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

from dataclasses import dataclass

import tree_sitter

from .config import ResolverConfig
from .index import (
    JavaIndex,
    _children_of_type,
    _descendants_of_type,
    _text,
    fnmatch_class,
)

# ── data ─────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ParamBinding:
    var_name: str
    type_fqn: str
    schema_id: str
    # Path already walked by the caller before this binding entered scope.
    # When a helper is invoked with `helper(parent.getChild().getGrand())`,
    # the helper's parameter is aliased to the *caller's* root binding with
    # path_prefix="child.grand" — so when the helper does `param.getX()`
    # the resolver lands on root → "child.grand.x" rather than restarting
    # from an unbound type. This is what makes N-deep qualifier→static→
    # parameter-chain resolution traceable end-to-end.
    path_prefix: str = ""


@dataclass(frozen=True)
class Resolution:
    kind: str           # direct | wrapper_arg | qualifier | static_call | intra_class
    file: str
    line: int
    snippet: str
    helper_fqn: str | None = None
    # Helper body capture (populated only on qualifier / static_call / intra_class
    # steps — the steps that actually walked into a helper method body). The body
    # is kept on the Resolution so persist() can dedupe it into the `helper`
    # table by FQN. Markdown render then inlines this verbatim under each edge.
    helper_file: str | None = None
    helper_start_line: int | None = None
    helper_end_line: int | None = None
    helper_signature: str | None = None
    helper_body: str | None = None


@dataclass(frozen=True)
class SourceMatch:
    binding: ParamBinding
    path: str
    trail: tuple[Resolution, ...] = ()

    def with_step(self, step: Resolution) -> SourceMatch:
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
    locals_init: dict[str, tree_sitter.Node] | None = None,
) -> SourceMatch | None:
    """Resolve an RHS expression to a SourceMatch (or None). Each step is
    recorded in the returned match's trail.

    `locals_init` maps local-variable names (declared in the surrounding
    method body) to their initialiser AST node. When the resolver hits a
    bare identifier that isn't a method parameter, it consults this map
    and recurses into the initialiser — closing the
    `String channelName = mc.getHeader().getChannelName(); target.setX(channelName)`
    pattern.
    """
    if visited is None:
        visited = set()
    if depth > cfg.max_depth:
        return None
    return _resolve(rhs, file_bytes, file_rel, bindings, index, cfg, depth, visited, locals_init or {})


