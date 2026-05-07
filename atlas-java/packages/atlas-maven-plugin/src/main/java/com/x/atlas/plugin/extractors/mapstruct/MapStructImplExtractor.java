package com.x.atlas.plugin.extractors.mapstruct;

import com.github.javaparser.ast.CompilationUnit;
import com.github.javaparser.ast.body.ClassOrInterfaceDeclaration;
import com.github.javaparser.ast.body.MethodDeclaration;
import com.github.javaparser.ast.body.Parameter;
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
 * Extracts edges from MapStruct-generated {@code *Impl.java} files. Operates
 * on fully-resolved code: every {@code target.setX(rhs)} is unambiguous after
 * annotation processing.
 *
 * <p>Multi-parameter aware: every method parameter is bound to its own source
 * type. {@code mapFrom(MessageContext mc, PaymentInit pi)} produces edges
 * tagged with each RHS's actual originating parameter (mc-rooted vs pi-rooted),
 * enabling multi-source pair lineage downstream.
 *
 * <p>Recursive composition: when {@code target.setX(helper(args))} is seen,
 * the helper's parameter list is re-bound from the call site's arguments and
 * walked with the path prefix advanced to {@code x}.
 */
public final class MapStructImplExtractor implements MappingExtractor {

    private static final String ID = "mapstruct-ast";
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
        ClassOrInterfaceDeclaration impl = classes.get(0);

        Map<String, MethodDeclaration> helpers = new HashMap<>();
        ExtractorResult.Builder rb = ExtractorResult.builder();
        TypeResolver typeResolver = new TypeResolver(cu);
        Walker walker = new Walker(ctx, candidate, impl, helpers, rb, typeResolver);

