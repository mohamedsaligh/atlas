"""Resolver chain: extract the true source path of every setter RHS,
following qualifier methods and static helpers into their source.

Pipeline per RHS (deterministic, first match wins):

  1. Direct getter chain                  → kind=rename, fast path
  2. Wrapper-arg recursion                → kind=qualifier|static_call
  3. Qualifier body recursion             → walks helper class's method
  4. Static helper body recursion         → walks static class's method
  5. Intra-class helper body recursion    → existing behavior
  6. Conditional / cast / paren           → unwrap and retry
  7. Unmatched                            → kind=expression, source=null

Bounded by `max_depth`. A visited set per call prevents cycles.

Each resolution step appends a `Resolution` to the edge's trail, recording
the file/line/snippet/helper_fqn that was followed. The trail is the audit
proof that the source path is real and traceable.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import tree_sitter

from .config import ResolverConfig
from .index import (
    JavaIndex,
    fnmatch_class,
    _children_of_type,
    _descendants_of_type,
    _text,
)


# ── data ─────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ParamBinding:
    var_name: str
    type_fqn: str
    schema_id: str


@dataclass(frozen=True)
class Resolution:
    kind: str           # direct | wrapper_arg | qualifier | static_call | intra_class
    file: str
    line: int
    snippet: str
    helper_fqn: str | None = None


@dataclass(frozen=True)
class SourceMatch:
    binding: ParamBinding
    path: str
    trail: tuple[Resolution, ...] = ()

    def with_step(self, step: Resolution) -> "SourceMatch":
        return SourceMatch(self.binding, self.path, self.trail + (step,))


# ── public entry point ──────────────────────────────────────────────────────


def resolve_source(
    rhs: tree_sitter.Node,
    file_bytes: bytes,
    file_rel: str,
    bindings: dict[str, ParamBinding],
    index: JavaIndex,
    cfg: ResolverConfig,
    *,
    depth: int = 0,
    visited: set[tuple[str, str]] | None = None,
) -> SourceMatch | None:
    """Resolve an RHS expression to a SourceMatch (or None). Each step is
    recorded in the returned match's trail."""
    if visited is None:
        visited = set()
    if depth > cfg.max_depth:
        return None
    return _resolve(rhs, file_bytes, file_rel, bindings, index, cfg, depth, visited)


def _resolve(
    rhs: tree_sitter.Node,
    file_bytes: bytes,
    file_rel: str,
    bindings: dict[str, ParamBinding],
    index: JavaIndex,
    cfg: ResolverConfig,
    depth: int,
    visited: set[tuple[str, str]],
) -> SourceMatch | None:

    t = rhs.type

    # ── literals / nulls ─────────────────────────────────────────────────────
    if t in ("string_literal", "decimal_integer_literal", "hex_integer_literal",
             "octal_integer_literal", "binary_integer_literal",
             "decimal_floating_point_literal", "hex_floating_point_literal",
             "true", "false", "null_literal", "character_literal"):
        return None

    # ── identifier (a bare param) ────────────────────────────────────────────
    if t == "identifier":
        name = _text(rhs, file_bytes)
        b = bindings.get(name)
        return SourceMatch(b, "") if b is not None else None

    # ── field_access (already-dotted path) ──────────────────────────────────
    if t == "field_access":
        obj = rhs.child_by_field_name("object")
        field_node = rhs.child_by_field_name("field")
        if obj is None or field_node is None:
            return None
        head = _resolve(obj, file_bytes, file_rel, bindings, index, cfg, depth + 1, visited)
        if head is None:
            return None
        seg = _text(field_node, file_bytes)
        return SourceMatch(head.binding, f"{head.path}.{seg}" if head.path else seg, head.trail)

    # ── method_invocation: getter chain or wrapper or helper ────────────────
    if t == "method_invocation":
        return _resolve_call(rhs, file_bytes, file_rel, bindings, index, cfg, depth, visited)

    # ── ternary: prefer then-branch, else-branch on miss ─────────────────────
    if t == "ternary_expression":
        for child_name in ("consequence", "alternative"):
            sub = rhs.child_by_field_name(child_name)
            if sub is not None:
                m = _resolve(sub, file_bytes, file_rel, bindings, index, cfg, depth + 1, visited)
                if m is not None:
                    return m
        return None

    # ── parens / cast: unwrap ───────────────────────────────────────────────
    if t == "parenthesized_expression":
        for c in rhs.children:
            if c.is_named:
                return _resolve(c, file_bytes, file_rel, bindings, index, cfg, depth + 1, visited)
        return None
    if t == "cast_expression":
        for c in rhs.children:
            if c.is_named and c.type not in ("type_identifier", "scoped_type_identifier"):
                return _resolve(c, file_bytes, file_rel, bindings, index, cfg, depth + 1, visited)
        return None

    return None


