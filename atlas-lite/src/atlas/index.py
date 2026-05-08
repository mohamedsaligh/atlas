"""Repo-wide Java AST index. Built once per extraction run.

The resolver chain (resolvers.py) consults this index to look up qualifier
classes, static helper classes, and intra-class helper methods, even when
they live outside the file currently being walked.

Memory model: the parsed tree-sitter tree is kept alive by holding the file
bytes in `cu_by_file`. Trees release once the index is dropped.
"""

from __future__ import annotations

import os
import re
import sys
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path

import tree_sitter
import tree_sitter_java

_LANG: tree_sitter.Language | None = None


def _lang() -> tree_sitter.Language:
    global _LANG
    if _LANG is None:
        _LANG = tree_sitter.Language(tree_sitter_java.language())
    return _LANG


def _make_parser() -> tree_sitter.Parser:
    return tree_sitter.Parser(_lang())


_SKIP_DIR_NAMES: set[str] = {
    ".git",
    ".idea",
    ".vscode",
    ".gradle",
    ".settings",
    "node_modules",
    "build",
    "out",
    "bin",
    "dist",
    ".next",
    ".nuxt",
    ".cache",
    # Inside a Maven `target/`, only generated-sources is interesting.
    "classes",
    "test-classes",
    "dependency",
    "site",
    "surefire-reports",
    "failsafe-reports",
}


@dataclass
class IndexedFile:
    rel_path: str
    abs_path: Path
    bytes: bytes
    tree: tree_sitter.Tree


@dataclass
class JavaIndex:
    """Multi-file index of an entire repo (or set of repos)."""

    files: dict[str, IndexedFile] = field(default_factory=dict)
    class_to_file: dict[str, str] = field(default_factory=dict)
    methods_by_class: dict[str, dict[str, tree_sitter.Node]] = field(default_factory=dict)
    imports_by_file: dict[str, dict[str, str]] = field(default_factory=dict)
    field_types: dict[str, dict[str, str]] = field(default_factory=dict)
    superclass_raw: dict[str, str] = field(
        default_factory=dict
    )  # FQN → super simple name (unresolved)

    def lookup_method(self, class_fqn: str, method_name: str) -> tree_sitter.Node | None:
        return self.methods_by_class.get(class_fqn, {}).get(method_name)

    def file_for_class(self, class_fqn: str) -> IndexedFile | None:
        path = self.class_to_file.get(class_fqn)
        return self.files.get(path) if path else None

    def imports_for_file(self, rel_path: str) -> dict[str, str]:
        return self.imports_by_file.get(rel_path, {})

    def resolve_simple(self, simple_name: str, current_file: str, current_pkg: str) -> str:
        """Resolve a simple type/class name to its FQN within `current_file`'s
        import context. Falls back to current_pkg if the name appears as a
        class declared in the same package, or returns the simple_name as-is
        if no resolution is possible."""
        imps = self.imports_by_file.get(current_file, {})
        if simple_name in imps:
            return imps[simple_name]
        same_pkg = f"{current_pkg}.{simple_name}" if current_pkg else simple_name
        if same_pkg in self.class_to_file:
            return same_pkg
        return simple_name

    def field_type(self, class_fqn: str, field_name: str) -> str | None:
        return self.field_types.get(class_fqn, {}).get(field_name)

    def field_type_with_inheritance(self, class_fqn: str, field_name: str) -> str | None:
        """Walk the extends chain looking for a field. Used by the resolver
        when a field is declared on an abstract parent (common in MapStruct
        Impl extending an abstract base that holds qualifier instances)."""
        seen: set[str] = set()
        cur = class_fqn
        while cur and cur not in seen:
            seen.add(cur)
            ft = self.field_types.get(cur, {}).get(field_name)
            if ft is not None:
                return ft
            super_simple = self.superclass_raw.get(cur)
            if not super_simple:
                return None
            cur_file = self.class_to_file.get(cur)
            imps = self.imports_by_file.get(cur_file or "", {})
            cur = imps.get(super_simple, super_simple)
        return None

    def package_of(self, rel_path: str) -> str:
        f = self.files.get(rel_path)
        if f is None:
            return ""
        for n in _children_of_type(f.tree.root_node, "package_declaration"):
            for c in n.children:
                if c.type in ("scoped_identifier", "identifier"):
                    return _text(c, f.bytes)
        return ""


