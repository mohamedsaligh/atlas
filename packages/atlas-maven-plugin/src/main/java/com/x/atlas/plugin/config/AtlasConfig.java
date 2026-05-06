package com.x.atlas.plugin.config;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.dataformat.yaml.YAMLFactory;
import com.networknt.schema.JsonSchema;
import com.networknt.schema.JsonSchemaFactory;
import com.networknt.schema.SpecVersion;
import com.networknt.schema.ValidationMessage;
import java.io.IOException;
import java.io.InputStream;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.Set;

/**
 * Load + validate atlas.yml. Pure data — no IO concerns leak past load().
 */
public final class AtlasConfig {

    private static final ObjectMapper YAML = new ObjectMapper(new YAMLFactory());
    private static final ObjectMapper JSON = new ObjectMapper();

    public final List<Project> projects;
    public final Storage storage;

    private AtlasConfig(List<Project> projects, Storage storage) {
        this.projects = projects;
        this.storage = storage;
    }

    public static AtlasConfig load(Path configFile) throws IOException {
        validate(configFile);
        Map<String, Object> root = YAML.readValue(configFile.toFile(),
                new com.fasterxml.jackson.core.type.TypeReference<>() {});
        return parse(root);
    }

    private static void validate(Path configFile) throws IOException {
        try (InputStream s = AtlasConfig.class.getResourceAsStream("/atlas-config.schema.json")) {
            if (s == null) {
                // Fallback: locate via repo root (dev runs).
                Path repoRoot = configFile.getParent();
                while (repoRoot != null && !Files.exists(repoRoot.resolve("schemas"))) {
                    repoRoot = repoRoot.getParent();
                }
                if (repoRoot == null) {
                    throw new IOException("atlas-config.schema.json not on classpath");
                }
                Path schemaPath = repoRoot.resolve("schemas/atlas-config.schema.json");
                JsonSchemaFactory factory = JsonSchemaFactory.getInstance(SpecVersion.VersionFlag.V202012);
                JsonSchema schema = factory.getSchema(JSON.readTree(schemaPath.toFile()));
                Set<ValidationMessage> errors = schema.validate(JSON.valueToTree(YAML.readValue(configFile.toFile(), Object.class)));
                if (!errors.isEmpty()) {
                    throw new IOException("atlas.yml invalid:\n" + String.join("\n",
                            errors.stream().map(ValidationMessage::getMessage).toList()));
                }
                return;
            }
            JsonSchemaFactory factory = JsonSchemaFactory.getInstance(SpecVersion.VersionFlag.V202012);
            JsonSchema schema = factory.getSchema(s);
            Set<ValidationMessage> errors = schema.validate(JSON.valueToTree(YAML.readValue(configFile.toFile(), Object.class)));
            if (!errors.isEmpty()) {
                throw new IOException("atlas.yml invalid:\n" + String.join("\n",
                        errors.stream().map(ValidationMessage::getMessage).toList()));
            }
        }
    }

    @SuppressWarnings("unchecked")
    private static AtlasConfig parse(Map<String, Object> root) {
        List<Project> projects = new ArrayList<>();
        for (Map<String, Object> p : (List<Map<String, Object>>) root.getOrDefault("projects", List.of())) {
            projects.add(Project.parse(p));
        }
        Storage storage = Storage.parse((Map<String, Object>) root.getOrDefault("storage", Map.of()));
        return new AtlasConfig(projects, storage);
    }

    public static final class Project {
        public final String id;
        public final String description;
        public final List<Repo> repos;
        public final List<DomainPair> domainPairs;

        public Project(String id, String description, List<Repo> repos, List<DomainPair> domainPairs) {
            this.id = id;
            this.description = description;
            this.repos = repos;
            this.domainPairs = domainPairs;
        }

        @SuppressWarnings("unchecked")
        static Project parse(Map<String, Object> m) {
            List<Repo> repos = new ArrayList<>();
            for (Map<String, Object> r : (List<Map<String, Object>>) m.getOrDefault("repos", List.of())) {
                repos.add(Repo.parse(r));
            }
            List<DomainPair> pairs = new ArrayList<>();
            for (Map<String, Object> p : (List<Map<String, Object>>) m.getOrDefault("domain_pairs", List.of())) {
                pairs.add(DomainPair.parse(p));
            }
            return new Project((String) m.get("id"), (String) m.get("description"), repos, pairs);
        }
    }