def _resolve_call(
    call: tree_sitter.Node,
    file_bytes: bytes,
    file_rel: str,
    bindings: dict[str, ParamBinding],
    index: JavaIndex,
    cfg: ResolverConfig,
    depth: int,
    visited: set[tuple[str, str]],
) -> SourceMatch | None:
    name_node = call.child_by_field_name("name")
    obj = call.child_by_field_name("object")
    args = call.child_by_field_name("arguments")
    method_name = _text(name_node, file_bytes) if name_node is not None else ""

    # Step 1 — direct getter chain on a known param (fast path).
    if obj is not None and method_name.startswith("get"):
        head = _resolve(obj, file_bytes, file_rel, bindings, index, cfg, depth + 1, visited)
        if head is not None:
            fld = _getter_to_field(method_name)
            new_path = f"{head.path}.{fld}" if head.path else fld
            return SourceMatch(head.binding, new_path, head.trail)

    # Step 2 — qualifier body recursion (instance method on a configured class).
    qual_match = _try_qualifier(
        call, obj, name_node, args, method_name,
        file_bytes, file_rel, bindings, index, cfg, depth, visited,
    )
    if qual_match is not None:
        return qual_match

    # Step 3 — static helper body recursion.
    static_match = _try_static_helper(
        call, obj, name_node, args, method_name,
        file_bytes, file_rel, bindings, index, cfg, depth, visited,
    )
    if static_match is not None:
        return static_match

    # Step 4 — intra-class helper recursion (when configured + method lives in same file).
    if cfg.follow_intra_class:
        intra_match = _try_intra_class(
            call, obj, name_node, args, method_name,
            file_bytes, file_rel, bindings, index, cfg, depth, visited,
        )
        if intra_match is not None:
            return intra_match

    # Step 5 — wrapper-arg recursion: try each argument until one resolves.
    if args is not None:
        for arg in args.children:
            if not arg.is_named or arg.type in (",", "(", ")"):
                continue
            inner = _resolve(arg, file_bytes, file_rel, bindings, index, cfg, depth + 1, visited)
            if inner is not None:
                step = Resolution(
                    kind="wrapper_arg",
                    file=file_rel,
                    line=call.start_point[0] + 1,
                    snippet=_text(call, file_bytes),
                    helper_fqn=None,
                )
                return inner.with_step(step)
    return None


# ── qualifier following ────────────────────────────────────────────────────


def _try_qualifier(
    call: tree_sitter.Node,
    obj: tree_sitter.Node | None,
    name_node: tree_sitter.Node | None,
    args: tree_sitter.Node | None,
    method_name: str,
    file_bytes: bytes,
    file_rel: str,
    bindings: dict[str, ParamBinding],
    index: JavaIndex,
    cfg: ResolverConfig,
    depth: int,
    visited: set[tuple[str, str]],
) -> SourceMatch | None:
    if obj is None or args is None or name_node is None:
        return None
    receiver_text = _text(obj, file_bytes)
    if not receiver_text or "." in receiver_text:
        return None
    if receiver_text and receiver_text[0].isupper():
        return None  # static call, handled separately

    # Resolve receiver type by walking up to the enclosing class & looking up
    # field type in the index.
    enclosing_class = _enclosing_class_fqn(call, file_bytes, file_rel, index)
    if enclosing_class is None:
        return None
    receiver_type = index.field_type(enclosing_class, receiver_text)
    if receiver_type is None:
        return None
    pkg = index.package_of(file_rel)
    receiver_fqn = index.resolve_simple(receiver_type.split("<")[0].strip(), file_rel, pkg)
    if not _matches_any(receiver_fqn, cfg.qualifier_classes):
        return None

    helper = index.lookup_method(receiver_fqn, method_name)
    if helper is None:
        return None
    cycle_key = (receiver_fqn, method_name)
    if cycle_key in visited:
        return None

    return _walk_helper_method(
        helper, receiver_fqn, method_name, args,
        file_bytes, file_rel, bindings, index, cfg, depth, visited | {cycle_key},
        kind="qualifier",
        call_node=call,
    )


