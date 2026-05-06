package com.x.atlas.core.model;

import com.fasterxml.jackson.annotation.JsonInclude;

/**
 * Git anchor for a code location. Captured by the extractor — never by an LLM.
 *
 * @param repo      Origin URL (ssh or https) of the repo.
 * @param sha       40-char commit SHA.
 * @param file      Repo-relative file path.
 * @param line      1-based line number of the AST node.
 * @param browseUrl Pre-built Bitbucket / GitHub URL pinned to {@code sha} and {@code line}.
 * @param blobSha   40-char blob SHA of the file at {@code sha}, for downstream drift checks.
 */
@JsonInclude(JsonInclude.Include.NON_ABSENT)
public record GitRef(
        String repo,
        String sha,
        String file,
        int line,
        String browseUrl,
        String blobSha
) {
    public GitRef(String repo, String sha, String file, int line) {
        this(repo, sha, file, line, null, null);
    }
}