    public static final class Repo {
        public final String id;
        public final String path;
        public final Bitbucket bitbucket;

        public Repo(String id, String path, Bitbucket bitbucket) {
            this.id = id;
            this.path = path;
            this.bitbucket = bitbucket;
        }

        @SuppressWarnings("unchecked")
        static Repo parse(Map<String, Object> m) {
            Map<String, Object> bb = (Map<String, Object>) m.get("bitbucket");
            Bitbucket bitbucket = bb == null ? null : new Bitbucket(
                    (String) bb.get("base_url"), (String) bb.get("project_key"),
                    (String) bb.get("repo_slug"), (String) bb.getOrDefault("api_kind", "server")
            );
            return new Repo((String) m.get("id"), (String) m.get("path"), bitbucket);
        }
    }

    public record Bitbucket(String baseUrl, String projectKey, String repoSlug, String apiKind) {}

    public static final class DomainPair {
        public final String id;
        public final List<SchemaRef> sources;
        public final List<SchemaRef> targets;
        public final List<String> scanPackages;
        public final List<ScopeRule> scopeRules;
        public final List<ExtractorSpec> extractors;

        public DomainPair(String id, List<SchemaRef> sources, List<SchemaRef> targets,
                          List<String> scanPackages, List<ScopeRule> scopeRules,
                          List<ExtractorSpec> extractors) {
            this.id = id;
            this.sources = sources;
            this.targets = targets;
            this.scanPackages = scanPackages;
            this.scopeRules = scopeRules;
            this.extractors = extractors;
        }

        @SuppressWarnings("unchecked")
        static DomainPair parse(Map<String, Object> m) {
            List<SchemaRef> sources = SchemaRef.parseListOrObject(m.get("source"));
            List<SchemaRef> targets = SchemaRef.parseListOrObject(m.get("target"));
            List<String> packages = (List<String>) m.getOrDefault("scan_packages", List.of());
            List<ScopeRule> rules = new ArrayList<>();
            Map<String, Object> si = (Map<String, Object>) m.get("scope_inference");
            if (si != null) {
                for (Map<String, Object> r : (List<Map<String, Object>>) si.getOrDefault("rules", List.of())) {
                    rules.add(new ScopeRule(
                            (String) r.get("pattern"),
                            (Map<String, Object>) r.get("scope"),
                            (List<String>) r.getOrDefault("capture", List.of())
                    ));
                }
            }
            List<ExtractorSpec> extractors = new ArrayList<>();
            for (Map<String, Object> e : (List<Map<String, Object>>) m.getOrDefault("extractors", List.of())) {
                extractors.add(new ExtractorSpec(
                        (String) e.get("type"),
                        (Map<String, Object>) e.getOrDefault("options", Map.of())
                ));
            }
            return new DomainPair(
                    (String) m.get("id"),
                    sources, targets, packages, rules, extractors
            );
        }
    }

    public record SchemaRef(String name, String schemaFile, String schemaKind, List<String> typeFqns) {
        @SuppressWarnings("unchecked")
        static SchemaRef parse(Map<String, Object> m) {
            List<String> fqns = (List<String>) m.getOrDefault("type_fqns", List.of());
            return new SchemaRef(
                    (String) m.get("name"),
                    (String) m.get("schema_file"),
                    (String) m.get("schema_kind"),
                    fqns == null ? List.of() : fqns
            );
        }

        @SuppressWarnings("unchecked")
        static List<SchemaRef> parseListOrObject(Object value) {
            if (value == null) return List.of();
            if (value instanceof List<?> list) {
                List<SchemaRef> out = new ArrayList<>();
                for (Object item : list) {
                    if (item instanceof Map<?, ?> map) {
                        out.add(parse((Map<String, Object>) map));
                    }
                }
                return out;
            }
            if (value instanceof Map<?, ?> map) {
                return List.of(parse((Map<String, Object>) map));
            }
            return List.of();
        }
    }

    public record ScopeRule(String pattern, Map<String, Object> scope, List<String> capture) {}
    public record ExtractorSpec(String type, Map<String, Object> options) {}

    public record Storage(String atlasKbPath, String atlasKbRepo, String localCache, String sqlitePath) {
        static Storage parse(Map<String, Object> m) {
            return new Storage(
                    (String) m.get("atlas_kb_path"),
                    (String) m.get("atlas_kb_repo"),
                    (String) m.get("local_cache"),
                    (String) m.get("sqlite_path")
            );
        }
    }
}