        for (MethodDeclaration m : impl.getMethods()) {
            helpers.put(m.getNameAsString(), m);
        }
        for (MethodDeclaration m : impl.getMethods()) {
            if (m.isAnnotationPresent("Override")) {
                walker.walkEntry(m);
            }
        }
        return rb.build();
    }

    private static String relPath(ExtractorContext ctx, Path file) {
        return ctx.repoRoot().relativize(file.toAbsolutePath()).toString().replace('\\', '/');
    }

    /** A method-parameter binding: the var name visible in the body and the type it represents. */
    private record ParamBinding(String name, String typeFqn, String schemaFile) {}

    /** Result of resolving the source-side of a setter's RHS expression. */
    private record SourceMatch(ParamBinding binding, String path) {}

    /** Per-extraction walker. */
    private static final class Walker {
        private final ExtractorContext ctx;
        private final Path file;
        private final ClassOrInterfaceDeclaration impl;
        private final Map<String, MethodDeclaration> helpers;
        private final ExtractorResult.Builder rb;
        private final ScopeInferenceEngine scopeEngine;
        private final GitRefCapture git;
        private final String mapperFqn;
        private final TypeResolver typeResolver;

        private String mapperId;
        private FieldRef targetTypeRef;

        Walker(ExtractorContext ctx, Path file, ClassOrInterfaceDeclaration impl,
               Map<String, MethodDeclaration> helpers, ExtractorResult.Builder rb,
               TypeResolver typeResolver) {
            this.ctx = ctx;
            this.file = file;
            this.impl = impl;
            this.helpers = helpers;
            this.rb = rb;
            this.scopeEngine = new ScopeInferenceEngine(ctx.scopeRules());
            this.git = GitRefCapture.forRepo(ctx.repoRoot());
            this.mapperFqn = impl.getFullyQualifiedName().orElse(impl.getNameAsString());
            this.typeResolver = typeResolver;
        }

        void walkEntry(MethodDeclaration entry) {
            String returnType = resolveReturn(entry);
            this.targetTypeRef = new FieldRef(returnType, "", ctx.target().schemaFile());
            this.mapperId = mapperFqn;

            Map<String, ParamBinding> bindings = bindParams(entry);
            walkBody(entry.getBody().orElse(null), "", bindings, entry);
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

        private void walkBody(BlockStmt body, String pathPrefix, Map<String, ParamBinding> bindings) {
            walkBody(body, pathPrefix, bindings, null);
        }

        private void walkBody(BlockStmt body, String pathPrefix, Map<String, ParamBinding> bindings,
                              MethodDeclaration methodForParamFallback) {
            if (body == null) return;
            String targetVar = findFirstNewLocal(body);
            if (targetVar == null && methodForParamFallback != null) {
                String returnType = methodForParamFallback.getType().toString();
                // Try locals of target type (any initialiser).
                for (Statement st : body.getStatements()) {
                    for (VariableDeclarationExpr v : st.findAll(VariableDeclarationExpr.class)) {
                        for (var var : v.getVariables()) {
                            String declared = var.getType().toString();
                            if (declared.equals(returnType) || declared.endsWith("." + returnType)) {
                                targetVar = var.getNameAsString();
                                break;
                            }
                        }
                        if (targetVar != null) break;
                    }
                    if (targetVar != null) break;
                }
                // Fall back to a parameter of target type.
                if (targetVar == null) {
                    for (Parameter p : methodForParamFallback.getParameters()) {
                        String pt = p.getType().toString();
                        if (pt.equals(returnType) || pt.endsWith("." + returnType)) {
                            targetVar = p.getNameAsString();
                            break;
                        }
                    }
                }
            }
            for (Statement st : body.getStatements()) {
                final String tv = targetVar;
                st.findAll(MethodCallExpr.class).forEach(call -> {
                    if (isSetterOnLocal(call, tv)) {
                        handleSetter(call, pathPrefix, bindings);
                    } else if (tv != null && isHelperMutator(call, tv)) {
                        handleEnrichment(call, pathPrefix, tv);
                    }
                });
            }
        }

        private static boolean isHelperMutator(MethodCallExpr call, String targetVar) {
            // Don't double-count: a setter on the target var is handled elsewhere.
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

        private void handleSetter(MethodCallExpr call, String pathPrefix, Map<String, ParamBinding> bindings) {
            String setter = call.getNameAsString();
            String fieldName = setterToField(setter);
            String fullPath = pathPrefix.isEmpty() ? fieldName : pathPrefix + "." + fieldName;
            if (call.getArguments().isEmpty()) return;
            Expression rhs = call.getArgument(0);

            // Recurse into helper(...) calls — they construct sub-targets.
            if (rhs instanceof MethodCallExpr inner) {
                MethodDeclaration helper = helpers.get(inner.getNameAsString());
                if (helper != null && helper.getBody().isPresent()) {
                    Map<String, ParamBinding> nestedBindings = bindHelperParams(helper, inner, bindings);
                    walkBody(helper.getBody().get(), fullPath, nestedBindings);
                    return;
                }
            }

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
                    .confidence(Confidence.HIGH)
                    .build();
            rb.edge(edge);
        }

        /**
         * Build the helper's bindings from the call site's arguments. Each helper
         * parameter aliases either a caller binding (when arg is a NameExpr referring
         * to one) or falls back to the helper parameter's own resolved type.
         */
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
            // Argument is e.g. `src.getField32A()` — leave the helper param to use its own type.
            return null;
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

        /**
         * Resolve the source side of an RHS expression. Walks down the expression
         * looking for the leftmost {@link NameExpr}. If that name matches any
         * parameter binding, returns a SourceMatch with the dotted path traversed
         * across getter calls. Returns null when the RHS doesn't ground in a known
         * parameter (constants, static helpers, foreign references).
         */
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
                // Wrapper call (qualifier instance method, static util, expression):
                // recurse into args to find a source-bound argument. First match wins.
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
                // For ternary, prefer the "then" branch's source.
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
            String fqnScope = typeResolver.resolve(scope);
            return fqnScope + "." + call.getNameAsString();
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
