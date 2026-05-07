package com.x.atlas.plugin.ast;

import com.github.javaparser.ast.CompilationUnit;
import com.github.javaparser.ast.ImportDeclaration;
import com.github.javaparser.ast.PackageDeclaration;
import com.github.javaparser.ast.body.ClassOrInterfaceDeclaration;
import java.util.HashMap;
import java.util.Map;

/**
 * Cheap, hang-proof FQN resolver. Builds a {@code simpleName -> FQN} map from
 * the compilation unit's import declarations and same-package classes. Avoids
 * JavaSymbolSolver's classpath walk, which can hang for tens of minutes on
 * deep dependency trees.
 *
 * <p>Coverage:
 * <ul>
 *   <li>Imported types — resolved to their fully-qualified import target.</li>
 *   <li>Same-package classes (declared in the same CU) — resolved to {@code pkg.Name}.</li>
 *   <li>Inner classes via {@code Outer.Inner} — resolved to {@code import-of-Outer + "." + Inner}.</li>
 *   <li>Generics and arrays — stripped before lookup; the base name is resolved.</li>
 *   <li>Unknown types — returned as the supplied simple name (best-effort).</li>
 * </ul>
 *
 * <p>Built once per file, used many times.
 */
public final class TypeResolver {

    private final Map<String, String> simpleToFqn;
    private final String packageName;

    public TypeResolver(CompilationUnit cu) {
        this.simpleToFqn = new HashMap<>();
        this.packageName = cu.getPackageDeclaration()
                .map(PackageDeclaration::getNameAsString)
                .orElse("");

        for (ImportDeclaration imp : cu.getImports()) {
            if (imp.isStatic() || imp.isAsterisk()) continue;
            String fqn = imp.getNameAsString();
            int dot = fqn.lastIndexOf('.');
            String simple = dot >= 0 ? fqn.substring(dot + 1) : fqn;
            simpleToFqn.putIfAbsent(simple, fqn);
        }

        for (ClassOrInterfaceDeclaration cls : cu.findAll(ClassOrInterfaceDeclaration.class)) {
            String name = cls.getNameAsString();
            String fqn = packageName.isEmpty() ? name : packageName + "." + name;
            simpleToFqn.putIfAbsent(name, fqn);
        }

        // java.lang is implicitly imported.
        for (String langType : new String[]{
                "String", "Integer", "Long", "Double", "Float", "Boolean", "Byte",
                "Short", "Character", "Object", "Number", "Class", "Void", "Throwable",
                "Exception", "RuntimeException", "Error", "System"
        }) {
            simpleToFqn.putIfAbsent(langType, "java.lang." + langType);
        }
    }

    /**
     * Resolve a type expression as it appears in source (with possible generics
     * and inner-class qualifiers) to its best-effort FQN.
     */
    public String resolve(String typeExpr) {
        if (typeExpr == null || typeExpr.isEmpty()) return "";
        String stripped = stripGenerics(typeExpr).trim();

        // Already fully-qualified.
        if (stripped.contains(".") && Character.isLowerCase(stripped.charAt(0))) {
            return stripped;
        }

        // Inner-class form: Outer.Inner -> resolve Outer, append .Inner.
        int firstDot = stripped.indexOf('.');
        if (firstDot > 0) {
            String head = stripped.substring(0, firstDot);
            String tail = stripped.substring(firstDot + 1);
            String headFqn = simpleToFqn.get(head);
            if (headFqn != null) return headFqn + "." + tail;
            // Already looks fully qualified (Foo.Bar with no import) — return as-is.
            return stripped;
        }

        return simpleToFqn.getOrDefault(stripped, stripped);
    }

    private static String stripGenerics(String s) {
        int lt = s.indexOf('<');
        String base = lt >= 0 ? s.substring(0, lt) : s;
        return base.replace("[]", "").trim();
    }
}
