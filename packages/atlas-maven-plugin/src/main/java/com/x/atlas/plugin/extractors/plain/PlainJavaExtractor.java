package com.x.atlas.plugin.extractors.plain;

import com.github.javaparser.ast.CompilationUnit;
import com.github.javaparser.ast.body.ClassOrInterfaceDeclaration;
import com.github.javaparser.ast.body.MethodDeclaration;
import com.github.javaparser.ast.body.Parameter;
import com.github.javaparser.ast.body.VariableDeclarator;
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
 * Extracts edges from non-MapStruct Java mappers (plain {@code new T(); set; set;}
 * patterns, builder chains, constructor mappings).
 *
 * <p>Algorithm per file:
 * <ol>
 *   <li>Find candidate methods: {@code T method(S src)} where S != T.</li>
 *   <li>Within each method, locate the first {@code new T()} or {@code T.builder()}
 *       local variable — this is the target instance.</li>
 *   <li>Walk every {@code target.setX(rhs)} on that variable; emit edges.</li>
 *   <li>Builder calls {@code .x(rhs)} on the chain are treated equivalently.</li>
 *   <li>Helper-method follow: when {@code target.setX(helper(args))} appears and
 *       {@code helper} lives in the same class, recurse with {@code x} as the
 *       path prefix.</li>
 * </ol>
 *
 * <p>Skips MapStruct-generated impls (those are handled by the mapstruct extractor).
 */
public final class PlainJavaExtractor implements MappingExtractor {

    private static final String ID = "plain-java";
    private static final String VERSION = "0.1.0";

    @Override public String id() { return ID; }
    @Override public String version() { return VERSION; }

    @Override
    public boolean supports(ExtractorContext ctx, Path candidate) {
        String s = candidate.toString().replace('\\', '/');
        if (!s.endsWith(".java")) return false;
        if (s.contains("/target/generated-sources/")) return false;
        return true;
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
        ClassOrInterfaceDeclaration cls = classes.get(0);
        if (cls.isAnnotationPresent("Mapper")) return ExtractorResult.empty(); // owned by mapstruct extractor

        Map<String, MethodDeclaration> helpers = new HashMap<>();
        for (MethodDeclaration m : cls.getMethods()) helpers.put(m.getNameAsString(), m);

        ExtractorResult.Builder rb = ExtractorResult.builder();
        Walker walker = new Walker(ctx, candidate, cls, helpers, rb);

        for (MethodDeclaration m : cls.getMethods()) {
            if (m.isAnnotationPresent("AtlasIgnore")) {
                rb.ignored(cls.getFullyQualifiedName().orElse(cls.getNameAsString())
                        + "#" + m.getNameAsString());
                continue;
            }
            walker.tryEntry(m);
        }
        return rb.build();
    }

    private static String relPath(ExtractorContext ctx, Path file) {
        return ctx.repoRoot().relativize(file.toAbsolutePath()).toString().replace('\\', '/');
    }

    private static final class Walker {
        private final ExtractorContext ctx;
        private final Path file;
        private final ClassOrInterfaceDeclaration cls;
        private final Map<String, MethodDeclaration> helpers;
        private final ExtractorResult.Builder rb;
        private final ScopeInferenceEngine scopeEngine;
        private final GitRefCapture git;
        private final String classFqn;

        private String mapperId;
        private FieldRef sourceTypeRef;
        private FieldRef targetTypeRef;

        Walker(ExtractorContext ctx, Path file, ClassOrInterfaceDeclaration cls,
               Map<String, MethodDeclaration> helpers, ExtractorResult.Builder rb) {
            this.ctx = ctx;
            this.file = file;
            this.cls = cls;
            this.helpers = helpers;
            this.rb = rb;
            this.scopeEngine = new ScopeInferenceEngine(ctx.scopeRules());
            this.git = GitRefCapture.forRepo(ctx.repoRoot());
            this.classFqn = cls.getFullyQualifiedName().orElse(cls.getNameAsString());
        }

        void tryEntry(MethodDeclaration method) {
            if (!method.getBody().isPresent()) return;
            BlockStmt body = method.getBody().get();
            String returnType = method.getType().toString();
            if ("void".equals(returnType)) return;
            if (method.getParameters().isEmpty()) return;
            String paramType = method.getParameter(0).getType().toString();
            if (paramType.equals(returnType)) return;
            // Heuristic: must contain at least one `target.setX(...)` on a freshly-created target
            String localVar = findFirstNewLocal(body, returnType);
            if (localVar == null) return;

            this.mapperId = classFqn + "#" + method.getNameAsString();
            String resolvedSource = resolveTypeFqn(method.getParameter(0).getType().toString(), method.getParameter(0));
            String resolvedTarget = resolveTypeFqn(method.getType().toString(), method);
            this.sourceTypeRef = new FieldRef(resolvedSource, "", ctx.source().schemaFile());
            this.targetTypeRef = new FieldRef(resolvedTarget, "", ctx.target().schemaFile());

            Parameter src = method.getParameter(0);
            walkBody(body, "", src.getNameAsString(), localVar);
        }

