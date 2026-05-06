package com.x.atlas.plugin;

import com.x.atlas.core.io.DeterministicJson;
import com.x.atlas.core.io.ManifestChecksum;
import com.x.atlas.core.model.CoverageManifest;
import com.x.atlas.core.model.CoverageManifest.UnparseableFile;
import com.x.atlas.core.model.Edge;
import com.x.atlas.core.model.FieldRef;
import com.x.atlas.core.model.Manifest;
import com.x.atlas.core.model.Manifest.SchemaRef;
import com.x.atlas.core.spi.ExtractorContext;
import com.x.atlas.core.spi.ExtractorResult;
import com.x.atlas.core.spi.MappingExtractor;
import com.x.atlas.plugin.config.AtlasConfig;
import com.x.atlas.plugin.io.PathScanner;
import java.io.IOException;
import java.nio.file.Path;
import java.time.Instant;
import java.util.*;
import java.util.stream.Collectors;

/**
 * Runs all configured extractors for one (project, repo, pair) combination.
 * Supports multi-source / multi-target pairs: scans once, then groups edges
 * by (source.schemaFile, target.schemaFile) and emits one manifest per group.
 */
public final class Orchestrator {

    private final List<MappingExtractor> registry;

    public Orchestrator() {
        this.registry = ServiceLoader.load(MappingExtractor.class).stream()
                .map(ServiceLoader.Provider::get)
                .sorted(Comparator.comparing(MappingExtractor::id))
                .toList();
    }

