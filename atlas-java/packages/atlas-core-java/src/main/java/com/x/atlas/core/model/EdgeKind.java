package com.x.atlas.core.model;

import com.fasterxml.jackson.annotation.JsonProperty;

/**
 * Discriminator on the RHS shape of an edge. Additive: never rename existing
 * values; only append new ones. Plugins that need a new kind must contribute
 * the value to this enum (deliberate evolution gate).
 */
public enum EdgeKind {

    /** RHS is {@code source.getX()} or a short null-safe chain. High confidence. */
    @JsonProperty("field_copy")     FIELD_COPY,

    /** RHS wraps a getter in a deterministic format call (substring, parseInt, BigDecimal::new). */
    @JsonProperty("format")         FORMAT,

    /** RHS is a multi-source / computed expression involving source getters. AST snippet captured. */
    @JsonProperty("expression")     EXPRESSION,

    /** RHS is a literal or static-final constant. */
    @JsonProperty("constant")       CONSTANT,

    /** RHS calls a static helper. {@code staticHelperFqn} captured. */
    @JsonProperty("static_call")    STATIC_CALL,

    /** RHS calls an instance helper / service. Low confidence. */
    @JsonProperty("enrichment")     ENRICHMENT,

    /** Same target field set under multiple branches. One edge per branch with branch predicate. */
    @JsonProperty("conditional")    CONDITIONAL,

    /** Source is iterable/array, target is iterable/array; element-level link with cardinality. */
    @JsonProperty("collection_map") COLLECTION_MAP,

    /** Target field present in target schema but never written by any mapper in scope. */
    @JsonProperty("unmapped")       UNMAPPED,

    /** Source and target type are the same (intra-domain reshuffle). */
    @JsonProperty("intra_domain")   INTRA_DOMAIN,

    /** {@code BeanUtils.copyProperties} or similar opaque copy. Per-field link unproven. */
    @JsonProperty("opaque_copy")    OPAQUE_COPY
}
