package com.x.atlas.core.annotation;

import java.lang.annotation.ElementType;
import java.lang.annotation.Retention;
import java.lang.annotation.RetentionPolicy;
import java.lang.annotation.Target;

/**
 * Declares a business identity for a field. Two fields sharing the same
 * {@code businessKey} are joined across pairs in cross-service lineage.
 *
 * <p>Prefer schema-side annotations (x-atlas-business-key) when the schema
 * supports it. Use this annotation on Java DTOs that don't have a generated
 * schema, or to override.
 */
@Retention(RetentionPolicy.SOURCE)
@Target({ElementType.FIELD, ElementType.METHOD})
public @interface AtlasField {

    /** Business key value, e.g. "DebtorIBAN". */
    String businessKey();

    /** Optional: qualifier when a single field needs context, e.g. currency for amount. */
    String qualifier() default "";
}
