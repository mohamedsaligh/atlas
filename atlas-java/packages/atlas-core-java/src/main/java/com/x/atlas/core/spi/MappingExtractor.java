package com.x.atlas.core.spi;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.node.JsonNodeFactory;
import java.nio.file.Path;

/**
 * Plug-in contract for a mapping extractor. New extractors register via
 * {@code META-INF/services/com.x.atlas.core.spi.MappingExtractor}.
 *
 * <p>Implementations <strong>must</strong> be deterministic: same inputs and
 * the same atlas-kb SHA produce byte-identical edges.
 */
public interface MappingExtractor {

    /**
     * Stable identifier used in {@code atlas.yml} {@code extractors[].type} and
     * recorded on every {@link com.x.atlas.core.model.Edge#mapperKind()}.
     * E.g. {@code mapstruct}, {@code plain-java}, {@code fixedlen-encoder},
     * {@code tagged-encoder}.
     */
    String id();

    /** Semver of the extractor implementation. Recorded in the manifest. */
    String version();

    /**
     * @return true if this extractor wants to handle the candidate file.
     *         Orchestrator runs all enabled extractors in registration order;
     *         the first to return {@code true} wins. Extractors that do not
     *         operate per-file (e.g., schema-driven) should return false here
     *         and override {@link #extractAll(ExtractorContext)} instead.
     */
    boolean supports(ExtractorContext ctx, Path candidate);

    /**
     * Extract edges from one candidate file. Default no-op; override when
     * {@link #supports(ExtractorContext, Path)} returns true.
     */
    default ExtractorResult extract(ExtractorContext ctx, Path candidate) {
        return ExtractorResult.empty();
    }

    /**
     * Extract edges that aren't tied to a single candidate file (e.g.,
     * an extractor that reads an external XML config). Default no-op;
     * the orchestrator calls this once per (project, repo, pair).
     */
    default ExtractorResult extractAll(ExtractorContext ctx) {
        return ExtractorResult.empty();
    }

    /**
     * JSON Schema describing this extractor's options block. Validated against
     * the value of {@code extractors[].options} in atlas.yml at config-load
     * time. Default = open object.
     */
    default JsonNode optionsSchema() {
        return JsonNodeFactory.instance.objectNode()
                .put("type", "object")
                .put("additionalProperties", true);
    }
}