def build_index(
    roots: list[Path],
    *,
    max_workers: int = 4,
    verbose: bool = False,
) -> JavaIndex:
    """Walk every `*.java` file under each root and build the index.

    Skips the usual noise (build outputs, IDE folders) but ALWAYS keeps
    `target/generated-sources/`. Parallel parsing via thread pool — tree-
    sitter releases the GIL for parsing.
    """
    paths: list[tuple[str, Path]] = []
    for root in roots:
        if not root.exists():
            continue
        for abs_path in _walk_java(root):
            try:
                rel = abs_path.relative_to(root.parent if root.parent.exists() else root)
            except ValueError:
                rel = abs_path
            paths.append((str(rel).replace("\\", "/"), abs_path))

    if verbose:
        print(f"[atlas-index] {len(paths)} java file(s) discovered", file=sys.stderr)

    files: dict[str, IndexedFile] = {}
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(_parse_one, rel, abs): rel for rel, abs in paths}
        for fut in as_completed(futures):
            rel = futures[fut]
            try:
                f = fut.result()
                if f is not None:
                    files[rel] = f
            except Exception as e:
                if verbose:
                    print(f"[atlas-index] parse failed: {rel}: {e}", file=sys.stderr)

    index = JavaIndex(files=dict(sorted(files.items())))
    for rel, f in index.files.items():
        index.imports_by_file[rel] = _extract_imports(f.tree.root_node, f.bytes)
        pkg = ""
        for n in _children_of_type(f.tree.root_node, "package_declaration"):
            for c in n.children:
                if c.type in ("scoped_identifier", "identifier"):
                    pkg = _text(c, f.bytes)
        for cls in _all_type_decls(f.tree.root_node):
            name_node = cls.child_by_field_name("name")
            if name_node is None:
                continue
            simple = _text(name_node, f.bytes)
            fqn = f"{pkg}.{simple}" if pkg else simple
            # Inner classes get qualified with outer name.
            outer = cls.parent
            while outer is not None and outer.type not in (
                "class_declaration",
                "interface_declaration",
            ):
                outer = outer.parent
            if outer is not None:
                outer_name_node = outer.child_by_field_name("name")
                if outer_name_node is not None:
                    outer_simple = _text(outer_name_node, f.bytes)
                    outer_fqn = f"{pkg}.{outer_simple}" if pkg else outer_simple
                    fqn = f"{outer_fqn}${simple}"
            index.class_to_file[fqn] = rel
            method_map = index.methods_by_class.setdefault(fqn, {})
            field_map = index.field_types.setdefault(fqn, {})
            # Capture extends chain (raw simple name; resolved at lookup time).
            super_node = cls.child_by_field_name("superclass")
            if super_node is not None:
                for c in super_node.children:
                    if c.type in ("type_identifier", "scoped_type_identifier", "generic_type"):
                        super_text = _text(c, f.bytes).split("<")[0].strip()
                        if super_text:
                            index.superclass_raw[fqn] = super_text
                        break
            body = cls.child_by_field_name("body")
            if body is None:
                continue
            for m in _children_of_type(body, "method_declaration"):
                mname_node = m.child_by_field_name("name")
                if mname_node is None:
                    continue
                method_map.setdefault(_text(mname_node, f.bytes), m)
            for fld in _children_of_type(body, "field_declaration"):
                t_node = fld.child_by_field_name("type")
                if t_node is None:
                    continue
                t_text = _text(t_node, f.bytes).split("<")[0].strip()
                for vd in _descendants_of_type(fld, "variable_declarator"):
                    vname_node = vd.child_by_field_name("name")
                    if vname_node is not None:
                        field_map[_text(vname_node, f.bytes)] = t_text

    if verbose:
        print(
            f"[atlas-index] {len(index.files)} parsed, "
            f"{len(index.class_to_file)} classes, "
            f"{sum(len(v) for v in index.methods_by_class.values())} methods",
            file=sys.stderr,
        )
    return index


def _walk_java(root: Path) -> Iterable[Path]:
    for current, dirs, files in os.walk(root):
        # Skip noise. Special-case `target`: keep `generated-sources` and
        # `atlas`, drop the rest.
        pruned: list[str] = []
        for d in dirs:
            if d in _SKIP_DIR_NAMES:
                continue
            if Path(current).name == "target" and d not in ("generated-sources", "atlas"):
                continue
            pruned.append(d)
        dirs[:] = pruned
        for f in files:
            if f.endswith(".java"):
                yield Path(current) / f


def _parse_one(rel: str, abs_path: Path) -> IndexedFile | None:
    try:
        b = abs_path.read_bytes()
    except OSError:
        return None
    tree = _make_parser().parse(b)
    return IndexedFile(rel_path=rel, abs_path=abs_path, bytes=b, tree=tree)


def _extract_imports(cu: tree_sitter.Node, source: bytes) -> dict[str, str]:
    out: dict[str, str] = {}
    for n in _children_of_type(cu, "import_declaration"):
        ident = None
        for c in n.children:
            if c.type in ("scoped_identifier", "identifier"):
                ident = c
                break
        if ident is None:
            continue
        fqn = _text(ident, source).rstrip(";")
        if fqn.endswith(".*"):
            continue
        simple = fqn.rsplit(".", 1)[-1]
        out.setdefault(simple, fqn)
    return out


def _all_type_decls(node: tree_sitter.Node) -> list[tree_sitter.Node]:
    out: list[tree_sitter.Node] = []
    stack = [node]
    while stack:
        n = stack.pop()
        if n.type in ("class_declaration", "interface_declaration", "enum_declaration"):
            out.append(n)
        for c in n.children:
            stack.append(c)
    out.reverse()
    return out


def _children_of_type(node: tree_sitter.Node, t: str) -> list[tree_sitter.Node]:
    return [c for c in node.children if c.type == t]


def _descendants_of_type(node: tree_sitter.Node, t: str) -> list[tree_sitter.Node]:
    out: list[tree_sitter.Node] = []
    stack = [node]
    while stack:
        n = stack.pop()
        for c in n.children:
            if c.type == t:
                out.append(c)
            stack.append(c)
    out.reverse()
    return out


def _text(node: tree_sitter.Node | None, source: bytes) -> str:
    if node is None:
        return ""
    return source[node.start_byte : node.end_byte].decode("utf-8", errors="replace")


def fnmatch_class(pattern: str, fqn: str) -> bool:
    """Glob-style class-FQN match: `*` matches a single segment;
    `**` matches any number of segments. Returns True if `fqn` matches."""
    pat = re.escape(pattern).replace(r"\*\*", ".*").replace(r"\*", "[^.]*")
    return re.match("^" + pat + "$", fqn) is not None
