package com.x.atlas.core.model;

import com.fasterxml.jackson.annotation.JsonInclude;

/**
 * Tags inferred from package path. Any field may be null when not applicable.
 */
@JsonInclude(JsonInclude.Include.NON_ABSENT)
public record Scope(
        Boolean common,
        String country,
        String clearing,
        String product,
        String fieldGroup
) {
    public static Scope ofCommon() {
        return new Scope(Boolean.TRUE, null, null, null, null);
    }

    public static Scope ofEmpty() {
        return new Scope(null, null, null, null, null);
    }
}