        private void walkBody(BlockStmt body, String pathPrefix, String sourceVar, String targetVar) {
            for (Statement st : body.getStatements()) {
                st.findAll(MethodCallExpr.class).forEach(call -> {
                    if (isSetterOnLocal(call, targetVar)) {
                        handleSetter(call, pathPrefix, sourceVar);
                    }
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

        private static String findFirstNewLocal(BlockStmt body, String returnTypeName) {
            for (Statement st : body.getStatements()) {
                List<VariableDeclarationExpr> decls = st.findAll(VariableDeclarationExpr.class);
                for (VariableDeclarationExpr v : decls) {
                    for (VariableDeclarator var : v.getVariables()) {
                        if (var.getInitializer().isPresent()
                                && var.getInitializer().get() instanceof ObjectCreationExpr oce) {
                            String tName = oce.getType().getNameAsString();
                            if (returnTypeName.endsWith(tName) || tName.equals(returnTypeName)) {
                                return var.getNameAsString();
                            }
                        }
                    }
                }
            }
            return null;
        }

        private void handleSetter(MethodCallExpr call, String pathPrefix, String sourceVar) {
            String fieldName = setterToField(call.getNameAsString());
            String fullPath = pathPrefix.isEmpty() ? fieldName : pathPrefix + "." + fieldName;
            if (call.getArguments().isEmpty()) return;
            Expression rhs = call.getArgument(0);

            if (rhs instanceof NameExpr nameRhs) {
                BlockStmt enclosing = call.findAncestor(BlockStmt.class).orElse(null);
                if (enclosing != null) {
                    String varName = nameRhs.getNameAsString();
                    String composedPath = tryComposeNestedTarget(enclosing, varName, fullPath, sourceVar);
                    if (composedPath != null) return; // edges emitted via recursion
                }
            }

            if (rhs instanceof MethodCallExpr inner) {
                MethodDeclaration helper = helpers.get(inner.getNameAsString());
                if (helper != null && helper.getBody().isPresent()) {
                    String nestedSource = inner.getArguments().isEmpty()
                            ? sourceVar
                            : argToBindingName(inner.getArgument(0), sourceVar);
                    String localTarget = findFirstNewLocal(helper.getBody().get(), helper.getType().toString());
                    if (localTarget != null) {
                        walkBody(helper.getBody().get(), fullPath, nestedSource, localTarget);
                        return;
                    }
                }
            }

            emit(call, rhs, fullPath, sourceVar);
        }

        /** When RHS is a name referring to a locally-built sub-target, walk that builder's setters. */
        private String tryComposeNestedTarget(BlockStmt block, String varName, String fullPath, String sourceVar) {
            for (Statement st : block.getStatements()) {
                List<VariableDeclarationExpr> decls = st.findAll(VariableDeclarationExpr.class);
                for (VariableDeclarationExpr v : decls) {
                    for (VariableDeclarator var : v.getVariables()) {
                        if (var.getNameAsString().equals(varName)
                                && var.getInitializer().isPresent()
                                && var.getInitializer().get() instanceof ObjectCreationExpr) {
                            walkBody(block, fullPath, sourceVar, varName);
                            return fullPath;
                        }
                    }
                }
            }
            return null;
        }

        private void emit(MethodCallExpr call, Expression rhs, String fullPath, String sourceVar) {
            EdgeKind kind = classify(rhs);
            String sourcePath = extractSourcePath(rhs, sourceVar);
            String staticHelperFqn = extractStaticHelperFqn(rhs);
            int line = call.getBegin().map(p -> p.line).orElse(0);

            String relFile = relFile();
            FieldRef target = new FieldRef(targetTypeRef.type(), fullPath, ctx.target().schemaFile(),
                    lookupBusinessKey(ctx.target().schemaFile(), fullPath));
            FieldRef source = sourcePath == null ? null : new FieldRef(
                    sourceTypeRef.type(), sourcePath, ctx.source().schemaFile(),
                    lookupBusinessKey(ctx.source().schemaFile(), sourcePath));

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
                    .confidence(kind == EdgeKind.CONSTANT || kind == EdgeKind.FIELD_COPY
                            ? Confidence.HIGH : Confidence.MEDIUM)
                    .build();
            rb.edge(edge);
        }

        private String relFile() {
            try {
                return ctx.repoRoot().toAbsolutePath().relativize(file.toAbsolutePath()).toString().replace('\\', '/');
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
                    || rhs instanceof LongLiteralExpr) return EdgeKind.CONSTANT;
            if (rhs instanceof MethodCallExpr call) {
                if (call.getScope().filter(NameExpr.class::isInstance)
                        .map(s -> Character.isUpperCase(((NameExpr) s).getNameAsString().charAt(0)))
                        .orElse(false)) return EdgeKind.STATIC_CALL;
                if (call.getNameAsString().startsWith("get") && call.getScope().isPresent()) return EdgeKind.FIELD_COPY;
                return EdgeKind.EXPRESSION;
            }
            if (rhs instanceof FieldAccessExpr || rhs instanceof NameExpr) return EdgeKind.FIELD_COPY;
            if (rhs instanceof ConditionalExpr) return EdgeKind.CONDITIONAL;
            return EdgeKind.EXPRESSION;
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
            if (call.getScope().filter(NameExpr.class::isInstance)
                    .map(s -> Character.isUpperCase(((NameExpr) s).getNameAsString().charAt(0)))
                    .orElse(false)) {
                try {
                    return call.resolve().getQualifiedName();
                } catch (Exception e) {
                    return call.getScope().map(Object::toString).orElse(null) + "." + call.getNameAsString();
                }
            }
            return null;
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

        private static String resolveTypeFqn(String fallback, MethodDeclaration m) {
            try {
                return m.getType().resolve().describe();
            } catch (Exception e) {
                return fallback;
            }
        }

        private static String resolveTypeFqn(String fallback, Parameter p) {
            try {
                return p.getType().resolve().describe();
            } catch (Exception e) {
                return fallback;
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
