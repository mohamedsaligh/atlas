package com.x.atlas.core.model;

import com.fasterxml.jackson.annotation.JsonInclude;
import java.util.List;
import java.util.Map;

/**
 * Output of one extraction run for one (project, repo, pair).
 * Mirrors {@code schemas/manifest.schema.json}.
 */
@JsonInclude(JsonInclude.Include.NON_ABSENT)
public record Manifest(
        String atlasVersion,
        int schemaVersion,
        String projectId,
        String repoId,
        String pairId,
        ManifestGit git,
        SchemaRef source,
        SchemaRef target,
        List<ExtractorEntry> extractors,
        List<Edge> edges,
        Stats stats,
        String checksum
) {
    public static final int CURRENT_SCHEMA_VERSION = 1;

    public record ManifestGit(String repo, String sha, String branch) {}

    public record SchemaRef(String name, String schemaFile, String schemaKind) {}

    @JsonInclude(JsonInclude.Include.NON_ABSENT)
    public record ExtractorEntry(String id, String version, Map<String, Object> options) {}

    @JsonInclude(JsonInclude.Include.NON_ABSENT)
    public record Stats(
            int filesScanned,
            int mappersDetected,
            int edgesEmitted,
            Map<String, Integer> byKind,
            Map<String, Integer> byMapperKind
    ) {}
}