    public RunResult runPair(
            AtlasConfig.Project project,
            AtlasConfig.Repo repo,
            AtlasConfig.DomainPair pair,
            Path repoRoot,
            List<Path> sourceRoots,
            List<Path> classpath,
            Map<String, Map<String, String>> businessKeys
    ) throws IOException {
        if (pair.sources.isEmpty() || pair.targets.isEmpty()) {
            throw new IOException("Pair " + pair.id + " has empty source or target");
        }

        List<MappingExtractor> enabled = enabledFor(pair);

        // Build FQN -> SchemaRef maps. When type_fqns is empty for a single-entry
        // source/target list, every edge falls back to that singleton schema.
        Map<String, AtlasConfig.SchemaRef> fqnToSource = buildFqnMap(pair.sources);
        Map<String, AtlasConfig.SchemaRef> fqnToTarget = buildFqnMap(pair.targets);

        AtlasConfig.SchemaRef defaultSource = pair.sources.get(0);
        AtlasConfig.SchemaRef defaultTarget = pair.targets.get(0);

        ExtractorContext ctx = new ExtractorContext(
                project.id,
                repo.id,
                repoRoot,
                pair.id,
                toCoreSchemaRef(defaultSource),
                toCoreSchemaRef(defaultTarget),
                Set.of(),
                Set.of(),
                pair.scanPackages,
                pair.scopeRules.stream()
                        .map(r -> new ExtractorContext.ScopeRule(r.pattern(), r.scope(), r.capture()))
                        .toList(),
                Map.of(),
                classpath,
                sourceRoots,
                businessKeys
        );

        // Auto-extend scan_packages with each parent's generated-sources path.
        List<String> extendedPackages = new ArrayList<>(pair.scanPackages);
        Set<String> generatedRoots = new LinkedHashSet<>();
        for (String g : pair.scanPackages) {
            int srcIdx = g.indexOf("/src/main/java/");
            if (srcIdx > 0) {
                String moduleRoot = g.substring(0, srcIdx);
                generatedRoots.add(moduleRoot + "/target/generated-sources/annotations/**");
            }
        }
        extendedPackages.addAll(generatedRoots);

        List<Path> candidates = PathScanner.scan(repoRoot, extendedPackages, ".java");

        List<Edge> allEdges = new ArrayList<>();
        List<UnparseableFile> unparseable = new ArrayList<>();
        List<String> ignored = new ArrayList<>();

        for (Path file : candidates) {
            for (MappingExtractor x : enabled) {
                if (x.supports(ctx, file)) {
                    ExtractorResult r = x.extract(ctx, file);
                    allEdges.addAll(r.edges());
                    unparseable.addAll(r.unparseable());
                    ignored.addAll(r.ignoredByAnnotation());
                    break;
                }
            }
        }
        for (MappingExtractor x : enabled) {
            ExtractorResult r = x.extractAll(ctx);
            allEdges.addAll(r.edges());
            unparseable.addAll(r.unparseable());
            ignored.addAll(r.ignoredByAnnotation());
        }

        // Re-tag each edge's source/target schemaFile based on its actual FQN.
        List<Edge> retagged = new ArrayList<>(allEdges.size());
        for (Edge e : allEdges) {
            FieldRef src = e.source();
            FieldRef tgt = e.target();

            AtlasConfig.SchemaRef matchedSrc = src == null
                    ? defaultSource
                    : fqnToSource.getOrDefault(src.type(), defaultSource);
            AtlasConfig.SchemaRef matchedTgt = fqnToTarget.getOrDefault(
                    tgt == null ? "" : tgt.type(), defaultTarget);

            FieldRef newSrc = src == null ? null
                    : new FieldRef(src.type(), src.path(), matchedSrc.schemaFile(), src.businessKey());
            FieldRef newTgt = tgt == null ? null
                    : new FieldRef(tgt.type(), tgt.path(), matchedTgt.schemaFile(), tgt.businessKey());

            retagged.add(retag(e, newSrc, newTgt));
        }

        boolean multi = pair.sources.size() > 1 || pair.targets.size() > 1;

        List<Manifest> manifests = new ArrayList<>();
        List<CoverageManifest> coverages = new ArrayList<>();

        if (!multi) {
            // Single source × single target: one manifest with all edges.
            RunResult one = emitOne(
                    project, repo, pair, repoRoot,
                    enabled, candidates.size(),
                    pair.id, defaultSource, defaultTarget,
                    retagged, unparseable, ignored
            );
            manifests.addAll(one.manifests());
            coverages.addAll(one.coverages());
        } else {
            // Multi: group edges by (source.schemaFile, target.schemaFile),
            // then emit one manifest per group with effective_pair_id.
            Map<String, AtlasConfig.SchemaRef> sourceByFile = bySchemaFile(pair.sources);
            Map<String, AtlasConfig.SchemaRef> targetByFile = bySchemaFile(pair.targets);

            Map<GroupKey, List<Edge>> grouped = new LinkedHashMap<>();
            for (Edge e : retagged) {
                String srcFile = e.source() == null ? defaultSource.schemaFile() : e.source().schemaFile();
                String tgtFile = e.target() == null ? defaultTarget.schemaFile() : e.target().schemaFile();
                grouped.computeIfAbsent(new GroupKey(srcFile, tgtFile), k -> new ArrayList<>()).add(e);
            }
            if (grouped.isEmpty()) {
                grouped.put(new GroupKey(defaultSource.schemaFile(), defaultTarget.schemaFile()), List.of());
            }
            for (Map.Entry<GroupKey, List<Edge>> entry : grouped.entrySet()) {
                GroupKey k = entry.getKey();
                AtlasConfig.SchemaRef src = sourceByFile.getOrDefault(k.sourceSchemaFile(), defaultSource);
                AtlasConfig.SchemaRef tgt = targetByFile.getOrDefault(k.targetSchemaFile(), defaultTarget);
                String effectivePairId = sanitize(pair.id + "__" + src.name() + "_to_" + tgt.name());
                RunResult one = emitOne(
                        project, repo, pair, repoRoot,
                        enabled, candidates.size(),
                        effectivePairId, src, tgt,
                        entry.getValue(), unparseable, ignored
                );
                manifests.addAll(one.manifests());
                coverages.addAll(one.coverages());
            }
        }

        return new RunResult(manifests, coverages, !unparseable.isEmpty());
    }

