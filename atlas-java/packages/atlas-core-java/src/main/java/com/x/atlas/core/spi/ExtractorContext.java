package com.x.atlas.core.spi;

import com.x.atlas.core.model.Manifest.SchemaRef;
import java.nio.file.Path;
import java.util.List;
import java.util.Map;
import java.util.Set;

/**
 * Inputs handed to every extractor. Immutable and shared across files within
 * one (project, repo, pair) extraction.
 *
 * @param projectId       Project id from atlas.yml.
 * @param repoId          Repo id from atlas.yml.
 * @param repoRoot        Absolute path to the repo root.
 * @param pairId          Domain pair id from atlas.yml.
 * @param source          Source schema ref.
 * @param target          Target schema ref.
 * @param sourceTypes     Java FQNs that count as source-pair types.
 * @param targetTypes     Java FQNs that count as target-pair types.
 * @param scanPackages    Globs (repo-relative) defining which files this pair owns.
 * @param scopeRules      Path-pattern rules for inferring scope tags.
 * @param options         This extractor's options block from atlas.yml.
 * @param classpath       Compiled classpath roots used for symbol resolution.
 * @param sourceRoots     Source roots (e.g., {@code src/main/java}, {@code target/generated-sources/annotations}).
 * @param businessKeys    Map of (schemaFile, fieldPath) → businessKey extracted from schema annotations.
 */
public record ExtractorContext(
        String projectId,
        String repoId,
        Path repoRoot,
        String pairId,
        SchemaRef source,
        SchemaRef target,
        Set<String> sourceTypes,
        Set<String> targetTypes,
        List<String> scanPackages,
        List<ScopeRule> scopeRules,
        Map<String, Object> options,
        List<Path> classpath,
        List<Path> sourceRoots,
        Map<String, Map<String, String>> businessKeys
) {
    /** Glob pattern + scope assignment / capture spec. */
    public record ScopeRule(
            String pattern,
            Map<String, Object> scope,
            List<String> capture
    ) {}
}
