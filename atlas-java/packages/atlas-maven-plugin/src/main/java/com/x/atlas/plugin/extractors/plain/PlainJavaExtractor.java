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
import com.x.atlas.plugin.ast.TypeResolver;
import com.x.atlas.plugin.git.GitRefCapture;
import java.nio.file.Path;
import java.util.*;

/**
 * Extracts edges from non-MapStruct Java mappers.
 *
 * <p>Multi-parameter aware: every method parameter is bound to its own source
 * type. {@code LocalDomain map(MessageContext mc, PaymentInit pi)} produces
 * edges tagged with each setter RHS's actual originating parameter.
 *
 * <p>Patterns covered:
 * <ul>
 *   <li>Setter writes on a fresh {@code new T()} target var (cluster).</li>
 *   <li>Builder chains terminating in {@code .build()} of target type.</li>
 *   <li>Constructor mappings (record / @AllArgsConstructor / explicit body).</li>
 *   <li>Direct field assignment on public fields.</li>
 *   <li>Cross-method follow into helpers in the same class.</li>
 * </ul>
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
        JavaParserHarness harness = JavaParserHarness.forContext(ctx.sourceRoots(), ctx.classpath());
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
        if (cls.isAnnotationPresent("Mapper")) return ExtractorResult.empty();

        Map<String, MethodDeclaration> helpers = new HashMap<>();
        for (MethodDeclaration m : cls.getMethods()) helpers.put(m.getNameAsString(), m);

        ExtractorResult.Builder rb = ExtractorResult.builder();
        TypeResolver typeResolver = new TypeResolver(cu);
        Walker walker = new Walker(ctx, candidate, cls, helpers, rb, typeResolver);

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

    private record ParamBinding(String name, String typeFqn, String schemaFile) {}

    private record SourceMatch(ParamBinding binding, String path) {}

    private static final class Walker {
        private final ExtractorContext ctx;
        private final Path file;
        private final ClassOrInterfaceDeclaration cls;
        private final Map<String, MethodDeclaration> helpers;
        private final ExtractorResult.Builder rb;
        private final ScopeInferenceEngine scopeEngine;
        private final GitRefCapture git;
        private final String classFqn;
        private final TypeResolver typeResolver;

        private String mapperId;
        private FieldRef targetTypeRef;

        Walker(ExtractorContext ctx, Path file, ClassOrInterfaceDeclaration cls,
               Map<String, MethodDeclaration> helpers, ExtractorResult.Builder rb,
               TypeResolver typeResolver) {
            this.ctx = ctx;
            this.file = file;
            this.cls = cls;
            this.helpers = helpers;
            this.rb = rb;
            this.scopeEngine = new ScopeInferenceEngine(ctx.scopeRules());
            this.git = GitRefCapture.forRepo(ctx.repoRoot());
            this.classFqn = cls.getFullyQualifiedName().orElse(cls.getNameAsString());
            this.typeResolver = typeResolver;
        }

        void tryEntry(MethodDeclaration method) {
            if (method.getBody().isEmpty()) return;
            BlockStmt body = method.getBody().get();
            String returnType = method.getType().toString();
            if ("void".equals(returnType)) return;
            if (method.getParameters().isEmpty()) return;

            String targetVar = findTargetVar(body, method, returnType);
            if (targetVar == null) return;
            if (!hasSetterOnVar(body, targetVar)) return;

            this.mapperId = classFqn + "#" + method.getNameAsString();
            String resolvedTarget = resolveReturn(method);
            this.targetTypeRef = new FieldRef(resolvedTarget, "", ctx.target().schemaFile());

            Map<String, ParamBinding> bindings = bindParams(method);
            walkBody(body, "", bindings, targetVar);
        }

        private static boolean hasSetterOnVar(BlockStmt body, String targetVar) {
            for (Statement st : body.getStatements()) {
                for (MethodCallExpr call : st.findAll(MethodCallExpr.class)) {
                    if (!call.getNameAsString().startsWith("set")) continue;
                    if (call.getScope().filter(NameExpr.class::isInstance)
                            .map(s -> ((NameExpr) s).getNameAsString().equals(targetVar))
                            .orElse(false)) {
                        return true;
                    }
                }
            }
            return false;
        }

        private Map<String, ParamBinding> bindParams(MethodDeclaration method) {
            Map<String, ParamBinding> out = new LinkedHashMap<>();
            for (Parameter p : method.getParameters()) {
                String type = resolveParam(p);
                out.put(p.getNameAsString(),
                        new ParamBinding(p.getNameAsString(), type, ctx.source().schemaFile()));
            }
            return out;
        }

        private void walkBody(BlockStmt body, String pathPrefix,
                              Map<String, ParamBinding> bindings, String targetVar) {
            for (Statement st : body.getStatements()) {
                st.findAll(MethodCallExpr.class).forEach(call -> {
                    if (isSetterOnLocal(call, targetVar)) {
                        handleSetter(call, pathPrefix, bindings);
                    } else if (targetVar != null && isHelperMutator(call, targetVar)) {
                        handleEnrichment(call, pathPrefix, targetVar);
                    }
                });
            }
        }

        private static boolean isHelperMutator(MethodCallExpr call, String targetVar) {
            if (call.getNameAsString().startsWith("set")
                    && call.getScope().filter(NameExpr.class::isInstance)
                            .map(s -> ((NameExpr) s).getNameAsString().equals(targetVar))
                            .orElse(false)) {
                return false;
            }
            for (Expression arg : call.getArguments()) {
                if (isGetterChainRootedAt(arg, targetVar)) return true;
            }
            return false;
        }

        private static boolean isGetterChainRootedAt(Expression e, String targetVar) {
            while (e instanceof MethodCallExpr m && m.getNameAsString().startsWith("get")) {
                e = m.getScope().orElse(null);
                if (e == null) return false;
            }
            return e instanceof NameExpr n && n.getNameAsString().equals(targetVar);
        }

        private static String pathFromGetterChain(Expression e) {
            StringBuilder sb = new StringBuilder();
            while (e instanceof MethodCallExpr m && m.getNameAsString().startsWith("get")) {
                if (sb.length() > 0) sb.insert(0, ".");
                sb.insert(0, getterToField(m.getNameAsString()));
                e = m.getScope().orElse(null);
            }
            return sb.toString();
        }

        private void handleEnrichment(MethodCallExpr call, String pathPrefix, String targetVar) {
            String helperFqn = extractStaticHelperFqn(call);
            if (helperFqn == null) {
                helperFqn = call.getScope().map(Object::toString).orElse("?") + "." + call.getNameAsString();
            }
            int line = call.getBegin().map(p -> p.line).orElse(0);
            String relFile = relFile();
            for (Expression arg : call.getArguments()) {
                if (!isGetterChainRootedAt(arg, targetVar)) continue;
                String pathFromArg = pathFromGetterChain(arg);
                if (pathFromArg.isEmpty()) continue;
                String fullPath = pathPrefix.isEmpty() ? pathFromArg : pathPrefix + "." + pathFromArg;
                FieldRef target = new FieldRef(targetTypeRef.type(), fullPath, ctx.target().schemaFile(),
                        lookupBusinessKey(ctx.target().schemaFile(), fullPath));
                String edgeId = EdgeIdGenerator.edgeId(
                        ctx.repoId(), ctx.pairId(), relFile, line, fullPath, "enrichment:" + helperFqn);
                GitRef gitRef = new GitRef(
                        git.repoUrl(), git.headSha(), relFile, line,
                        null, git.blobShaFor(Path.of(relFile)));
                Edge edge = Edge.builder()
                        .edgeId(edgeId)
                        .mapperId(mapperId)
                        .mapperKind(ID)
                        .kind(EdgeKind.ENRICHMENT)
                        .source(null)
                        .target(target)
                        .expression(call.toString())
                        .staticHelperFqn(helperFqn)
                        .scope(scopeEngine.infer(Path.of(relFile)))
                        .git(gitRef)
                        .confidence(Confidence.LOW)
                        .build();
                rb.edge(edge);
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

        /**
         * Resolve the target var:
         *   1. First local declared with the target type (any initialiser).
         *   2. Else, first method parameter typed as the target.
         */
        private static String findTargetVar(BlockStmt body, MethodDeclaration method, String returnTypeName) {
            for (Statement st : body.getStatements()) {
                for (VariableDeclarationExpr v : st.findAll(VariableDeclarationExpr.class)) {
                    for (VariableDeclarator var : v.getVariables()) {
                        String declared = var.getType().toString();
                        if (declared.equals(returnTypeName) || declared.endsWith("." + returnTypeName)) {
                            return var.getNameAsString();
                        }
                    }
                }
            }
            for (Parameter p : method.getParameters()) {
                String pt = p.getType().toString();
                if (pt.equals(returnTypeName) || pt.endsWith("." + returnTypeName)) {
                    return p.getNameAsString();
                }
            }
            return null;
        }

        private void handleSetter(MethodCallExpr call, String pathPrefix, Map<String, ParamBinding> bindings) {
            String fieldName = setterToField(call.getNameAsString());
            String fullPath = pathPrefix.isEmpty() ? fieldName : pathPrefix + "." + fieldName;
            if (call.getArguments().isEmpty()) return;
            Expression rhs = call.getArgument(0);

            // Compose nested target instances built earlier in the same block.
            if (rhs instanceof NameExpr nameRhs) {
                BlockStmt enclosing = call.findAncestor(BlockStmt.class).orElse(null);
                if (enclosing != null) {
                    String composed = tryComposeNestedTarget(enclosing, nameRhs.getNameAsString(), fullPath, bindings);
                    if (composed != null) return;
                }
            }

            // Helper following: target.setX(helper(args)) -> walk helper with prefix=x.
            if (rhs instanceof MethodCallExpr inner) {
                MethodDeclaration helper = helpers.get(inner.getNameAsString());
                if (helper != null && helper.getBody().isPresent()) {
                    Map<String, ParamBinding> nestedBindings = bindHelperParams(helper, inner, bindings);
                    String localTarget = findFirstNewLocal(helper.getBody().get(), helper.getType().toString());
                    if (localTarget != null) {
                        walkBody(helper.getBody().get(), fullPath, nestedBindings, localTarget);
                        return;
                    }
                }
            }

            emit(call, rhs, fullPath, bindings);
        }

        private String tryComposeNestedTarget(
                BlockStmt block, String varName, String fullPath, Map<String, ParamBinding> bindings
        ) {
            for (Statement st : block.getStatements()) {
                List<VariableDeclarationExpr> decls = st.findAll(VariableDeclarationExpr.class);
                for (VariableDeclarationExpr v : decls) {
                    for (VariableDeclarator var : v.getVariables()) {
                        if (var.getNameAsString().equals(varName)
                                && var.getInitializer().isPresent()
                                && var.getInitializer().get() instanceof ObjectCreationExpr) {
                            walkBody(block, fullPath, bindings, varName);
                            return fullPath;
                        }
                    }
                }
            }
            return null;
        }

        private Map<String, ParamBinding> bindHelperParams(
                MethodDeclaration helper, MethodCallExpr call, Map<String, ParamBinding> callerBindings
        ) {
            Map<String, ParamBinding> out = new LinkedHashMap<>();
            List<Parameter> helperParams = helper.getParameters();
            List<Expression> args = call.getArguments();
            for (int i = 0; i < helperParams.size(); i++) {
                String pname = helperParams.get(i).getNameAsString();
                ParamBinding alias = i < args.size() ? resolveArgToBinding(args.get(i), callerBindings) : null;
                if (alias != null) {
                    out.put(pname, new ParamBinding(pname, alias.typeFqn(), alias.schemaFile()));
                } else {
                    String type = resolveParam(helperParams.get(i));
                    out.put(pname, new ParamBinding(pname, type, ctx.source().schemaFile()));
                }
            }
            return out;
        }

        private ParamBinding resolveArgToBinding(Expression arg, Map<String, ParamBinding> bindings) {
            if (arg instanceof NameExpr n) return bindings.get(n.getNameAsString());
            return null;
        }

        private void emit(MethodCallExpr call, Expression rhs, String fullPath, Map<String, ParamBinding> bindings) {
            EdgeKind kind = classify(rhs);
            SourceMatch match = extractSource(rhs, bindings);
            String staticHelperFqn = extractStaticHelperFqn(rhs);
            int line = call.getBegin().map(p -> p.line).orElse(0);

            String relFile = relFile();
            FieldRef target = new FieldRef(targetTypeRef.type(), fullPath, ctx.target().schemaFile(),
                    lookupBusinessKey(ctx.target().schemaFile(), fullPath));
            FieldRef source = match == null ? null : new FieldRef(
                    match.binding().typeFqn(), match.path(), match.binding().schemaFile(),
                    lookupBusinessKey(match.binding().schemaFile(), match.path()));

            String edgeId = EdgeIdGenerator.edgeId(
                    ctx.repoId(), ctx.pairId(), relFile, line, fullPath,
                    match == null ? null : match.path());

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
                if (isStaticHelperCall(call)) return EdgeKind.STATIC_CALL;
                if (call.getNameAsString().startsWith("get") && call.getScope().isPresent()) return EdgeKind.FIELD_COPY;
                return EdgeKind.EXPRESSION;
            }
            if (rhs instanceof FieldAccessExpr || rhs instanceof NameExpr) return EdgeKind.FIELD_COPY;
            if (rhs instanceof ConditionalExpr) return EdgeKind.CONDITIONAL;
            return EdgeKind.EXPRESSION;
        }

        private static boolean isStaticHelperCall(MethodCallExpr call) {
            return call.getScope()
                    .filter(NameExpr.class::isInstance)
                    .map(s -> Character.isUpperCase(((NameExpr) s).getNameAsString().charAt(0)))
                    .orElse(false);
        }

        private SourceMatch extractSource(Expression rhs, Map<String, ParamBinding> bindings) {
            if (rhs instanceof StringLiteralExpr || rhs instanceof IntegerLiteralExpr
                    || rhs instanceof DoubleLiteralExpr || rhs instanceof BooleanLiteralExpr
                    || rhs instanceof NullLiteralExpr) return null;
            if (rhs instanceof MethodCallExpr call) {
                if (call.getNameAsString().startsWith("get") && call.getScope().isPresent()) {
                    SourceMatch headMatch = extractSource(call.getScope().get(), bindings);
                    if (headMatch != null) {
                        String field = getterToField(call.getNameAsString());
                        String path = headMatch.path().isEmpty() ? field : headMatch.path() + "." + field;
                        return new SourceMatch(headMatch.binding(), path);
                    }
                }
                // Wrapper call (qualifier, util, expression): recurse into args.
                for (Expression arg : call.getArguments()) {
                    SourceMatch argMatch = extractSource(arg, bindings);
                    if (argMatch != null) return argMatch;
                }
                return null;
            }
            if (rhs instanceof NameExpr name) {
                ParamBinding b = bindings.get(name.getNameAsString());
                if (b == null) return null;
                return new SourceMatch(b, "");
            }
            if (rhs instanceof FieldAccessExpr fa) {
                SourceMatch headMatch = extractSource(fa.getScope(), bindings);
                if (headMatch == null) return null;
                String field = fa.getNameAsString();
                String path = headMatch.path().isEmpty() ? field : headMatch.path() + "." + field;
                return new SourceMatch(headMatch.binding(), path);
            }
            if (rhs instanceof ConditionalExpr cond) {
                SourceMatch thenMatch = extractSource(cond.getThenExpr(), bindings);
                if (thenMatch != null) return thenMatch;
                return extractSource(cond.getElseExpr(), bindings);
            }
            if (rhs instanceof EnclosedExpr enc) {
                return extractSource(enc.getInner(), bindings);
            }
            if (rhs instanceof CastExpr cast) {
                return extractSource(cast.getExpression(), bindings);
            }
            return null;
        }

        private String extractStaticHelperFqn(Expression rhs) {
            if (!(rhs instanceof MethodCallExpr call)) return null;
            if (!isStaticHelperCall(call)) return null;
            String scope = call.getScope().map(Object::toString).orElse(null);
            if (scope == null) return null;
            return typeResolver.resolve(scope) + "." + call.getNameAsString();
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

        private String resolveReturn(MethodDeclaration m) {
            return typeResolver.resolve(m.getType().toString());
        }

        private String resolveParam(Parameter p) {
            return typeResolver.resolve(p.getType().toString());
        }

        private String lookupBusinessKey(String schemaFile, String path) {
            Map<String, String> bk = ctx.businessKeys().get(schemaFile);
            return bk == null ? null : bk.get(path);
        }
    }
}