# ── static helper following ─────────────────────────────────────────────────


def _try_static_helper(
    call: tree_sitter.Node,
    obj: tree_sitter.Node | None,
    name_node: tree_sitter.Node | None,
    args: tree_sitter.Node | None,
    method_name: str,
    file_bytes: bytes,
    file_rel: str,
    bindings: dict[str, ParamBinding],
    index: JavaIndex,
    cfg: ResolverConfig,
    depth: int,
    visited: set[tuple[str, str]],
) -> SourceMatch | None:
    if obj is None or args is None:
        return None
    scope_text = _text(obj, file_bytes)
    if not scope_text or not scope_text[0].isupper():
        return None

    pkg = index.package_of(file_rel)
    scope_fqn = index.resolve_simple(scope_text.split(".")[0], file_rel, pkg)
    # Allow inner-class disambiguation: Outer.Inner -> resolve(Outer) + ".Inner"
    if "." in scope_text:
        tail = scope_text.split(".", 1)[1]
        scope_fqn = f"{scope_fqn}.{tail}"

    if not _matches_any(scope_fqn, cfg.static_helper_classes):
        return None

    helper = index.lookup_method(scope_fqn, method_name)
    if helper is None:
        return None
    cycle_key = (scope_fqn, method_name)
    if cycle_key in visited:
        return None

    return _walk_helper_method(
        helper, scope_fqn, method_name, args,
        file_bytes, file_rel, bindings, index, cfg, depth, visited | {cycle_key},
        kind="static_call",
        call_node=call,
    )


# ── intra-class helper following ────────────────────────────────────────────


def _try_intra_class(
    call: tree_sitter.Node,
    obj: tree_sitter.Node | None,
    name_node: tree_sitter.Node | None,
    args: tree_sitter.Node | None,
    method_name: str,
    file_bytes: bytes,
    file_rel: str,
    bindings: dict[str, ParamBinding],
    index: JavaIndex,
    cfg: ResolverConfig,
    depth: int,
    visited: set[tuple[str, str]],
) -> SourceMatch | None:
    if obj is not None or args is None:
        return None  # only bare calls (helperName(args)), not target.helperName
    enclosing_class = _enclosing_class_fqn(call, file_bytes, file_rel, index)
    if enclosing_class is None:
        return None
    helper = index.lookup_method(enclosing_class, method_name)
    if helper is None:
        return None
    cycle_key = (enclosing_class, method_name)
    if cycle_key in visited:
        return None

    return _walk_helper_method(
        helper, enclosing_class, method_name, args,
        file_bytes, file_rel, bindings, index, cfg, depth, visited | {cycle_key},
        kind="intra_class",
        call_node=call,
    )


# ── walking the helper body ────────────────────────────────────────────────


