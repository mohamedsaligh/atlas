package com.x.atlas.core.scope;

import com.x.atlas.core.model.Scope;
import com.x.atlas.core.spi.ExtractorContext.ScopeRule;
import java.nio.file.Path;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * Applies path-pattern rules to derive {@link Scope} tags from a file path.
 *
 * <p>Rules support two forms:
 * <ul>
 *   <li>{@code scope: {common: true}} — assigns a fixed scope payload.</li>
 *   <li>{@code capture: [country, clearing]} — captures path segments named
 *       in the pattern as named groups using {@code {name}} syntax.</li>
 * </ul>
 *
 * <p>First-match wins. Captured values are normalised to UPPER_SNAKE.
 */
public final class ScopeInferenceEngine {

    private final List<CompiledRule> rules;

    public ScopeInferenceEngine(List<ScopeRule> rules) {
        this.rules = rules.stream().map(ScopeInferenceEngine::compile).toList();
    }

    public Scope infer(Path repoRelative) {
        String path = repoRelative.toString().replace('\\', '/');
        for (CompiledRule r : rules) {
            Matcher m = r.regex.matcher(path);
            if (m.matches()) {
                Map<String, Object> scope = new LinkedHashMap<>();
                if (r.fixedScope != null) {
                    scope.putAll(r.fixedScope);
                }
                for (String name : r.captureNames) {
                    String v = safeGroup(m, name);
                    if (v != null) {
                        scope.put(name, normalize(v));
                    }
                }
                return toScope(scope);
            }
        }
        return Scope.ofEmpty();
    }

    private static String safeGroup(Matcher m, String name) {
        try {
            return m.group(name);
        } catch (IllegalArgumentException e) {
            return null;
        }
    }

    private static String normalize(String s) {
        return s.toUpperCase(Locale.ROOT).replace('-', '_');
    }

    private static Scope toScope(Map<String, Object> m) {
        return new Scope(
                (Boolean) m.get("common"),
                (String) m.get("country"),
                (String) m.get("clearing"),
                (String) m.get("product"),
                (String) m.get("fieldGroup")
        );
    }

    private static CompiledRule compile(ScopeRule rule) {
        String regex = globToRegex(rule.pattern());
        Pattern p = Pattern.compile(regex);
        Map<String, Object> fixed = rule.scope() == null ? null : new HashMap<>(rule.scope());
        List<String> capture = rule.capture() == null ? List.of() : rule.capture();
        return new CompiledRule(p, fixed, capture);
    }

    /**
     * Converts a glob with {name}-style captures into a Java regex.
     * Supported tokens: {@code **}, {@code *}, {@code {name}}.
     * Anything else is escaped literally.
     */
    static String globToRegex(String glob) {
        StringBuilder sb = new StringBuilder("^");
        int i = 0;
        while (i < glob.length()) {
            char c = glob.charAt(i);
            if (c == '*') {
                if (i + 1 < glob.length() && glob.charAt(i + 1) == '*') {
                    sb.append(".*");
                    i += 2;
                } else {
                    sb.append("[^/]*");
                    i++;
                }
            } else if (c == '{') {
                int end = glob.indexOf('}', i);
                if (end < 0) {
                    sb.append("\\{");
                    i++;
                } else {
                    String name = glob.substring(i + 1, end);
                    sb.append("(?<").append(name).append(">[^/]+)");
                    i = end + 1;
                }
            } else if ("\\.^$|()+?[]".indexOf(c) >= 0) {
                sb.append('\\').append(c);
                i++;
            } else {
                sb.append(c);
                i++;
            }
        }
        sb.append('$');
        return sb.toString();
    }

    private record CompiledRule(Pattern regex, Map<String, Object> fixedScope, List<String> captureNames) {}
}
