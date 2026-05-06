package com.x.atlas.core.spi;

import com.x.atlas.core.model.CoverageManifest.UnparseableFile;
import com.x.atlas.core.model.Edge;
import java.util.ArrayList;
import java.util.List;

/**
 * Per-extractor result for one candidate file (or aggregated across files,
 * extractor's choice — orchestrator merges by edgeId).
 */
public record ExtractorResult(
        List<Edge> edges,
        List<UnparseableFile> unparseable,
        List<String> ignoredByAnnotation,
        List<UnmatchedTarget> unmatchedTargets
) {
    public ExtractorResult {
        edges = edges == null ? List.of() : List.copyOf(edges);
        unparseable = unparseable == null ? List.of() : List.copyOf(unparseable);
        ignoredByAnnotation = ignoredByAnnotation == null ? List.of() : List.copyOf(ignoredByAnnotation);
        unmatchedTargets = unmatchedTargets == null ? List.of() : List.copyOf(unmatchedTargets);
    }

    /** Used when extractor encounters an unrecognised target write site for review. */
    public record UnmatchedTarget(String file, int line, String snippet, String reason) {}

    public static ExtractorResult empty() {
        return new ExtractorResult(List.of(), List.of(), List.of(), List.of());
    }

    public static Builder builder() { return new Builder(); }

    public static final class Builder {
        private final List<Edge> edges = new ArrayList<>();
        private final List<UnparseableFile> unparseable = new ArrayList<>();
        private final List<String> ignoredByAnnotation = new ArrayList<>();
        private final List<UnmatchedTarget> unmatchedTargets = new ArrayList<>();

        public Builder edge(Edge e) { edges.add(e); return this; }
        public Builder edges(List<Edge> es) { edges.addAll(es); return this; }
        public Builder unparseable(UnparseableFile u) { unparseable.add(u); return this; }
        public Builder ignored(String fqn) { ignoredByAnnotation.add(fqn); return this; }
        public Builder unmatched(UnmatchedTarget u) { unmatchedTargets.add(u); return this; }

        public ExtractorResult build() {
            return new ExtractorResult(edges, unparseable, ignoredByAnnotation, unmatchedTargets);
        }
    }
}