def _resolve(
    rhs: tree_sitter.Node,
    file_bytes: bytes,
    file_rel: str,
    bindings: dict[str, ParamBinding],
    index: JavaIndex,
    cfg: ResolverConfig,
    depth: int,
    visited: set[tuple[str, str]],
    locals_init: dict[str, tree_sitter.Node],
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
        if b is not None:
            # path_prefix is the path the caller already walked before this
            # binding entered scope (e.g. "txInfo.intermediaryAgent.financialInstId"
            # when this helper was invoked with that getter chain).
            return SourceMatch(b, b.path_prefix)
        # Local-var fallback: identifier names a method-local whose initialiser
        # might trace back to a known parameter.
        init = locals_init.get(name)
        if init is not None:
            return _resolve(init, file_bytes, file_rel, bindings, index, cfg, depth + 1, visited, locals_init)
        return None

    # ── field_access (already-dotted path) ──────────────────────────────────
    if t == "field_access":
        obj = rhs.child_by_field_name("object")
        field_node = rhs.child_by_field_name("field")
        if obj is None or field_node is None:
            return None
        head = _resolve(obj, file_bytes, file_rel, bindings, index, cfg, depth + 1, visited, locals_init)
        if head is None:
            return None
        seg = _text(field_node, file_bytes)
        return SourceMatch(head.binding, f"{head.path}.{seg}" if head.path else seg, head.trail)

    # ── method_invocation: getter chain or wrapper or helper ────────────────
    if t == "method_invocation":
        return _resolve_call(rhs, file_bytes, file_rel, bindings, index, cfg, depth, visited, locals_init)

    # ── ternary: prefer then-branch, else-branch on miss ─────────────────────
    if t == "ternary_expression":
        for child_name in ("consequence", "alternative"):
            sub = rhs.child_by_field_name(child_name)
            if sub is not None:
                m = _resolve(sub, file_bytes, file_rel, bindings, index, cfg, depth + 1, visited, locals_init)
                if m is not None:
                    return m
        return None

    # ── parens / cast: unwrap ───────────────────────────────────────────────
    if t == "parenthesized_expression":
        for c in rhs.children:
            if c.is_named:
                return _resolve(c, file_bytes, file_rel, bindings, index, cfg, depth + 1, visited, locals_init)
        return None
    if t == "cast_expression":
        for c in rhs.children:
            if c.is_named and c.type not in ("type_identifier", "scoped_type_identifier"):
                return _resolve(c, file_bytes, file_rel, bindings, index, cfg, depth + 1, visited, locals_init)
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
    locals_init: dict[str, tree_sitter.Node],
) -> SourceMatch | None:
    name_node = call.child_by_field_name("name")
    obj = call.child_by_field_name("object")
    args = call.child_by_field_name("arguments")
    method_name = _text(name_node, file_bytes) if name_node is not None else ""

    # Step 1 — direct getter chain on a known param (fast path).
    if obj is not None and method_name.startswith("get"):
        head = _resolve(obj, file_bytes, file_rel, bindings, index, cfg, depth + 1, visited, locals_init)
        if head is not None:
            fld = _getter_to_field(method_name)
            new_path = f"{head.path}.{fld}" if head.path else fld
            return SourceMatch(head.binding, new_path, head.trail)

    # Step 2 — qualifier body recursion (instance method on a configured class).
    qual_match = _try_qualifier(
        call, obj, name_node, args, method_name,
        file_bytes, file_rel, bindings, index, cfg, depth, visited, locals_init,
    )
    if qual_match is not None:
        return qual_match

    # Step 3 — static helper body recursion.
    static_match = _try_static_helper(
        call, obj, name_node, args, method_name,
        file_bytes, file_rel, bindings, index, cfg, depth, visited, locals_init,
    )
    if static_match is not None:
        return static_match

    # Step 4 — intra-class helper recursion (when configured + method lives in same file).
    if cfg.follow_intra_class:
        intra_match = _try_intra_class(
            call, obj, name_node, args, method_name,
            file_bytes, file_rel, bindings, index, cfg, depth, visited, locals_init,
        )
        if intra_match is not None:
            return intra_match

    # Step 5 — wrapper-arg recursion: try each argument until one resolves.
    if args is not None:
        for arg in args.children:
            if not arg.is_named or arg.type in (",", "(", ")"):
                continue
            inner = _resolve(arg, file_bytes, file_rel, bindings, index, cfg, depth + 1, visited, locals_init)
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
    locals_init: dict[str, tree_sitter.Node],
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
    receiver_type = index.field_type_with_inheritance(enclosing_class, receiver_text)
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
        caller_locals_init=locals_init,
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
    locals_init: dict[str, tree_sitter.Node],
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
        caller_locals_init=locals_init,
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
    locals_init: dict[str, tree_sitter.Node],
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
        caller_locals_init=locals_init,
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
    caller_locals_init: dict[str, tree_sitter.Node],
) -> SourceMatch | None:
    helper_fqn = f"{helper_class_fqn}.{helper_method_name}"
    helper_file = index.class_to_file.get(helper_class_fqn) or index.class_to_file.get(helper_class_fqn.split("$", 1)[0])
    if helper_file is None:
        return None
    helper_indexed = index.files.get(helper_file)
    if helper_indexed is None:
        return None

    helper_params = _parse_params(helper, helper_indexed.bytes, helper_file, index)
    # Alias each helper param to the caller's resolved root binding +
    # accumulated path prefix. Crucial for N-deep chains
    # (qualifier → static helper → param.getX().getY()).
    new_bindings = _alias_caller_bindings(
        helper_params, caller_args,
        caller_file_bytes, caller_file_rel, caller_bindings,
        index, cfg, depth, visited, caller_locals_init,
    )

    body = helper.child_by_field_name("body")
    if body is None:
        return None

    # Capture helper details once; reused on whichever step succeeds. Needed by
    # persist() to populate the `helper` table (BA-grade Markdown render).
    helper_signature = _helper_signature(helper, helper_indexed.bytes)
    helper_body_text = _text(helper, helper_indexed.bytes)
    helper_start_line = helper.start_point[0] + 1
    helper_end_line = helper.end_point[0] + 1

    def _step() -> Resolution:
        return Resolution(
            kind=kind,
            file=caller_file_rel,
            line=call_node.start_point[0] + 1,
            snippet=_text(call_node, caller_file_bytes),
            helper_fqn=helper_fqn,
            helper_file=helper_file,
            helper_start_line=helper_start_line,
            helper_end_line=helper_end_line,
            helper_signature=helper_signature,
            helper_body=helper_body_text,
        )

    # Collect helper's own locals — they're in scope inside the helper body.
    helper_locals = collect_locals(body)

    # 1. Best signal: a `return ...;` whose expression resolves.
    for ret in _descendants_of_type(body, "return_statement"):
        for c in ret.children:
            if c.is_named:
                inner = _resolve(c, helper_indexed.bytes, helper_file, new_bindings, index, cfg, depth + 1, visited, helper_locals)
                if inner is not None:
                    return inner.with_step(_step())
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
        inner = _resolve(first, helper_indexed.bytes, helper_file, new_bindings, index, cfg, depth + 1, visited, helper_locals)
        if inner is not None:
            return inner.with_step(_step())

    return None


