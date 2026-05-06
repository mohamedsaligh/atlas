package com.x.atlas.plugin.git;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.HashMap;
import java.util.Map;

/**
 * Captures git metadata (sha, branch, repo, blob shas) once per extraction
 * via {@code git} CLI. Determinism: results are cached per (repoRoot, file).
 */
public final class GitRefCapture {

    private final Path repoRoot;
    private final String headSha;
    private final String branch;
    private final String repoUrl;
    private final Map<String, String> blobShaByFile = new HashMap<>();

    private static final Map<Path, GitRefCapture> CACHE = new java.util.concurrent.ConcurrentHashMap<>();

    public static GitRefCapture forRepo(Path repoRoot) {
        return CACHE.computeIfAbsent(repoRoot.toAbsolutePath().normalize(), GitRefCapture::new);
    }

    public GitRefCapture(Path repoRoot) {
        this.repoRoot = repoRoot;
        this.headSha = readGit(repoRoot, "rev-parse", "HEAD");
        this.branch = readGit(repoRoot, "rev-parse", "--abbrev-ref", "HEAD");
        this.repoUrl = readGitOrigin(repoRoot);
    }

    public String headSha() { return headSha != null ? headSha : "0".repeat(40); }
    public String branch()  { return branch != null ? branch : "main"; }
    public String repoUrl() { return repoUrl != null ? repoUrl : ""; }

    public String blobShaFor(Path repoRelative) {
        String key = repoRelative.toString().replace('\\', '/');
        return blobShaByFile.computeIfAbsent(key, k -> {
            String out = readGit(repoRoot, "ls-tree", headSha(), k);
            // Output: "100644 blob <sha>\t<path>"
            if (out == null || out.isBlank()) return null;
            String[] parts = out.split("\\s+");
            return parts.length >= 3 ? parts[2] : null;
        });
    }

    private static String readGit(Path repoRoot, String... args) {
        try {
            String[] cmd = new String[args.length + 1];
            cmd[0] = "git";
            System.arraycopy(args, 0, cmd, 1, args.length);
            ProcessBuilder pb = new ProcessBuilder(cmd).directory(repoRoot.toFile())
                    .redirectErrorStream(true);
            Process p = pb.start();
            byte[] bytes = p.getInputStream().readAllBytes();
            int rc = p.waitFor();
            if (rc != 0) return null;
            return new String(bytes, StandardCharsets.UTF_8).trim();
        } catch (Exception e) {
            return null;
        }
    }

    private static String readGitOrigin(Path repoRoot) {
        String url = readGit(repoRoot, "config", "--get", "remote.origin.url");
        if (url == null || url.isBlank()) {
            // Fallback: walk up to .git/config in case shell captures fail.
            try {
                Path cfg = repoRoot.resolve(".git/config");
                if (Files.exists(cfg)) {
                    String txt = Files.readString(cfg);
                    int i = txt.indexOf("[remote \"origin\"]");
                    if (i >= 0) {
                        int u = txt.indexOf("url =", i);
                        if (u > 0) {
                            int eol = txt.indexOf('\n', u);
                            return txt.substring(u + 5, eol < 0 ? txt.length() : eol).trim();
                        }
                    }
                }
            } catch (IOException ignore) {}
        }
        return url;
    }
}
