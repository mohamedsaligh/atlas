package com.x.atlas.core.model;

import com.fasterxml.jackson.annotation.JsonInclude;

/**
 * Reference to a field in a domain schema.
 *
 * @param type        Java FQN of the holding class.
 * @param path        Dotted path within the schema.
 * @param schemaFile  Schema file relative to repo root.
 * @param businessKey Value of x-atlas-business-key on the field, when declared.
 */
@JsonInclude(JsonInclude.Include.NON_ABSENT)
public record FieldRef(
        String type,
        String path,
        String schemaFile,
        String businessKey
) {
    public FieldRef(String type, String path, String schemaFile) {
        this(type, path, schemaFile, null);
    }
}
