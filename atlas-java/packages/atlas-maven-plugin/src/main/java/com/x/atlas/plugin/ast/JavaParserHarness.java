package com.x.atlas.plugin.ast;

import com.github.javaparser.JavaParser;
import com.github.javaparser.ParseResult;
import com.github.javaparser.ParserConfiguration;
import com.github.javaparser.ast.CompilationUnit;
import com.github.javaparser.symbolsolver.JavaSymbolSolver;
import com.github.javaparser.symbolsolver.resolution.typesolvers.CombinedTypeSolver;
import com.github.javaparser.symbolsolver.resolution.typesolvers.JarTypeSolver;
import com.github.javaparser.symbolsolver.resolution.typesolvers.JavaParserTypeSolver;
import com.github.javaparser.symbolsolver.resolution.typesolvers.ReflectionTypeSolver;
import java.io.IOException;
import java.io.UncheckedIOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.concurrent.ConcurrentHashMap;

/**
 * Wires JavaParser + JavaSymbolSolver. One harness per (project, repo, pair).
 *
 * <p>The classpath/source roots come from the Maven project (Mojo passes them
 * in), so symbol resolution sees the user's actual dependencies.
 */
public final class JavaParserHarness {

    private static final Map<String, JavaParserHarness> CACHE = new ConcurrentHashMap<>();

    /**
     * Get a cached harness for the given (sourceRoots, classpath) pair, or build one.
     * Building is O(jars) — without caching, the orchestrator paid this cost per file
     * and ran for hours on real codebases.
     */
    public static JavaParserHarness forContext(List<Path> sourceRoots, List<Path> classpath) {
        String key = cacheKey(sourceRoots, classpath);
        return CACHE.computeIfAbsent(key, k -> new JavaParserHarness(sourceRoots, classpath));
    }

    private static String cacheKey(List<Path> sourceRoots, List<Path> classpath) {
        StringBuilder sb = new StringBuilder();
        for (Path p : sourceRoots) sb.append(p.toAbsolutePath().toString()).append('|');
        sb.append("##");
        for (Path p : classpath) sb.append(p.toAbsolutePath().toString()).append('|');
        return sb.toString();
    }

    private final JavaParser parser;

    public JavaParserHarness(List<Path> sourceRoots, List<Path> classpath) {
        // Symbol solving is intentionally OFF by default — it hangs on large
        // generated impls with deep classpath. Type FQN resolution is delegated
        // to TypeResolver (import-table based, O(1) per lookup, no class loading).
        // Set -Datlas.useSymbolSolver=true to opt in for richer resolution.
        ParserConfiguration cfg = new ParserConfiguration()
                .setLanguageLevel(ParserConfiguration.LanguageLevel.JAVA_17);
        if (Boolean.getBoolean("atlas.useSymbolSolver")) {
            CombinedTypeSolver solver = new CombinedTypeSolver();
            solver.add(new ReflectionTypeSolver());
            for (Path root : sourceRoots) {
                if (Files.exists(root)) {
                    solver.add(new JavaParserTypeSolver(root.toFile()));
                }
            }
            for (Path jar : classpath) {
                if (Files.exists(jar) && jar.toString().endsWith(".jar")) {
                    try {
                        solver.add(new JarTypeSolver(jar.toFile()));
                    } catch (IOException e) {
                        throw new UncheckedIOException("Failed to add jar to type solver: " + jar, e);
                    }
                }
            }
            cfg.setSymbolResolver(new JavaSymbolSolver(solver));
        }
        this.parser = new JavaParser(cfg);
    }

    public Optional<CompilationUnit> parse(Path file) {
        try {
            ParseResult<CompilationUnit> result = parser.parse(file);
            return result.getResult();
        } catch (IOException e) {
            return Optional.empty();
        }
    }
}