    private RunResult emitOne(
            AtlasConfig.Project project,
            AtlasConfig.Repo repo,
            AtlasConfig.DomainPair pair,
            Path repoRoot,
            List<MappingExtractor> enabled,
            int filesScanned,
            String effectivePairId,
            AtlasConfig.SchemaRef src,
            AtlasConfig.SchemaRef tgt,
            List<Edge> edges,
            List<UnparseableFile> unparseable,
            List<String> ignored
    ) throws IOException {
        Map<String, Edge> byId = new LinkedHashMap<>();
        for (Edge e : edges) byId.putIfAbsent(e.edgeId(), e);
        List<Edge> sorted = new ArrayList<>(byId.values());
        sorted.sort(Comparator
                .comparing((Edge e) -> e.git() == null ? "" : e.git().file())
                .thenComparingInt(e -> e.git() == null ? 0 : e.git().line())
                .thenComparing(e -> e.target() == null ? "" : e.target().path())
                .thenComparing(e -> e.source() == null ? "" : (e.source().path() == null ? "" : e.source().path()))
                .thenComparing(Edge::edgeId));

        Map<String, Integer> byKind = new TreeMap<>();
        Map<String, Integer> byMapperKind = new TreeMap<>();
        Set<String> mapperIds = new TreeSet<>();
        for (Edge e : sorted) {
            byKind.merge(e.kind().name().toLowerCase(Locale.ROOT), 1, Integer::sum);
            byMapperKind.merge(e.mapperKind(), 1, Integer::sum);
            if (e.mapperId() != null) mapperIds.add(e.mapperId());
        }

        Manifest.ManifestGit git = new Manifest.ManifestGit("", "0".repeat(40), "main");

        Manifest manifest = new Manifest(
                "0.1.0",
                Manifest.CURRENT_SCHEMA_VERSION,
                project.id,
                repo.id,
                effectivePairId,
                git,
                toCoreSchemaRef(src),
                toCoreSchemaRef(tgt),
                enabled.stream()
                        .map(x -> new Manifest.ExtractorEntry(x.id(), x.version(), null))
                        .sorted(Comparator.comparing(Manifest.ExtractorEntry::id))
                        .toList(),
                sorted,
                new Manifest.Stats(filesScanned, mapperIds.size(), sorted.size(), byKind, byMapperKind),
                ""
        );
        manifest = ManifestChecksum.stamp(manifest);

        CoverageManifest coverage = new CoverageManifest(
                CoverageManifest.CURRENT_SCHEMA_VERSION,
                project.id,
                repo.id,
                effectivePairId,
                Instant.parse("2026-01-01T00:00:00Z").toString(),
                "0".repeat(40),
                filesScanned,
                mapperIds.size(),
                sorted.size(),
                byMapperKind,
                byKind,
                unparseable.stream().sorted(Comparator.comparing(UnparseableFile::file)).toList(),
                List.of(),
                ignored.stream().sorted().distinct().toList(),
                enabled.stream().collect(Collectors.toMap(
                        MappingExtractor::id, MappingExtractor::version,
                        (a, b) -> a, TreeMap::new)),
                null,
                ""
        );
        coverage = ManifestChecksum.stamp(coverage);

        Path outDir = repoRoot.resolve("target/atlas/manifests");
        Path covDir = repoRoot.resolve("target/atlas/coverage");
        DeterministicJson.writeFile(outDir.resolve(effectivePairId + ".manifest.json"), manifest);
        DeterministicJson.writeFile(covDir.resolve(effectivePairId + ".coverage-manifest.json"), coverage);

        return new RunResult(List.of(manifest), List.of(coverage), !unparseable.isEmpty());
    }

    private static Map<String, AtlasConfig.SchemaRef> buildFqnMap(List<AtlasConfig.SchemaRef> refs) {
        Map<String, AtlasConfig.SchemaRef> out = new HashMap<>();
        for (AtlasConfig.SchemaRef r : refs) {
            if (r.typeFqns() == null || r.typeFqns().isEmpty()) continue;
            for (String fqn : r.typeFqns()) {
                out.put(fqn, r);
            }
        }
        return out;
    }

    private static Map<String, AtlasConfig.SchemaRef> bySchemaFile(List<AtlasConfig.SchemaRef> refs) {
        Map<String, AtlasConfig.SchemaRef> out = new HashMap<>();
        for (AtlasConfig.SchemaRef r : refs) {
            out.put(r.schemaFile(), r);
        }
        return out;
    }

    private static Edge retag(Edge e, FieldRef newSource, FieldRef newTarget) {
        return new Edge(
                e.edgeId(), e.mapperId(), e.mapperKind(), e.kind(),
                newSource, newTarget,
                e.expression(), e.staticHelperFqn(),
                e.cardinality(), e.branchCondition(), e.formatSpec(),
                e.scope(), e.git(), e.testIds(), e.confidence()
        );
    }

    private List<MappingExtractor> enabledFor(AtlasConfig.DomainPair pair) {
        if (pair.extractors == null || pair.extractors.isEmpty()) {
            return registry;
        }
        Set<String> ids = new LinkedHashSet<>();
        for (var spec : pair.extractors) ids.add(spec.type());
        List<MappingExtractor> result = new ArrayList<>();
        for (String id : ids) {
            for (MappingExtractor x : registry) {
                if (x.id().equals(id)) {
                    result.add(x);
                    break;
                }
            }
        }
        return result;
    }

    private static SchemaRef toCoreSchemaRef(AtlasConfig.SchemaRef s) {
        return new SchemaRef(s.name(), s.schemaFile(), s.schemaKind());
    }

    private static String sanitize(String s) {
        return s.replaceAll("[^A-Za-z0-9_-]+", "_").toLowerCase(Locale.ROOT);
    }

    private record GroupKey(String sourceSchemaFile, String targetSchemaFile) {}

    public record RunResult(List<Manifest> manifests, List<CoverageManifest> coverages, boolean hasUnparseable) {}
}
