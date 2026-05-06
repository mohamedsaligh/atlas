package com.x.atlas.plugin.io;

import java.io.IOException;
import java.nio.file.FileSystems;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.PathMatcher;
import java.nio.file.attribute.BasicFileAttributes;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.List;
import java.util.Locale;

/**
 * Walks a repo for files matching a list of glob patterns. Deterministic
 * order: results sorted with {@link Comparator#naturalOrder()} after
 * normalising path separators to '/'.
 */
public final class PathScanner {

    private PathScanner() {}

    public static List<Path> scan(Path repoRoot, List<String> globs, String suffix) throws IOException {
        List<PathMatcher> matchers = globs.stream()
                .map(g -> FileSystems.getDefault().getPathMatcher("glob:" + g))
                .toList();
        List<Path> hits = new ArrayList<>();
        if (!Files.exists(repoRoot)) return hits;

        Files.walkFileTree(repoRoot, new java.nio.file.SimpleFileVisitor<>() {
            @Override
            public java.nio.file.FileVisitResult visitFile(Path file, BasicFileAttributes attrs) {
                if (suffix != null && !file.toString().endsWith(suffix)) {
                    return java.nio.file.FileVisitResult.CONTINUE;
                }
                Path rel = repoRoot.relativize(file);
                String relStr = rel.toString().replace('\\', '/');
                Path relUnix = Path.of(relStr);
                for (PathMatcher m : matchers) {
                    if (m.matches(relUnix)) {
                        hits.add(file);
                        break;
                    }
                }
                return java.nio.file.FileVisitResult.CONTINUE;
            }
        });

        hits.sort(Comparator.comparing(p ->
                repoRoot.relativize(p).toString().replace('\\', '/').toLowerCase(Locale.ROOT)));
        return hits;
    }
}
