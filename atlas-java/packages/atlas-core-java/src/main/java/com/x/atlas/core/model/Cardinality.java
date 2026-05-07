package com.x.atlas.core.model;

import com.fasterxml.jackson.annotation.JsonProperty;

public enum Cardinality {
    @JsonProperty("1:1") ONE_TO_ONE,
    @JsonProperty("1:N") ONE_TO_MANY,
    @JsonProperty("N:1") MANY_TO_ONE,
    @JsonProperty("N:M") MANY_TO_MANY
}
