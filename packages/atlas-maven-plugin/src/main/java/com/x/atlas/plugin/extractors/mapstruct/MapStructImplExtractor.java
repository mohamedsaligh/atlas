package com.x.atlas.plugin.extractors.mapstruct;

import com.github.javaparser.ast.CompilationUnit;
import com.github.javaparser.ast.body.ClassOrInterfaceDeclaration;
import com.github.javaparser.ast.body.MethodDeclaration;
import com.github.javaparser.ast.expr.*;
import com.github.javaparser.ast.stmt.BlockStmt;
import com.github.javaparser.ast.stmt.Statement;
import com.x.atlas.core.io.EdgeIdGenerator;
import com.x.atlas.core.model.*;
import com.x.atlas.core.scope.ScopeInferenceEngine;
import com.x.atlas.core.spi.ExtractorContext;
import com.x.atlas.core.spi.ExtractorResult;
import com.x.atlas.core.spi.MappingExtractor;
import com.x.atlas.plugin.ast.JavaParserHarness;
import com.x.atlas.plugin.git.GitRefCapture;
import java.nio.file.Path;
import java.util.*;

/**
 * Extracts edges from MapStruct-generated {@code *Impl.java} files. Operates
 * on fully-resolved code: every {@code target.setX(rhs)} is unambiguous after
 * annotation processing.
 *
 * <p>Recursive composition: when {@code target.setX(helper(...))} is seen, the
 * extractor walks {@code helper}'s body with the path prefix advanced to {@code x},
 * allowing nested setters in the helper to produce dotted paths
 * (e.g. {@code dbtrAcct.iban}).
 */
public final class MapStructImplExtractor implements MappingExtractor {

    private static final String ID = "mapstruct";
    private static final String VERSION = "0.1.0";
    private static final String GENERATED_MARKER = "org.mapstruct.ap.MappingProcessor";

    @Override public String id() { return ID; }
    @Override public String version() { return VERSION; }

    @Override
    public boolean supports(ExtractorContext ctx, Path candidate) {
        String s = candidate.toString().replace('\\', '/');
        if (!s.endsWith("Impl.java")) return false;
        if (!s.contains("/target/generated-sources/")) return false;
        try {
            String content = java.nio.file.Files.readString(candidate);
            return content.contains(GENERATED_MARKER);
        } catch (Exception e) {
            return false;
        }
    }

    @Override
    public ExtractorResult extract(ExtractorContext ctx, Path candidate) {
        JavaParserHarness harness = new JavaParserHarness(ctx.sourceRoots(), ctx.classpath());
        Optional<CompilationUnit> cuOpt = harness.parse(candidate);
        if (cuOpt.isEmpty()) {
            return ExtractorResult.builder()
                    .unparseable(new CoverageManifest.UnparseableFile(
                            relPath(ctx, candidate), null, "JavaParser could not parse"))
                    .build();
        }
        CompilationUnit cu = cuOpt.get();

        List<ClassOrInterfaceDeclaration> classes = cu.findAll(ClassOrInterfaceDeclaration.class);
        if (classes.isEmpty()) return ExtractorResult.empty();
        ClassOrInterfaceDeclaration impl = classes.get(0);

        // Index helper methods by name → resolve return-typed targets.
        Map<String, MethodDeclaration> helpers = new HashMap<>();
        MethodDeclaration entry = null;
        for (MethodDeclaration m : impl.getMethods()) {
            helpers.put(m.getNameAsString(), m);
            if (m.isAnnotationPresent("Override") && entry == null) {
                entry = m;
            }
        }
        if (entry == null) return ExtractorResult.empty();

        ExtractorResult.Builder rb = ExtractorResult.builder();
        Walker walker = new Walker(ctx, candidate, impl, helpers, rb);
        walker.walkEntry(entry);
        return rb.build();
    }

    private static String relPath(ExtractorContext ctx, Path file) {
        return ctx.repoRoot().relativize(file.toAbsolutePath()).toString().replace('\\', '/');
    }

    /** Per-extraction walker. Holds the recursion stack and source binding. */
    private static final class Walker {
        private final ExtractorContext ctx;
        private final Path file;
        private final ClassOrInterfaceDeclaration impl;
        private final Map<String, MethodDeclaration> helpers;
        private final ExtractorResult.Builder rb;
        private final ScopeInferenceEngine scopeEngine;
        private final GitRefCapture git;
        private final String mapperFqn;

        private FieldRef sourceTypeRef;
        private FieldRef targetTypeRef;
        private String mapperId;

