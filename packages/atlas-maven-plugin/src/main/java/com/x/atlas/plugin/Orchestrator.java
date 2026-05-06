package com.x.atlas.plugin;

import com.x.atlas.core.io.DeterministicJson;
import com.x.atlas.core.io.ManifestChecksum;
import com.x.atlas.core.model.CoverageManifest;
import com.x.atlas.core.model.CoverageManifest.UnparseableFile;
import com.x.atlas.core.model.Edge;
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

/**
 * Runs all configured extractors for one (project, repo, pair) combination.
 * Merges edges, dedupes by edgeId, sorts deterministically, stamps checksum.
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
        List<MappingExtractor> enabled = enabledFor(pair);

        ExtractorContext ctx = new ExtractorContext(
                project.id,
                repo.id,
                repoRoot,
                pair.id,
                toCoreSchemaRef(pair.source),
                toCoreSchemaRef(pair.target),
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
        List<String> extendedPackages = new java.util.ArrayList<>(pair.scanPackages);
        java.util.Set<String> generatedRoots = new java.util.LinkedHashSet<>();
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

        // Dedupe by edgeId, deterministic sort.
        Map<String, Edge> byId = new LinkedHashMap<>();
        for (Edge e : allEdges) byId.putIfAbsent(e.edgeId(), e);
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
                pair.id,
                git,
                toCoreSchemaRef(pair.source),
                toCoreSchemaRef(pair.target),
                enabled.stream()
                        .map(x -> new Manifest.ExtractorEntry(x.id(), x.version(), null))
                        .sorted(Comparator.comparing(Manifest.ExtractorEntry::id))
                        .toList(),
                sorted,
                new Manifest.Stats(candidates.size(), mapperIds.size(), sorted.size(), byKind, byMapperKind),
                ""
        );
        manifest = ManifestChecksum.stamp(manifest);

        CoverageManifest coverage = new CoverageManifest(
                CoverageManifest.CURRENT_SCHEMA_VERSION,
                project.id,
                repo.id,
                pair.id,
                Instant.parse("2026-01-01T00:00:00Z").toString(),
                "0".repeat(40),
                candidates.size(),
                mapperIds.size(),
                sorted.size(),
                byMapperKind,
                byKind,
                unparseable.stream()
                        .sorted(Comparator.comparing(UnparseableFile::file))
                        .toList(),
                List.of(),
                ignored.stream().sorted().distinct().toList(),
                enabled.stream().collect(java.util.stream.Collectors.toMap(
                        MappingExtractor::id, MappingExtractor::version,
                        (a, b) -> a, TreeMap::new)),
                null,
                ""
        );
        coverage = ManifestChecksum.stamp(coverage);

        Path outDir = repoRoot.resolve("target/atlas/manifests");
        Path covDir = repoRoot.resolve("target/atlas/coverage");
        DeterministicJson.writeFile(outDir.resolve(pair.id + ".manifest.json"), manifest);
        DeterministicJson.writeFile(covDir.resolve(pair.id + ".coverage-manifest.json"), coverage);

        return new RunResult(manifest, coverage, !unparseable.isEmpty());
    }

    private List<MappingExtractor> enabledFor(AtlasConfig.DomainPair pair) {
        if (pair.extractors == null || pair.extractors.isEmpty()) {
            return registry; // default: all registered
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

    public record RunResult(Manifest manifest, CoverageManifest coverage, boolean hasUnparseable) {}
}
