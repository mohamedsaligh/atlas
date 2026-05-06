package com.x.atlas.core.annotation;

import java.lang.annotation.ElementType;
import java.lang.annotation.Retention;
import java.lang.annotation.RetentionPolicy;
import java.lang.annotation.Target;

/**
 * Marks a class, method, or field to be skipped by Atlas extraction.
 * Recorded in the coverage manifest under {@code ignoredByAnnotation}.
 */
@Retention(RetentionPolicy.SOURCE)
@Target({ElementType.TYPE, ElementType.METHOD, ElementType.FIELD})
public @interface AtlasIgnore {
    String reason() default "";
}
