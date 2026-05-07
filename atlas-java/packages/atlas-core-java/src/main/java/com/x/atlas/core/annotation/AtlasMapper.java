package com.x.atlas.core.annotation;

import java.lang.annotation.ElementType;
import java.lang.annotation.Retention;
import java.lang.annotation.RetentionPolicy;
import java.lang.annotation.Target;

/**
 * Marks a class as an authoritative mapper. Atlas treats the class as a Layer-1
 * mapper regardless of naming or package. Use for non-MapStruct mappers that
 * cannot be moved into a {@code mapper/} package.
 */
@Retention(RetentionPolicy.SOURCE)
@Target(ElementType.TYPE)
public @interface AtlasMapper {

    /** Source domain class. */
    Class<?> source();

    /** Target domain class. */
    Class<?> target();

    /** Free-form role: "core" (default), "pre", "post", "fixup". */
    String role() default "core";
}
