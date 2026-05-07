package com.x.atlas.plugin.io;

import java.io.IOException;
import java.nio.file.FileSystems;
import java.nio.file.FileVisitResult;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.PathMatcher;
import java.nio.file.SimpleFileVisitor;
import java.nio.file.attribute.BasicFileAttributes;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.List;
import java.util.Locale;
import java.util.Set;

/**
 * Walks a repo for files matching a list of glob patterns. Prunes noise
 * directories (.git/, target/, node_modules/, etc.) to keep walks fast on
 * large monorepos and slow filesystems (network drives, antivirus-scanned).
 *
 * <p>Two whitelisted exceptions inside {@code target/}:
 * {@code target/generated-sources/} (MapStruct impls live here) and
 * {@code target/atlas/} (our own outputs).
 */
public final class PathScanner {

    private PathScanner() {}

    /** Directories never worth walking into for source extraction. */
    private static final Set<String> SKIP_NAMES = Set.of(
            ".git", ".idea", ".vscode", ".gradle", ".settings",
            "node_modules", "build", "out", "bin", "dist",
            ".next", ".nuxt", ".cache", ".m2"
    );

    public static List<Path> scan(Path repoRoot, List<String> globs, String suffix) throws IOException {
        List<PathMatcher> matchers = globs.stream()
                .map(g -> FileSystems.getDefault().getPathMatcher("glob:" + g))
                .toList();
        List<Path> hits = new ArrayList<>();
        if (!Files.exists(repoRoot)) return hits;

        Files.walkFileTree(repoRoot, new SimpleFileVisitor<>() {
            @Override
            public FileVisitResult preVisitDirectory(Path dir, BasicFileAttributes attrs) {
                String name = dir.getFileName() == null ? "" : dir.getFileName().toString();
                if (SKIP_NAMES.contains(name)) {
                    return FileVisitResult.SKIP_SUBTREE;
                }
                if ("target".equals(name)) {
                    // Allow only target/generated-sources and target/atlas underneath.
                    // Skip everything else under target/.
                    return FileVisitResult.CONTINUE;
                }
                if ("classes".equals(name) || "test-classes".equals(name)) {
                    Path parent = dir.getParent();
                    if (parent != null && "target".equals(parent.getFileName() == null ? "" : parent.getFileName().toString())) {
                        return FileVisitResult.SKIP_SUBTREE;
                    }
                }
                if ("dependency".equals(name) || "site".equals(name) || "reports".equals(name)
                        || "surefire-reports".equals(name) || "failsafe-reports".equals(name)) {
                    Path parent = dir.getParent();
                    if (parent != null && "target".equals(parent.getFileName() == null ? "" : parent.getFileName().toString())) {
                        return FileVisitResult.SKIP_SUBTREE;
                    }
                }
                return FileVisitResult.CONTINUE;
            }

            @Override
            public FileVisitResult visitFile(Path file, BasicFileAttributes attrs) {
                if (suffix != null && !file.toString().endsWith(suffix)) {
                    return FileVisitResult.CONTINUE;
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
                return FileVisitResult.CONTINUE;
            }

            @Override
            public FileVisitResult visitFileFailed(Path file, IOException exc) {
                return FileVisitResult.CONTINUE;
            }
        });

        hits.sort(Comparator.comparing(p ->
                repoRoot.relativize(p).toString().replace('\\', '/').toLowerCase(Locale.ROOT)));
        return hits;
    }
}