        Walker(ExtractorContext ctx, Path file, ClassOrInterfaceDeclaration impl,
               Map<String, MethodDeclaration> helpers, ExtractorResult.Builder rb) {
            this.ctx = ctx;
            this.file = file;
            this.impl = impl;
            this.helpers = helpers;
            this.rb = rb;
            this.scopeEngine = new ScopeInferenceEngine(ctx.scopeRules());
            this.git = GitRefCapture.forRepo(ctx.repoRoot());
            this.mapperFqn = impl.getFullyQualifiedName().orElse(impl.getNameAsString());
        }

        void walkEntry(MethodDeclaration entry) {
            String returnType = resolveReturn(entry);
            String paramType = entry.getParameters().isEmpty() ? null : resolveParam(entry.getParameter(0));

            this.sourceTypeRef = new FieldRef(paramType, "", ctx.source().schemaFile());
            this.targetTypeRef = new FieldRef(returnType, "", ctx.target().schemaFile());
            this.mapperId = mapperFqn;

            String paramName = entry.getParameters().isEmpty() ? "src"
                    : entry.getParameter(0).getNameAsString();
            walkBody(entry.getBody().orElse(null), "", paramName);
        }

        private void walkBody(BlockStmt body, String pathPrefix, String sourceVar) {
            if (body == null) return;
            String localTargetVar = findFirstNewLocal(body);
            for (Statement st : body.getStatements()) {
                st.findAll(MethodCallExpr.class).forEach(call -> {
                    if (!isSetterOnLocal(call, localTargetVar)) return;
                    handleSetter(call, pathPrefix, sourceVar);
                });
            }
        }

        private boolean isSetterOnLocal(MethodCallExpr call, String localVar) {
            if (localVar == null) return false;
            if (!call.getNameAsString().startsWith("set")) return false;
            return call.getScope()
                    .filter(NameExpr.class::isInstance)
                    .map(s -> ((NameExpr) s).getNameAsString().equals(localVar))
                    .orElse(false);
        }

        private static String findFirstNewLocal(BlockStmt body) {
            for (Statement st : body.getStatements()) {
                List<VariableDeclarationExpr> decls = st.findAll(VariableDeclarationExpr.class);
                for (VariableDeclarationExpr v : decls) {
                    var vars = v.getVariables();
                    if (vars.isEmpty()) continue;
                    var var0 = vars.get(0);
                    if (var0.getInitializer().isPresent()
                            && var0.getInitializer().get() instanceof ObjectCreationExpr) {
                        return var0.getNameAsString();
                    }
                }
            }
            return null;
        }

        private void handleSetter(MethodCallExpr call, String pathPrefix, String sourceVar) {
            String setter = call.getNameAsString();
            String fieldName = setterToField(setter);
            String fullPath = pathPrefix.isEmpty() ? fieldName : pathPrefix + "." + fieldName;
            if (call.getArguments().isEmpty()) return;
            Expression rhs = call.getArgument(0);

            // Recurse into helper(...) calls — they construct sub-targets.
            if (rhs instanceof MethodCallExpr inner) {
                MethodDeclaration helper = helpers.get(inner.getNameAsString());
                if (helper != null && helper.getBody().isPresent()) {
                    String nestedSource = inner.getArguments().isEmpty()
                            ? sourceVar
                            : argToBindingName(inner.getArgument(0), sourceVar);
                    String nestedSourceExpr = inner.getArguments().isEmpty()
                            ? sourceVar
                            : inner.getArgument(0).toString();
                    walkBody(helper.getBody().get(), fullPath, nestedSource);
                    return;
                }
            }

            EdgeKind kind = classify(rhs);
            String sourcePath = extractSourcePath(rhs, sourceVar);
            String staticHelperFqn = extractStaticHelperFqn(rhs);
            int line = call.getBegin().map(p -> p.line).orElse(0);

            FieldRef target = new FieldRef(targetTypeRef.type(), fullPath, ctx.target().schemaFile(),
                    lookupBusinessKey(ctx.target().schemaFile(), fullPath));
            FieldRef source = sourcePath == null ? null : new FieldRef(
                    sourceTypeRef.type(), sourcePath, ctx.source().schemaFile(),
                    lookupBusinessKey(ctx.source().schemaFile(), sourcePath));

            String relFile = relFile();
            String edgeId = EdgeIdGenerator.edgeId(
                    ctx.repoId(), ctx.pairId(), relFile, line, fullPath, sourcePath);

            GitRef gitRef = new GitRef(
                    git.repoUrl(), git.headSha(), relFile, line,
                    null, git.blobShaFor(Path.of(relFile)));

            Edge edge = Edge.builder()
                    .edgeId(edgeId)
                    .mapperId(mapperId)
                    .mapperKind(ID)
                    .kind(kind)
                    .source(source)
                    .target(target)
                    .expression(rhs.toString())
                    .staticHelperFqn(staticHelperFqn)
                    .scope(scopeEngine.infer(Path.of(relFile)))
                    .git(gitRef)
                    .confidence(Confidence.HIGH)
                    .build();
            rb.edge(edge);
        }

