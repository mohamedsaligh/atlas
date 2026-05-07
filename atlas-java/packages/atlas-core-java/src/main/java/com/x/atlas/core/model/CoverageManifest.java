package com.x.atlas.core.model;

import com.fasterxml.jackson.annotation.JsonInclude;
import java.util.List;
import java.util.Map;

/**
 * Per-extraction coverage telemetry. Build fails if {@code unparseableFiles}
 * is non-empty or if mapper count drops > 2σ vs baseline (drift gate).
 */
@JsonInclude(JsonInclude.Include.NON_ABSENT)
public record CoverageManifest(
        int schemaVersion,
        String projectId,
        String repoId,
        String pairId,
        String extractedAt,
        String gitSha,
        int filesScanned,
        int mappersDetected,
        int edgesEmitted,
        Map<String, Integer> byMapperKind,
        Map<String, Integer> byEdgeKind,
        List<UnparseableFile> unparseableFiles,
        List<UnmatchedTargetField> unmatchedTargetFields,
        List<String> ignoredByAnnotation,
        Map<String, String> extractorVersions,
        Drift drift,
        String checksum
) {
    public static final int CURRENT_SCHEMA_VERSION = 1;

    @JsonInclude(JsonInclude.Include.NON_ABSENT)
    public record UnparseableFile(String file, Integer line, String reason) {}

    public record UnmatchedTargetField(String targetPath, String schemaFile) {}

    @JsonInclude(JsonInclude.Include.NON_ABSENT)
    public record Drift(Integer baselineMappersDetected, Double deltaSigma, boolean accepted) {}
}