def _helper_signature(method: tree_sitter.Node, file_bytes: bytes) -> str:
    """Slice the Java text from the method's start to its body's open brace.

    Captures modifiers, return type, name, parameter list, throws clause —
    everything a BA needs to read to judge what the helper does.
    """
    body = method.child_by_field_name("body")
    if body is None:
        return _text(method, file_bytes).strip().rstrip(";")
    end = body.start_byte
    return file_bytes[method.start_byte:end].decode("utf-8", errors="replace").strip()


def _alias_caller_bindings(
    helper_params: dict[str, ParamBinding],
    caller_args: tree_sitter.Node,
    caller_bytes: bytes,
    caller_file_rel: str,
    caller_bindings: dict[str, ParamBinding],
    index: JavaIndex,
    cfg: ResolverConfig,
    depth: int,
    visited: set[tuple[str, str]],
    caller_locals_init: dict[str, tree_sitter.Node],
) -> dict[str, ParamBinding]:
    """Alias each helper parameter to the caller's resolved source binding.

    For each caller arg in positional order, run the full resolver chain in
    the caller's scope. If it resolves to ``(root_binding, path)``, alias the
    helper's parameter to that root with ``path_prefix=path`` — so any
    dereference of the parameter inside the helper body lands on the original
    source schema with the full accumulated path.

    Falls back to the helper's own type-only binding when the arg can't be
    resolved (literal, computed expression, unconfigured helper, etc.).
    """
    out: dict[str, ParamBinding] = {}
    helper_names = list(helper_params.keys())
    arg_list = [c for c in caller_args.children if c.is_named and c.type not in (",", "(", ")")]
    for i, name in enumerate(helper_names):
        own = helper_params[name]
        if i < len(arg_list):
            m = _resolve(
                arg_list[i], caller_bytes, caller_file_rel, caller_bindings,
                index, cfg, depth + 1, visited, caller_locals_init,
            )
            if m is not None:
                out[name] = ParamBinding(
                    var_name=name,
                    type_fqn=m.binding.type_fqn,
                    schema_id=m.binding.schema_id,
                    path_prefix=m.path,
                )
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


# ── local-var collection ────────────────────────────────────────────────────


def collect_locals(method_body: tree_sitter.Node) -> dict[str, tree_sitter.Node]:
    """Map every method-local variable name → its initialiser AST node.

    Used by the resolver to chase identifiers that aren't method parameters
    but whose declared value traces back to one. Pattern:

        String channelName = mc.getHeader().getChannelName();
        target.setChannelName(channelName);

    `target.setChannelName(channelName)` → resolver hits identifier `channelName`,
    finds it in this map, recurses into the initialiser → resolves to
    `mc.header.channelName` on the MessageContext binding.
    """
    out: dict[str, tree_sitter.Node] = {}
    for v in _descendants_of_type(method_body, "local_variable_declaration"):
        for decl in _descendants_of_type(v, "variable_declarator"):
            name_node = decl.child_by_field_name("name")
            init = decl.child_by_field_name("value")
            if name_node is None or init is None:
                continue
            from_bytes = b""  # name extracted by caller via _text
            # Identifier text is whatever tree-sitter returned — caller already
            # has access to file_bytes. We just store the AST node; the name
            # is extracted by the consumer via _text(name_node, file_bytes).
            #
            # Storing the *node* means the consumer must know the source bytes.
            # Since collect_locals is always called from the same scope as the
            # body being walked, we can index by position-extracted text using
            # the byte slice from the source the body came from.
            out[_text_unsafe(name_node)] = init
    return out


def _text_unsafe(node: tree_sitter.Node) -> str:
    """Extract text from a node using its own byte range. Works without a
    bytes argument because tree-sitter exposes start/end byte offsets and the
    `text` attribute when it was parsed from bytes. Falls back to position-
    based `text` if available."""
    txt = getattr(node, "text", None)
    if isinstance(txt, (bytes, bytearray)):
        return bytes(txt).decode("utf-8", errors="replace")
    if isinstance(txt, str):
        return txt
    return ""