        private String relFile() {
            Path abs = file.toAbsolutePath();
            try {
                return ctx.repoRoot().toAbsolutePath().relativize(abs).toString().replace('\\', '/');
            } catch (Exception e) {
                return file.toString();
            }
        }

        private static String setterToField(String setter) {
            String n = setter.substring(3);
            return n.isEmpty() ? n : Character.toLowerCase(n.charAt(0)) + n.substring(1);
        }

        private static EdgeKind classify(Expression rhs) {
            if (rhs instanceof StringLiteralExpr || rhs instanceof IntegerLiteralExpr
                    || rhs instanceof DoubleLiteralExpr || rhs instanceof BooleanLiteralExpr
                    || rhs instanceof NullLiteralExpr || rhs instanceof CharLiteralExpr
                    || rhs instanceof LongLiteralExpr) {
                return EdgeKind.CONSTANT;
            }
            if (rhs instanceof MethodCallExpr call) {
                if (isStaticHelperCall(call)) return EdgeKind.STATIC_CALL;
                if (call.getNameAsString().startsWith("get") && call.getScope().isPresent()) {
                    return EdgeKind.FIELD_COPY;
                }
                return EdgeKind.EXPRESSION;
            }
            if (rhs instanceof FieldAccessExpr) return EdgeKind.FIELD_COPY;
            if (rhs instanceof NameExpr) return EdgeKind.FIELD_COPY;
            if (rhs instanceof ConditionalExpr) return EdgeKind.CONDITIONAL;
            return EdgeKind.EXPRESSION;
        }

        private static boolean isStaticHelperCall(MethodCallExpr call) {
            return call.getScope()
                    .filter(NameExpr.class::isInstance)
                    .map(s -> Character.isUpperCase(((NameExpr) s).getNameAsString().charAt(0)))
                    .orElse(false);
        }

        private String extractSourcePath(Expression rhs, String sourceVar) {
            if (rhs instanceof StringLiteralExpr || rhs instanceof IntegerLiteralExpr
                    || rhs instanceof DoubleLiteralExpr || rhs instanceof BooleanLiteralExpr
                    || rhs instanceof NullLiteralExpr) return null;

            if (rhs instanceof MethodCallExpr call && call.getNameAsString().startsWith("get")) {
                Expression scope = call.getScope().orElse(null);
                String head = scope == null ? null : extractSourcePath(scope, sourceVar);
                String field = getterToField(call.getNameAsString());
                if (head == null || head.isEmpty()) return field;
                return head + "." + field;
            }
            if (rhs instanceof NameExpr name) {
                if (name.getNameAsString().equals(sourceVar)) return "";
                return null;
            }
            if (rhs instanceof FieldAccessExpr fa) {
                String head = extractSourcePath(fa.getScope(), sourceVar);
                String field = fa.getNameAsString();
                if (head == null) return field;
                return head.isEmpty() ? field : head + "." + field;
            }
            return null;
        }

        private static String extractStaticHelperFqn(Expression rhs) {
            if (!(rhs instanceof MethodCallExpr call)) return null;
            if (!isStaticHelperCall(call)) return null;
            try {
                return call.resolve().getQualifiedName();
            } catch (RuntimeException e) {
                return call.getScope().map(Object::toString).orElse(null) + "." + call.getNameAsString();
            }
        }

        private static String getterToField(String getter) {
            if (getter.startsWith("get")) {
                String n = getter.substring(3);
                return n.isEmpty() ? n : Character.toLowerCase(n.charAt(0)) + n.substring(1);
            }
            if (getter.startsWith("is")) {
                String n = getter.substring(2);
                return n.isEmpty() ? n : Character.toLowerCase(n.charAt(0)) + n.substring(1);
            }
            return getter;
        }

        private static String resolveReturn(MethodDeclaration m) {
            try {
                return m.getType().resolve().describe();
            } catch (Exception e) {
                return m.getType().toString();
            }
        }

        private static String resolveParam(com.github.javaparser.ast.body.Parameter p) {
            try {
                return p.getType().resolve().describe();
            } catch (Exception e) {
                return p.getType().toString();
            }
        }

        private static String argToBindingName(Expression arg, String fallback) {
            if (arg instanceof NameExpr n) return n.getNameAsString();
            return fallback;
        }

        private String lookupBusinessKey(String schemaFile, String path) {
            Map<String, String> bk = ctx.businessKeys().get(schemaFile);
            return bk == null ? null : bk.get(path);
        }
    }
}