def _walk_helper_method(
    helper: tree_sitter.Node,
    helper_class_fqn: str,
    helper_method_name: str,
    caller_args: tree_sitter.Node,
    caller_file_bytes: bytes,
    caller_file_rel: str,
    caller_bindings: dict[str, ParamBinding],
    index: JavaIndex,
    cfg: ResolverConfig,
    depth: int,
    visited: set[tuple[str, str]],
    *,
    kind: str,
    call_node: tree_sitter.Node,
) -> SourceMatch | None:
    helper_fqn = f"{helper_class_fqn}.{helper_method_name}"
    helper_file = index.class_to_file.get(helper_class_fqn) or index.class_to_file.get(helper_class_fqn.split("$", 1)[0])
    if helper_file is None:
        return None
    helper_indexed = index.files.get(helper_file)
    if helper_indexed is None:
        return None

    helper_params = _parse_params(helper, helper_indexed.bytes, helper_file, index)
    new_bindings = _alias_caller_bindings(helper_params, caller_args, caller_file_bytes, caller_bindings)

    body = helper.child_by_field_name("body")
    if body is None:
        return None

    # 1. Best signal: a `return ...;` whose expression resolves.
    for ret in _descendants_of_type(body, "return_statement"):
        for c in ret.children:
            if c.is_named:
                inner = _resolve(c, helper_indexed.bytes, helper_file, new_bindings, index, cfg, depth + 1, visited)
                if inner is not None:
                    step = Resolution(
                        kind=kind,
                        file=caller_file_rel,
                        line=call_node.start_point[0] + 1,
                        snippet=_text(call_node, caller_file_bytes),
                        helper_fqn=helper_fqn,
                    )
                    return inner.with_step(step)
                break  # only inspect the first named child of the return statement

    # 2. If no return — try the first setter chain on a target var inside the helper.
    for call in _descendants_of_type(body, "method_invocation"):
        n = call.child_by_field_name("name")
        a = call.child_by_field_name("arguments")
        if n is None or a is None:
            continue
        nm = _text(n, helper_indexed.bytes)
        if not nm.startswith("set"):
            continue
        first = _first_arg(a)
        if first is None:
            continue
        inner = _resolve(first, helper_indexed.bytes, helper_file, new_bindings, index, cfg, depth + 1, visited)
        if inner is not None:
            step = Resolution(
                kind=kind,
                file=caller_file_rel,
                line=call_node.start_point[0] + 1,
                snippet=_text(call_node, caller_file_bytes),
                helper_fqn=helper_fqn,
            )
            return inner.with_step(step)

    return None


def _alias_caller_bindings(
    helper_params: dict[str, ParamBinding],
    caller_args: tree_sitter.Node,
    caller_bytes: bytes,
    caller_bindings: dict[str, ParamBinding],
) -> dict[str, ParamBinding]:
    out: dict[str, ParamBinding] = {}
    helper_names = list(helper_params.keys())
    arg_list = [c for c in caller_args.children if c.is_named and c.type not in (",", "(", ")")]
    for i, name in enumerate(helper_names):
        own = helper_params[name]
        if i < len(arg_list) and arg_list[i].type == "identifier":
            caller_var = _text(arg_list[i], caller_bytes)
            caller = caller_bindings.get(caller_var)
            if caller is not None:
                out[name] = ParamBinding(name, caller.type_fqn, caller.schema_id)
                continue
        out[name] = own
    return out


def _parse_params(
    method: tree_sitter.Node, file_bytes: bytes, file_rel: str, index: JavaIndex,
) -> dict[str, ParamBinding]:
    params_node = method.child_by_field_name("parameters")
    out: dict[str, ParamBinding] = {}
    if params_node is None:
        return out
    pkg = index.package_of(file_rel)
    for p in _children_of_type(params_node, "formal_parameter"):
        type_node = p.child_by_field_name("type")
        name_node = p.child_by_field_name("name")
        if type_node is None or name_node is None:
            continue
        type_str = _text(type_node, file_bytes).split("<")[0].strip()
        type_fqn = index.resolve_simple(type_str.split(".")[0], file_rel, pkg)
        if "." in type_str:
            type_fqn = f"{type_fqn}.{type_str.split('.', 1)[1]}"
        name = _text(name_node, file_bytes)
        out[name] = ParamBinding(name, type_fqn, "")
    return out


# ── tree helpers ────────────────────────────────────────────────────────────


def _enclosing_class_fqn(
    node: tree_sitter.Node, file_bytes: bytes, file_rel: str, index: JavaIndex,
) -> str | None:
    n = node.parent
    while n is not None:
        if n.type in ("class_declaration", "interface_declaration"):
            name_node = n.child_by_field_name("name")
            if name_node is None:
                return None
            simple = _text(name_node, file_bytes)
            pkg = index.package_of(file_rel)
            return f"{pkg}.{simple}" if pkg else simple
        n = n.parent
    return None


def _matches_any(fqn: str, patterns: list[str]) -> bool:
    return any(fnmatch_class(p, fqn) or p == fqn for p in patterns)


def _first_arg(arguments: tree_sitter.Node) -> tree_sitter.Node | None:
    for c in arguments.children:
        if c.is_named and c.type not in (",", "(", ")"):
            return c
    return None


def _getter_to_field(getter: str) -> str:
    if getter.startswith("get"):
        n = getter[3:]
        return n if not n else n[0].lower() + n[1:]
    if getter.startswith("is"):
        n = getter[2:]
        return n if not n else n[0].lower() + n[1:]
    return getter
