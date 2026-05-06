package com.x.atlas.core.annotation;

import java.lang.annotation.ElementType;
import java.lang.annotation.Retention;
import java.lang.annotation.RetentionPolicy;
import java.lang.annotation.Target;

/**
 * Declares the edge ids covered by a test method. Optional; the extractor's
 * default test linker matches by target field path on assertions, but this
 * annotation is the deterministic override when matching is ambiguous.
 */
@Retention(RetentionPolicy.SOURCE)
@Target(ElementType.METHOD)
public @interface AtlasCovers {
    /** Edge ids, e.g. "payment-service.mt103_to_local.e_a1b2c3d4". */
    String[] value();
}
