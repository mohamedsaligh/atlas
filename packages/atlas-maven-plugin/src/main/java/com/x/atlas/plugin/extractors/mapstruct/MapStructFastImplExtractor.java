package com.x.atlas.plugin.extractors.mapstruct;

import com.x.atlas.core.io.EdgeIdGenerator;
import com.x.atlas.core.model.*;
import com.x.atlas.core.scope.ScopeInferenceEngine;
import com.x.atlas.core.spi.ExtractorContext;
import com.x.atlas.core.spi.ExtractorResult;
import com.x.atlas.core.spi.MappingExtractor;
import com.x.atlas.plugin.git.GitRefCapture;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.*;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * Fast text/regex-based extractor for MapStruct-generated {@code *Impl.java}
 * files. Generated impls have a 100% predictable shape, so we bypass JavaParser
 * entirely (which can hang for minutes on very large impls with deep generics).
 *
 * <p>Coverage parity with the AST-based {@link MapStructImplExtractor} for the
 * structural patterns:
 * <ul>
 *   <li>{@code target.setX(src.getY()...)} field-copy chains.</li>
 *   <li>{@code target.setX("CONST")} constants.</li>
 *   <li>{@code target.setX(Qualifier.method(src.getY()))} wrapper-arg recursion
 *       — extracts the inner source path.</li>
 *   <li>{@code target.setX(helperMethod(args))} where {@code helperMethod} is
 *       defined in the same class — recurses with prefix {@code x}.</li>
 *   <li>{@code Helper.update(target.getZ())} → emits {@code kind=enrichment}
 *       edge on {@code z}.</li>
 * </ul>
 *
 * <p>What's not covered (graceful degradation):
 * <ul>
 *   <li>Lambdas with embedded setter chains.</li>
 *   <li>Calls that span unbalanced quotes inside string literals (corner case).</li>
 * </ul>
 */
public final class MapStructFastImplExtractor implements MappingExtractor {

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
            String head = readHead(candidate, 4096);
            return head.contains(GENERATED_MARKER);
        } catch (Exception e) {
            return false;
        }
    }

    private static String readHead(Path file, int limit) throws java.io.IOException {
        byte[] all = Files.readAllBytes(file);
        int n = Math.min(all.length, limit);
        return new String(all, 0, n, java.nio.charset.StandardCharsets.UTF_8);
    }

    @Override
    public ExtractorResult extract(ExtractorContext ctx, Path candidate) {
        String text;
        try {
            text = Files.readString(candidate);
        } catch (java.io.IOException e) {
            return ExtractorResult.builder()
                    .unparseable(new CoverageManifest.UnparseableFile(
                            relPath(ctx, candidate), null, "read failed: " + e.getMessage()))
                    .build();
        }
        String stripped = stripComments(text);
        ExtractorResult.Builder rb = ExtractorResult.builder();
        new Walker(ctx, candidate, stripped, text, rb).walk();
        return rb.build();
    }

    private static String relPath(ExtractorContext ctx, Path file) {
        return ctx.repoRoot().relativize(file.toAbsolutePath()).toString().replace('\\', '/');
    }

    /* ────────────────────────────── parsing ─────────────────────────────── */

    private static final Pattern PACKAGE_RE =
            Pattern.compile("(?m)^\\s*package\\s+([\\w.]+)\\s*;");
    private static final Pattern IMPORT_RE =
            Pattern.compile("(?m)^\\s*import\\s+(?:static\\s+)?([\\w.*]+)\\s*;");
    private static final Pattern CLASS_DECL_RE =
            Pattern.compile("(?m)\\b(?:public|abstract|final|protected|private|static|\\s)*\\s*class\\s+(\\w+)\\b");
    private static final Pattern METHOD_DECL_RE = Pattern.compile(
            "(?ms)" +
            "((?:@\\w+(?:\\([^)]*\\))?\\s+)*)" +                           // 1: annotation block
            "(?:(?:public|protected|private|abstract|static|final|default)\\s+)+" +   // 1+ modifiers
            "([\\w.<>\\[\\],?]+?)\\s+" +                                    // 2: return type (no whitespace inside)
            "(\\w+)\\s*" +                                                  // 3: method name
            "\\(([^)]*)\\)\\s*\\{"                                          // 4: params, then '{'
    );
    private static final Pattern PARAM_RE = Pattern.compile(
            "([\\w.<>\\[\\],\\s]+?)\\s+(\\w+)\\s*(?:,|$)"
    );
    private static final Pattern LOCAL_NEW_RE = Pattern.compile(
            "([\\w.]+)\\s+(\\w+)\\s*=\\s*new\\s+([\\w.]+)\\s*\\("
    );
    private static final Pattern OVERRIDE_RE = Pattern.compile("@Override\\b");

    private static String stripComments(String s) {
        // Remove block comments first.
        StringBuilder out = new StringBuilder(s.length());
        int i = 0;
        while (i < s.length()) {
            if (i + 1 < s.length() && s.charAt(i) == '/' && s.charAt(i + 1) == '*') {
                int end = s.indexOf("*/", i + 2);
                if (end < 0) break;
                // Preserve newlines so line numbers stay accurate.
                for (int j = i; j < end + 2; j++) {
                    char c = s.charAt(j);
                    out.append(c == '\n' ? '\n' : ' ');
                }
                i = end + 2;
            } else if (i + 1 < s.length() && s.charAt(i) == '/' && s.charAt(i + 1) == '/') {
                int end = s.indexOf('\n', i);
                if (end < 0) end = s.length();
                for (int j = i; j < end; j++) out.append(' ');
                i = end;
            } else {
                out.append(s.charAt(i));
                i++;
            }
        }
        return out.toString();
    }

    /* ─────────────────────────── traversal core ─────────────────────────── */

    private static final class ParamBinding {
        final String name;
        final String typeFqn;
        final String schemaFile;
        ParamBinding(String name, String typeFqn, String schemaFile) {
            this.name = name; this.typeFqn = typeFqn; this.schemaFile = schemaFile;
        }
    }

    private static final class SourceMatch {
        final ParamBinding binding;
        final String path;
        SourceMatch(ParamBinding b, String path) { this.binding = b; this.path = path; }
    }

    private static final class MethodBlock {
        final String name;
        final String returnType;
        final String params;
        final boolean hasOverride;
        final int bodyStart;
        final int bodyEnd;
        final String body;
        MethodBlock(String name, String returnType, String params, boolean hasOverride,
                    int bodyStart, int bodyEnd, String body) {
            this.name = name; this.returnType = returnType; this.params = params;
            this.hasOverride = hasOverride;
            this.bodyStart = bodyStart; this.bodyEnd = bodyEnd; this.body = body;
        }
    }

    private final class Walker {
        final ExtractorContext ctx;
        final Path file;
        final String stripped;            // comment-stripped text
        final String original;            // original text (for line numbering only)
        final ExtractorResult.Builder rb;
        final ScopeInferenceEngine scopeEngine;
        final GitRefCapture git;
        final Map<String, String> imports = new HashMap<>();
        String pkg = "";
        final String relFile;

        Walker(ExtractorContext ctx, Path file, String stripped, String original,
               ExtractorResult.Builder rb) {
            this.ctx = ctx;
            this.file = file;
            this.stripped = stripped;
            this.original = original;
            this.rb = rb;
            this.scopeEngine = new ScopeInferenceEngine(ctx.scopeRules());
            this.git = GitRefCapture.forRepo(ctx.repoRoot());
            this.relFile = relFile();
        }

        void walk() {
            Matcher pm = PACKAGE_RE.matcher(stripped);
            if (pm.find()) pkg = pm.group(1);

            Matcher im = IMPORT_RE.matcher(stripped);
            while (im.find()) {
                String fqn = im.group(1);
                if (fqn.endsWith(".*")) continue;
                int dot = fqn.lastIndexOf('.');
                String simple = dot >= 0 ? fqn.substring(dot + 1) : fqn;
                imports.putIfAbsent(simple, fqn);
            }

            Matcher cm = CLASS_DECL_RE.matcher(stripped);
            while (cm.find()) {
                int classStart = cm.start();
                int braceIdx = stripped.indexOf('{', cm.end());
                if (braceIdx < 0) continue;
                int classEnd = matchingBrace(stripped, braceIdx);
                if (classEnd < 0) continue;
                String className = cm.group(1);
                String classBody = stripped.substring(braceIdx + 1, classEnd);
                String classFqn = pkg.isEmpty() ? className : pkg + "." + className;
                processClass(classFqn, classBody);
                // Don't reset matcher; CLASS_DECL_RE may still match inner classes.
            }
        }

        private void processClass(String classFqn, String classBody) {
            Map<String, MethodBlock> methods = findMethods(classBody);
            for (MethodBlock m : methods.values()) {
                if (!m.hasOverride) continue;
                walkMethod(m, methods, "", classFqn);
            }
        }

        private Map<String, MethodBlock> findMethods(String classBody) {
            Map<String, MethodBlock> out = new LinkedHashMap<>();
            Matcher mm = METHOD_DECL_RE.matcher(classBody);
            while (mm.find()) {
                String annotations = mm.group(1) == null ? "" : mm.group(1);
                String returnType = mm.group(2).trim();
                String methodName = mm.group(3);
                String params = mm.group(4) == null ? "" : mm.group(4);
                int bodyStart = mm.end();
                int bodyEnd = matchingBrace(classBody, bodyStart - 1);
                if (bodyEnd < 0) continue;
                String body = classBody.substring(bodyStart, bodyEnd);
                boolean hasOverride = OVERRIDE_RE.matcher(annotations).find();
                out.putIfAbsent(methodName, new MethodBlock(
                        methodName, returnType, params, hasOverride,
                        bodyStart, bodyEnd, body
                ));
            }
            return out;
        }

        private void walkMethod(MethodBlock m, Map<String, MethodBlock> helpers,
                                String pathPrefix, String classFqn) {
            String mapperId = classFqn + (pathPrefix.isEmpty() ? "" : "#" + m.name);
            // Identify target var.
            String returnType = m.returnType.split("<")[0].trim();
            String returnTypeFqn = imports.getOrDefault(returnType, pkg.isEmpty() ? returnType : pkg + "." + returnType);

            String targetVar = findTargetVar(m.body, returnType, m.params);
            if (targetVar == null) return;

            Map<String, ParamBinding> bindings = parseParams(m.params);

            // Walk all setter calls on targetVar.
            int lineBase = computeBodyLineBase(m);

            walkBodyForCalls(m.body, lineBase, targetVar, bindings, pathPrefix,
                    helpers, mapperId, returnTypeFqn, classFqn);
        }

        private void walkBodyForCalls(String body, int lineBase, String targetVar,
                                      Map<String, ParamBinding> bindings, String pathPrefix,
                                      Map<String, MethodBlock> helpers, String mapperId,
                                      String returnTypeFqn, String classFqn) {
            int len = body.length();
            int i = 0;
            while (i < len) {
                int dotIdx = -1;
                int helperIdx = -1;
                // Look for either "<targetVar>.set" or a top-level identifier+'.' that takes targetVar.getX as arg.
                int nextSetter = body.indexOf(targetVar + ".set", i);
                int nextHelper = findHelperMutatorStart(body, i, targetVar);

                if (nextSetter < 0 && nextHelper < 0) break;
                if (nextSetter >= 0 && (nextHelper < 0 || nextSetter < nextHelper)) {
                    // Setter call on targetVar.
                    int setterStart = nextSetter;
                    int parenStart = body.indexOf('(', setterStart);
                    if (parenStart < 0) { i = setterStart + 1; continue; }
                    int parenEnd = matchingParen(body, parenStart);
                    if (parenEnd < 0) { i = setterStart + 1; continue; }
                    String setterName = body.substring(setterStart + targetVar.length() + 1, parenStart);
                    if (!setterName.startsWith("set")) { i = parenStart + 1; continue; }
                    String fieldName = setterToField(setterName);
                    String rhs = body.substring(parenStart + 1, parenEnd).trim();
                    int line = lineBase + countLines(body, 0, setterStart);
                    handleSetter(rhs, fieldName, pathPrefix, bindings, helpers, line,
                            mapperId, returnTypeFqn, classFqn);
                    i = parenEnd + 1;
                } else {
                    // Helper mutator: <Util>.<method>(target.getX(), ...).
                    int parenStart = body.indexOf('(', nextHelper);
                    if (parenStart < 0) { i = nextHelper + 1; continue; }
                    int parenEnd = matchingParen(body, parenStart);
                    if (parenEnd < 0) { i = nextHelper + 1; continue; }
                    String callPrefix = body.substring(nextHelper, parenStart);
                    String args = body.substring(parenStart + 1, parenEnd);
                    int line = lineBase + countLines(body, 0, nextHelper);
                    handleEnrichment(callPrefix, args, pathPrefix, line, mapperId,
                            returnTypeFqn, targetVar);
                    i = parenEnd + 1;
                }
            }
        }

        private int findHelperMutatorStart(String body, int from, String targetVar) {
            // Scan for any identifier-chain followed by '(' whose args contain targetVar.getX(.
            // Heuristic: look for "(" then check args window for the targetVar getter pattern.
            int idx = body.indexOf(targetVar + ".get", from);
            if (idx < 0) return -1;
            // Walk backwards to find the start of the enclosing call.
            int p = idx;
            while (p > from) {
                char c = body.charAt(p);
                if (c == '\n' || c == ';' || c == '{' || c == '}') return -1;
                if (c == '(') {
                    // Check that this isn't the setter on targetVar itself.
                    int callerEnd = p;
                    int callerStart = callerEnd;
                    while (callerStart > 0) {
                        char cc = body.charAt(callerStart - 1);
                        if (Character.isWhitespace(cc) || cc == '\n' || cc == ';' || cc == '{' || cc == '}') break;
                        callerStart--;
                    }
                    String caller = body.substring(callerStart, callerEnd);
                    if (caller.startsWith(targetVar + ".set")) return -1;
                    return callerStart;
                }
                p--;
            }
            return -1;
        }

        private void handleSetter(String rhs, String fieldName, String pathPrefix,
                                  Map<String, ParamBinding> bindings,
                                  Map<String, MethodBlock> helpers, int line,
                                  String mapperId, String returnTypeFqn, String classFqn) {
            String fullPath = pathPrefix.isEmpty() ? fieldName : pathPrefix + "." + fieldName;

            // Helper recursion: rhs is `helperName(args)` and helperName is in helpers map.
            String trimmed = rhs.trim();
            int parenIdx = trimmed.indexOf('(');
            if (parenIdx > 0 && trimmed.endsWith(")")) {
                String head = trimmed.substring(0, parenIdx);
                if (!head.contains(".") && helpers.containsKey(head)) {
                    MethodBlock helper = helpers.get(head);
                    String args = trimmed.substring(parenIdx + 1, trimmed.length() - 1);
                    Map<String, ParamBinding> nestedBindings = bindHelperParams(helper, args, bindings);
                    walkMethod(new MethodBlock(helper.name, helper.returnType, helper.params,
                            true, helper.bodyStart, helper.bodyEnd, helper.body),
                            helpers, fullPath, classFqn);
                    return;
                }
            }

            EdgeKind kind = classifyRhs(trimmed);
            SourceMatch match = extractSource(trimmed, bindings);
            String staticHelperFqn = extractStaticHelperFqn(trimmed);

            FieldRef target = new FieldRef(returnTypeFqn, fullPath, ctx.target().schemaFile(),
                    lookupBusinessKey(ctx.target().schemaFile(), fullPath));
            FieldRef source = match == null ? null : new FieldRef(
                    match.binding.typeFqn, match.path, match.binding.schemaFile,
                    lookupBusinessKey(match.binding.schemaFile, match.path));

            String edgeId = EdgeIdGenerator.edgeId(
                    ctx.repoId(), ctx.pairId(), relFile, line, fullPath,
                    match == null ? null : match.path);
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
                    .expression(trimmed)
                    .staticHelperFqn(staticHelperFqn)
                    .scope(scopeEngine.infer(Path.of(relFile)))
                    .git(gitRef)
                    .confidence(Confidence.HIGH)
                    .build();
            rb.edge(edge);
        }

        private void handleEnrichment(String callPrefix, String args, String pathPrefix,
                                      int line, String mapperId, String returnTypeFqn,
                                      String targetVar) {
            String helperFqn = resolveCallableFqn(callPrefix);
            // Split args at top level, keep only target.getX(...) chains.
            List<String> argList = splitArgs(args);
            for (String arg : argList) {
                String t = arg.trim();
                if (!t.startsWith(targetVar + ".get")) continue;
                String pathFromArg = pathFromGetterChain(t.substring(targetVar.length() + 1));
                if (pathFromArg.isEmpty()) continue;
                String fullPath = pathPrefix.isEmpty() ? pathFromArg : pathPrefix + "." + pathFromArg;
                FieldRef target = new FieldRef(returnTypeFqn, fullPath, ctx.target().schemaFile(),
                        lookupBusinessKey(ctx.target().schemaFile(), fullPath));
                String edgeId = EdgeIdGenerator.edgeId(
                        ctx.repoId(), ctx.pairId(), relFile, line, fullPath,
                        "enrichment:" + helperFqn);
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
                        .expression(callPrefix + "(" + args + ")")
                        .staticHelperFqn(helperFqn)
                        .scope(scopeEngine.infer(Path.of(relFile)))
                        .git(gitRef)
                        .confidence(Confidence.LOW)
                        .build();
                rb.edge(edge);
            }
        }

        /* ─────────────────── source-side resolution ─────────────────── */

        private SourceMatch extractSource(String rhs, Map<String, ParamBinding> bindings) {
            String t = rhs.trim();
            if (t.isEmpty()) return null;
            if (t.startsWith("\"") || t.matches("-?[0-9].*") || t.equals("null")
                    || t.equals("true") || t.equals("false")) return null;

            // Strip outer parens.
            while (t.startsWith("(") && t.endsWith(")") && balanced(t.substring(1, t.length() - 1))) {
                t = t.substring(1, t.length() - 1).trim();
            }

            // Cast: (Type) expr -> recurse on expr.
            if (t.startsWith("(")) {
                int close = matchingParen(t, 0);
                if (close > 0 && close < t.length() - 1) {
                    return extractSource(t.substring(close + 1), bindings);
                }
            }

            // Identifier or chain: look for the leftmost segment.
            int firstParen = t.indexOf('(');
            int firstDot = t.indexOf('.');
            if (firstParen < 0 && firstDot < 0) {
                // Bare identifier.
                ParamBinding b = bindings.get(t);
                return b == null ? null : new SourceMatch(b, "");
            }

            // If there's a '.' before any '(', it's a getter chain like a.b.c() or a.getX().getY().
            if (firstDot >= 0 && (firstParen < 0 || firstDot < firstParen)) {
                // Parse the chain.
                return parseGetterChain(t, bindings);
            }

            // Otherwise it starts with a function call like Helper.method(...) or method(...).
            // Recurse into args looking for any source-bound expression.
            int parenStart = firstParen;
            int parenEnd = matchingParen(t, parenStart);
            if (parenEnd < 0) return null;
            String args = t.substring(parenStart + 1, parenEnd);
            for (String arg : splitArgs(args)) {
                SourceMatch m = extractSource(arg.trim(), bindings);
                if (m != null) return m;
            }
            return null;
        }

        private SourceMatch parseGetterChain(String s, Map<String, ParamBinding> bindings) {
            // Walk segments separated by '.', each segment optionally ending in "()".
            // Examples:
            //   "src.getField20()"
            //   "src.getField32A().getAmount()"
            //   "messageContext.getLegalEntity()"
            //   "src.getField50K()"
            int i = 0;
            int n = s.length();
            // First segment = identifier (the param).
            int dot = s.indexOf('.');
            if (dot < 0) {
                ParamBinding b = bindings.get(s.trim());
                return b == null ? null : new SourceMatch(b, "");
            }
            String head = s.substring(0, dot).trim();
            ParamBinding binding = bindings.get(head);
            if (binding == null) return null;
            StringBuilder path = new StringBuilder();
            int p = dot + 1;
            while (p < n) {
                int nextDot = -1;
                int parenAt = -1;
                int depth = 0;
                int q = p;
                while (q < n) {
                    char c = s.charAt(q);
                    if (c == '(') { parenAt = q; break; }
                    if (c == '.' && depth == 0) { nextDot = q; break; }
                    q++;
                }
                String segment;
                if (parenAt > 0) {
                    int close = matchingParen(s, parenAt);
                    if (close < 0) return null;
                    segment = s.substring(p, parenAt);
                    p = close + 1;
                } else if (nextDot > 0) {
                    segment = s.substring(p, nextDot);
                    p = nextDot;
                } else {
                    segment = s.substring(p, n);
                    p = n;
                }
                String fld = getterToField(segment.trim());
                if (path.length() > 0) path.append('.');
                path.append(fld);
                if (p < n && s.charAt(p) == '.') p++;
            }
            return new SourceMatch(binding, path.toString());
        }

        private static EdgeKind classifyRhs(String rhs) {
            String t = rhs.trim();
            if (t.startsWith("\"") || t.matches("-?[0-9].*") || t.equals("null")
                    || t.equals("true") || t.equals("false")) return EdgeKind.CONSTANT;
            if (t.contains("?") && t.contains(":")) return EdgeKind.CONDITIONAL;
            int firstDot = t.indexOf('.');
            int firstParen = t.indexOf('(');
            if (firstDot >= 0 && firstParen >= 0 && firstDot < firstParen) {
                // Looks like x.method(...) — may be field copy or wrapper.
                String head = t.substring(0, firstDot);
                if (head.length() > 0 && Character.isUpperCase(head.charAt(0))) return EdgeKind.STATIC_CALL;
                // x.getY() => field_copy; x.something(...) => expression.
                String segment = t.substring(firstDot + 1, firstParen);
                if (segment.startsWith("get")) return EdgeKind.FIELD_COPY;
                return EdgeKind.EXPRESSION;
            }
            if (firstParen > 0) {
                String head = t.substring(0, firstParen);
                if (head.length() > 0 && Character.isUpperCase(head.charAt(0))) return EdgeKind.STATIC_CALL;
                return EdgeKind.EXPRESSION;
            }
            return EdgeKind.EXPRESSION;
        }

        private String extractStaticHelperFqn(String rhs) {
            String t = rhs.trim();
            int dot = t.indexOf('.');
            int paren = t.indexOf('(');
            if (dot < 0 || paren < 0 || dot >= paren) return null;
            String head = t.substring(0, dot);
            if (head.isEmpty() || !Character.isUpperCase(head.charAt(0))) return null;
            String method = t.substring(dot + 1, paren);
            String fqnHead = imports.getOrDefault(head, head);
            return fqnHead + "." + method;
        }

        private String resolveCallableFqn(String callPrefix) {
            int dot = callPrefix.lastIndexOf('.');
            if (dot < 0) return callPrefix;
            String scope = callPrefix.substring(0, dot);
            String method = callPrefix.substring(dot + 1);
            String fqnScope = imports.getOrDefault(scope, scope);
            return fqnScope + "." + method;
        }

        /* ───────────────────── parameter handling ───────────────────── */

        private Map<String, ParamBinding> parseParams(String params) {
            Map<String, ParamBinding> out = new LinkedHashMap<>();
            String trimmed = params.trim();
            if (trimmed.isEmpty()) return out;
            for (String part : splitArgs(trimmed)) {
                String pt = part.trim();
                Matcher m = PARAM_RE.matcher(pt + ",");
                if (m.find()) {
                    String type = m.group(1).trim().split("<")[0].trim();
                    String name = m.group(2).trim();
                    String typeFqn = imports.getOrDefault(type, pkg.isEmpty() ? type : pkg + "." + type);
                    out.put(name, new ParamBinding(name, typeFqn, ctx.source().schemaFile()));
                }
            }
            return out;
        }

        private Map<String, ParamBinding> bindHelperParams(MethodBlock helper, String args,
                                                           Map<String, ParamBinding> caller) {
            Map<String, ParamBinding> helperOwn = parseParams(helper.params);
            // Override with caller bindings if arg is a bare NameExpr matching a caller binding.
            List<String> argList = splitArgs(args);
            int i = 0;
            for (Map.Entry<String, ParamBinding> e : helperOwn.entrySet()) {
                if (i >= argList.size()) break;
                String arg = argList.get(i++).trim();
                ParamBinding alias = caller.get(arg);
                if (alias != null) {
                    e.setValue(new ParamBinding(e.getKey(), alias.typeFqn, alias.schemaFile));
                }
            }
            return helperOwn;
        }

        private static String findTargetVar(String body, String returnType, String params) {
            Matcher m = LOCAL_NEW_RE.matcher(body);
            while (m.find()) {
                String declType = m.group(1);
                String varName = m.group(2);
                if (declType.equals(returnType)) return varName;
            }
            // Fallback: parameter of return type.
            Matcher pm = PARAM_RE.matcher(params + ",");
            while (pm.find()) {
                String pt = pm.group(1).trim().split("<")[0].trim();
                if (pt.equals(returnType)) return pm.group(2).trim();
            }
            return null;
        }

        /* ──────────────────────── string helpers ────────────────────── */

        private String relFile() {
            try {
                return ctx.repoRoot().toAbsolutePath()
                        .relativize(file.toAbsolutePath()).toString().replace('\\', '/');
            } catch (Exception e) {
                return file.toString();
            }
        }

        private String lookupBusinessKey(String schemaFile, String path) {
            Map<String, String> bk = ctx.businessKeys().get(schemaFile);
            return bk == null ? null : bk.get(path);
        }

        private static int matchingBrace(String s, int openIdx) {
            int depth = 0;
            int n = s.length();
            for (int i = openIdx; i < n; i++) {
                char c = s.charAt(i);
                if (c == '"') { i = skipString(s, i); continue; }
                if (c == '\'') { i = skipChar(s, i); continue; }
                if (c == '{') depth++;
                else if (c == '}') {
                    depth--;
                    if (depth == 0) return i;
                }
            }
            return -1;
        }

        private static int matchingParen(String s, int openIdx) {
            int depth = 0;
            int n = s.length();
            for (int i = openIdx; i < n; i++) {
                char c = s.charAt(i);
                if (c == '"') { i = skipString(s, i); continue; }
                if (c == '\'') { i = skipChar(s, i); continue; }
                if (c == '(') depth++;
                else if (c == ')') {
                    depth--;
                    if (depth == 0) return i;
                }
            }
            return -1;
        }

        private static int skipString(String s, int from) {
            int i = from + 1;
            while (i < s.length()) {
                char c = s.charAt(i);
                if (c == '\\') { i += 2; continue; }
                if (c == '"') return i;
                i++;
            }
            return s.length() - 1;
        }

        private static int skipChar(String s, int from) {
            int i = from + 1;
            while (i < s.length()) {
                char c = s.charAt(i);
                if (c == '\\') { i += 2; continue; }
                if (c == '\'') return i;
                i++;
            }
            return s.length() - 1;
        }

        private static List<String> splitArgs(String args) {
            List<String> out = new ArrayList<>();
            int depth = 0;
            StringBuilder cur = new StringBuilder();
            for (int i = 0; i < args.length(); i++) {
                char c = args.charAt(i);
                if (c == '"') { int e = skipString(args, i); cur.append(args, i, e + 1); i = e; continue; }
                if (c == '\'') { int e = skipChar(args, i); cur.append(args, i, e + 1); i = e; continue; }
                if (c == '(' || c == '<' || c == '[') { depth++; cur.append(c); }
                else if (c == ')' || c == '>' || c == ']') { depth--; cur.append(c); }
                else if (c == ',' && depth == 0) {
                    out.add(cur.toString());
                    cur.setLength(0);
                } else cur.append(c);
            }
            if (cur.length() > 0) out.add(cur.toString());
            return out;
        }

        private static boolean balanced(String s) {
            int depth = 0;
            for (int i = 0; i < s.length(); i++) {
                char c = s.charAt(i);
                if (c == '(') depth++;
                else if (c == ')') { depth--; if (depth < 0) return false; }
            }
            return depth == 0;
        }

        private static String setterToField(String setter) {
            String n = setter.substring(3);
            return n.isEmpty() ? n : Character.toLowerCase(n.charAt(0)) + n.substring(1);
        }

        private static String getterToField(String name) {
            String s = name.trim();
            if (s.startsWith("get")) {
                String n = s.substring(3);
                return n.isEmpty() ? n : Character.toLowerCase(n.charAt(0)) + n.substring(1);
            }
            if (s.startsWith("is")) {
                String n = s.substring(2);
                return n.isEmpty() ? n : Character.toLowerCase(n.charAt(0)) + n.substring(1);
            }
            return s;
        }

        private static String pathFromGetterChain(String chain) {
            // chain example: "getDbtrAcct().getIban()" — drop outer parens, walk segments.
            StringBuilder sb = new StringBuilder();
            int p = 0;
            while (p < chain.length()) {
                int paren = chain.indexOf('(', p);
                if (paren < 0) break;
                String seg = chain.substring(p, paren);
                int close = matchingParen(chain, paren);
                if (close < 0) break;
                if (sb.length() > 0) sb.append('.');
                sb.append(getterToField(seg));
                p = close + 1;
                if (p < chain.length() && chain.charAt(p) == '.') p++;
            }
            return sb.toString();
        }

        private static int countLines(String s, int from, int to) {
            int n = 0;
            for (int i = from; i < to && i < s.length(); i++) {
                if (s.charAt(i) == '\n') n++;
            }
            return n;
        }

        private int computeBodyLineBase(MethodBlock m) {
            // Approximation: line number is 1-based count of '\n' before the body in the
            // stripped text. Stripping preserves newlines so this is consistent with the
            // original file's line numbers for the purpose of citing the setter line.
            int classOffsetIdx = stripped.indexOf(m.body);
            return classOffsetIdx > 0 ? countLines(stripped, 0, classOffsetIdx) + 1 : 1;
        }
    }
}
