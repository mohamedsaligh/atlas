"""Tree-sitter Java extractor — produces edges, mappers, fields into SQLite.

Lessons from atlas-java applied here:

* **Multi-parameter binding.** Each method parameter is its own source.
  Edges are tagged with the actual parameter's type, not just the first
  parameter's. Fixes mappers like
  ``T mapFromPymt(MessageContext mc, PaymentInit pi)``.

* **Helper recursion with path prefix.** When ``target.setX(helper(args))``
  is seen and ``helper`` is a sibling method, its body is walked with
  the path prefix ``x``, producing nested-path edges
  (``dbtrAcct.iban ← field50K``).

* **Wrapper-arg source recursion.** When the RHS is
  ``Qualifier.method(src.getY())`` or ``Util.fn(src.getY())``, the source
  path is recovered from the inner getter chain. Otherwise these would
  emit ``source=null`` edges and lose the trail.

* **Helper mutator → kind=enrichment.** Calls of shape
  ``Helper.method(target.getX())`` outside a setter are detected and
  emit a synthetic ``kind=enrichment`` edge anchored at the getter path.

* **Target-var beyond fresh ``new T()``.** Method-parameter target vars
  and locals initialised by other method calls are also valid mapping
  targets, covering ``default mapFromReturn(T source)`` style code.

* **Tree-sitter parser** sidesteps the JavaParser+symbol-solver hangs
  observed on large generated impls.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import tree_sitter
import tree_sitter_java

from . import ATLAS_VERSION, TS_JAVA_VERSION
from .config import AtlasConfig, Pair, Repo, ResolverConfig, SchemaRef
from .index import JavaIndex, build_index
from .resolvers import (
    ParamBinding as ResolverParamBinding,
)
from .resolvers import (
    Resolution,
    collect_locals,
    resolve_source,
)
from .schemas import FieldAttrs, enumerate_fields

# ─────────────────────────────────────────────────────────────────────────────
# Tree-sitter setup
# ─────────────────────────────────────────────────────────────────────────────


def _make_parser() -> tree_sitter.Parser:
    lang = tree_sitter.Language(tree_sitter_java.language())
    p = tree_sitter.Parser(lang)
    return p


_PARSER: tree_sitter.Parser | None = None


def _parser() -> tree_sitter.Parser:
    global _PARSER
    if _PARSER is None:
        _PARSER = _make_parser()
    return _PARSER


# ─────────────────────────────────────────────────────────────────────────────
# Data classes
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class FieldRef:
    schema_id: str           # canonical schema name (e.g. "SWIFT_MT103.xsd")
    path: str
    business_key: str | None
    type_fqn: str | None


@dataclass(frozen=True)
class GitRef:
    repo: str
    sha: str
    file: str
    line: int
    browse_url: str


@dataclass
class Edge:
    pair_id: str
    mapper_id: str
    mapper_kind: str
    kind: str                # rename | constant | format | expression | concat | static_call | enrichment | unmapped | qualifier
    source: FieldRef | None
    target: FieldRef
    expression: str
    static_helper_fqn: str | None
    format_spec: dict[str, Any] | None
    git: GitRef
    scope: dict[str, Any] = field(default_factory=dict)
    trail: tuple[Resolution, ...] = ()
    entry_point_id: str | None = None

    def edge_id(self, repo_id: str) -> str:
        h = hashlib.sha1(
            f"{self.git.file}:{self.git.line}:{self.target.path}".encode()
        ).hexdigest()[:12]
        return f"{repo_id}.{self.pair_id}.e_{h}"


@dataclass
class MapperBlock:
    fqn: str
    kind: str
    pair_id: str
    repo_id: str
    file: str
    sha: str
    browse_url: str
    scope: dict[str, Any]


@dataclass
class EntryPoint:
    """A top-level transformation method — a public method that takes one or
    more source schemas and returns a target schema. The unit a Business
    Analyst reasons about; pivots Markdown, coverage, impact analysis, and the
    UI/graph onto methods rather than classes or files.
    """
    id: str
    pair_id: str
    repo_id: str
    class_fqn: str
    method_name: str
    method_signature: str
    source_schema_ids: list[str]
    target_schema_id: str
    file: str
    line: int
    sha: str
    browse_url: str
    scope: dict[str, Any]


@dataclass
class ExtractResult:
    edges: list[Edge] = field(default_factory=list)
    mappers: list[MapperBlock] = field(default_factory=list)
    entry_points: list[EntryPoint] = field(default_factory=list)
    unparseable: list[dict[str, str]] = field(default_factory=list)
    files_scanned: int = 0


# ─────────────────────────────────────────────────────────────────────────────
# Public entry point
# ─────────────────────────────────────────────────────────────────────────────


def run_extract(
    cfg: AtlasConfig,
    cfg_dir: Path,
    *,
    pair_filter: str | None = None,
    repo_filter: str | None = None,
    file_timeout_s: float = 60.0,
    verbose: bool = False,
) -> dict[tuple[str, str], ExtractResult]:
    """Run extraction across every (repo, pair) combination. Returns per-pair results."""
    out: dict[tuple[str, str], ExtractResult] = {}
    business_keys = _build_business_keys(cfg, cfg_dir)

    # Build a single repo-wide AST index. Used by the resolver chain to look up
    # qualifier classes, static helpers, and intra-class helpers across files.
    repo_paths = [Path(os.path.expanduser(r.path)).resolve() for r in cfg.repos
                  if (not repo_filter or r.id == repo_filter)]
    index = build_index(repo_paths, verbose=verbose)

    # The resolver config is per-pair (or per-method-selector). Default to an
    # empty config when none provided — back-compat with the existing pair model.
    resolver_cfg_default = ResolverConfig()

    # Map each pair_id to its resolver config (taken from method_selectors of
    # the same id, when present). This lets users configure qualifier_classes
    # and static_helper_classes on a per-pair basis from atlas.yml.
    selectors_by_id = {ms.id: ms for ms in cfg.method_selectors}

    for pair in cfg.pairs:
        if pair_filter and pair.id != pair_filter:
            continue
        # Resolver config priority:
        #   1. pair.resolvers (when set inline on the pair) — simplest user shape.
        #   2. method_selectors[id == pair.id].resolvers — when both blocks coexist.
        #   3. empty (back-compat: no helper following).
        if pair.resolvers is not None:
            rcfg = pair.resolvers
        elif pair.id in selectors_by_id:
            rcfg = selectors_by_id[pair.id].resolvers
        else:
            rcfg = resolver_cfg_default
        for repo in cfg.repos:
            if repo_filter and repo.id != repo_filter:
                continue
            sha = _git_sha(repo.path)
            if verbose:
                print(
                    f"[atlas] extract pair={pair.id} repo={repo.id} sha={sha[:8]} "
                    f"resolvers=qualifiers:{len(rcfg.qualifier_classes)} "
                    f"statics:{len(rcfg.static_helper_classes)} max_depth:{rcfg.max_depth}",
                    file=sys.stderr,
                )
            result = _run_pair_repo(
                cfg, cfg_dir, pair, repo, sha, business_keys, file_timeout_s, verbose,
                index=index, resolver_cfg=rcfg,
            )
            out[(repo.id, pair.id)] = result
    return out


# ─────────────────────────────────────────────────────────────────────────────
# Per-(repo, pair) extraction
# ─────────────────────────────────────────────────────────────────────────────


def _run_pair_repo(
    cfg: AtlasConfig,
    cfg_dir: Path,
    pair: Pair,
    repo: Repo,
    sha: str,
    business_keys: dict[str, dict[str, FieldAttrs]],
    file_timeout_s: float,
    verbose: bool,
    *,
    index: JavaIndex,
    resolver_cfg: ResolverConfig,
) -> ExtractResult:
    result = ExtractResult()
    repo_root = Path(repo.path).expanduser().resolve()

    extended_globs = _auto_extend_globs(pair.scan_globs)
    candidates = _scan_files(cfg_dir, extended_globs, repo_root)
    if verbose:
        print(f"[atlas] scanned {len(candidates)} candidate(s) for pair={pair.id} "
              f"(globs={len(extended_globs)})", file=sys.stderr)
    result.files_scanned = len(candidates)

    sources = pair.effective_sources()
    targets = pair.effective_targets()
    if not sources or not targets:
        return result
    fqn_to_source = _build_fqn_map(sources)
    fqn_to_target = _build_fqn_map(targets)
    default_source = sources[0]
    default_target = targets[0]

    browse_template = (cfg.bitbucket and cfg.bitbucket.browse_template) or ""

    start = time.monotonic()
    for file in candidates:
        # Per-file timeout safety net.
        if time.monotonic() - start > file_timeout_s * len(candidates):
            result.unparseable.append({"file": str(file), "reason": "global timeout"})
            break
        rel = _rel_to_repo(file, repo_root)
        try:
            walker = FileWalker(
                file=file,
                rel=rel,
                repo=repo,
                pair=pair,
                sha=sha,
                browse_template=browse_template,
                business_keys=business_keys,
                fqn_to_source=fqn_to_source,
                fqn_to_target=fqn_to_target,
                default_source=default_source,
                default_target=default_target,
                scope=_infer_scope(rel, pair.scan_globs, pair.scope_rules),
                index=index,
                resolver_cfg=resolver_cfg,
            )
            walker.walk(result)
        except Exception as e:
            result.unparseable.append({"file": str(rel), "reason": str(e)})

    return result


# ─────────────────────────────────────────────────────────────────────────────
# Per-file walker
# ─────────────────────────────────────────────────────────────────────────────


# ParamBinding moved to resolvers.py (single source of truth across modules).
ParamBinding = ResolverParamBinding


@dataclass
class FileWalker:
    file: Path
    rel: str
    repo: Repo
    pair: Pair
    sha: str
    browse_template: str
    business_keys: dict[str, dict[str, FieldAttrs]]
    fqn_to_source: dict[str, SchemaRef]
    fqn_to_target: dict[str, SchemaRef]
    default_source: SchemaRef
    default_target: SchemaRef
    scope: dict[str, Any]
    index: JavaIndex
    resolver_cfg: ResolverConfig

    def walk(self, result: ExtractResult) -> None:
        text = self.file.read_bytes()
        tree = _parser().parse(text)
        if tree.root_node.has_error:
            # Tree-sitter is robust to syntax errors; we keep going. Record
            # only true parse failures (none here — tree always builds).
            pass

        cu = tree.root_node
        package = self._package(cu, text)
        imports = self._imports(cu, text)

        for cls in _children_of_type(cu, "class_declaration"):
            class_name_node = _child_by_field(cls, "name")
            if class_name_node is None:
                continue
            class_name = _text(class_name_node, text)
            class_fqn = f"{package}.{class_name}" if package else class_name
            self._walk_class(cls, text, class_fqn, imports, result)

        for cls in _children_of_type(cu, "interface_declaration"):
            class_name_node = _child_by_field(cls, "name")
            if class_name_node is None:
                continue
            class_name = _text(class_name_node, text)
            class_fqn = f"{package}.{class_name}" if package else class_name
            self._walk_class(cls, text, class_fqn, imports, result)

    def _walk_class(
        self,
        cls: tree_sitter.Node,
        text: bytes,
        class_fqn: str,
        imports: dict[str, str],
        result: ExtractResult,
    ) -> None:
        body = _child_by_field(cls, "body")
        if body is None:
            return
        methods = {
            _text(_child_by_field(m, "name"), text): m
            for m in _children_of_type(body, "method_declaration")
            if _child_by_field(m, "name") is not None
        }
        if not methods:
            return

        kind = self._classify_class(text, class_fqn)

        # Entry methods: @Override annotated, OR public top-level (in non-MapStruct
        # mappers) that constructs a fresh target. Helpers (non-@Override) are only
        # walked via recursion from a setter.
        class_edges_before = len(result.edges)
        for name, m in methods.items():
            if kind == "mapstruct-impl" and not _has_override(m, text):
                continue  # helpers walked only via recursion
            params = self._parse_params(m, text, imports)
            if not params and not _has_target_var(m, text, imports):
                continue

            method_edges_before = len(result.edges)
            return_type_node = _child_by_field(m, "type")
            return_type = _text(return_type_node, text) if return_type_node else ""

            self._walk_method(
                m, text, class_fqn, name, params, methods, "", imports, result, kind
            )

            # Assemble an EntryPoint iff this method actually emitted edges.
            # Tag every newly-emitted edge with the entry-point id.
            if len(result.edges) > method_edges_before:
                target_fqn_local = imports.get(return_type, return_type)
                ep_id = self._entry_point_id(class_fqn, name, params, return_type)
                for edge in result.edges[method_edges_before:]:
                    edge.entry_point_id = ep_id
                method_line = m.start_point[0] + 1
                source_schema_ids = sorted({
                    p.schema_id for p in params.values() if p.schema_id
                })
                result.entry_points.append(EntryPoint(
                    id=ep_id,
                    pair_id=self.pair.id,
                    repo_id=self.repo.id,
                    class_fqn=class_fqn,
                    method_name=name,
                    method_signature=_method_signature(m, text),
                    source_schema_ids=source_schema_ids,
                    target_schema_id=self._schema_id_for_target(target_fqn_local),
                    file=self.rel,
                    line=method_line,
                    sha=self.sha,
                    browse_url=self._browse_url(method_line),
                    scope=self.scope,
                ))

        # Only record the mapper if it actually emitted edges (drops phantom
        # interface entries that have no body — they're not mappers, just signatures).
        if len(result.edges) > class_edges_before:
            browse_url = self._browse_url(0)
            result.mappers.append(MapperBlock(
                fqn=class_fqn,
                kind=kind,
                pair_id=self.pair.id,
                repo_id=self.repo.id,
                file=self.rel,
                sha=self.sha,
                browse_url=browse_url,
                scope=self.scope,
            ))

    def _walk_method(
        self,
        method: tree_sitter.Node,
        text: bytes,
        class_fqn: str,
        method_name: str,
        params: dict[str, ParamBinding],
        helpers: dict[str, tree_sitter.Node],
        path_prefix: str,
        imports: dict[str, str],
        result: ExtractResult,
        kind: str,
    ) -> None:
        body = _child_by_field(method, "body")
        if body is None:
            return
        return_type_node = _child_by_field(method, "type")
        return_type = _text(return_type_node, text) if return_type_node else ""
        target_fqn = imports.get(return_type, return_type)

        target_var = _find_target_var(body, text, return_type, params, imports)
        if target_var is None:
            return
        mapper_id = class_fqn

        # Collect method-local variables once per entry method body. Used by
        # the resolver to chase identifier RHS expressions back to their
        # initialiser when the identifier names a local var (Bucket C).
        self._method_locals = collect_locals(body)

        # Walk every method_invocation in the body.
        for call in _descendants_of_type(body, "method_invocation"):
            obj = _child_by_field(call, "object")
            name_node = _child_by_field(call, "name")
            if name_node is None:
                continue
            name = _text(name_node, text)
            args_node = _child_by_field(call, "arguments")
            line = call.start_point[0] + 1

            if obj is not None and _text(obj, text) == target_var and name.startswith("set"):
                self._handle_setter(
                    call, text, target_var, target_fqn, name, args_node,
                    params, helpers, path_prefix, imports, mapper_id, kind, result, line,
                )
            elif args_node is not None and _arg_is_target_chain(args_node, text, target_var):
                self._handle_enrichment(
                    call, text, target_var, target_fqn, name, args_node,
                    path_prefix, imports, mapper_id, kind, result, line,
                )

    def _handle_setter(
        self,
        call: tree_sitter.Node,
        text: bytes,
        target_var: str,
        target_fqn: str,
        method_name: str,
        args_node: tree_sitter.Node | None,
        params: dict[str, ParamBinding],
        helpers: dict[str, tree_sitter.Node],
        path_prefix: str,
        imports: dict[str, str],
        mapper_id: str,
        mapper_kind: str,
        result: ExtractResult,
        line: int,
    ) -> None:
        field_name = _setter_to_field(method_name)
        full_path = f"{path_prefix}.{field_name}" if path_prefix else field_name
        if args_node is None:
            return
        first_arg = _first_arg(args_node)
        if first_arg is None:
            return

        # Helper recursion: target.setX(helperName(args)) where helperName is a sibling method.
        if first_arg.type == "method_invocation":
            inner_name = _child_by_field(first_arg, "name")
            inner_obj = _child_by_field(first_arg, "object")
            if inner_name is not None and inner_obj is None:
                helper_name = _text(inner_name, text)
                if helper_name in helpers:
                    helper = helpers[helper_name]
                    helper_params = self._parse_params(helper, text, imports)
                    inner_args = _child_by_field(first_arg, "arguments")
                    if inner_args is not None:
                        helper_params = self._alias_caller_bindings(
                            helper_params, inner_args, text, params
                        )
                    self._walk_method(
                        helper, text, mapper_id, helper_name, helper_params, helpers,
                        full_path, imports, result, mapper_kind,
                    )
                    return

        # Classify + resolve source via the new chain (qualifier / static / intra-class).
        kind = _classify(first_arg, text)
        match = resolve_source(
            first_arg, text, self.rel, params, self.index, self.resolver_cfg,
            locals_init=getattr(self, "_method_locals", None),
        )
        static_helper_fqn = _extract_static_helper_fqn(first_arg, text, imports)

        # Refine kind based on what the resolver did.
        trail: tuple[Resolution, ...] = ()
        if match is not None:
            trail = match.trail
            if any(s.kind == "qualifier" for s in trail):
                kind = "qualifier"
            elif any(s.kind == "static_call" for s in trail):
                kind = "static_call"

        target_field = self._field_ref(target_fqn, full_path, self.default_target)
        source_field: FieldRef | None = None
        if match is not None:
            source_field = self._field_ref_for_binding(match.binding, match.path)

        result.edges.append(Edge(
            pair_id=self.pair.id,
            mapper_id=mapper_id,
            mapper_kind=mapper_kind,
            kind=kind,
            source=source_field,
            target=target_field,
            expression=_text(first_arg, text),
            static_helper_fqn=static_helper_fqn,
            format_spec=None,
            git=GitRef(self.repo.id, self.sha, self.rel, line, self._browse_url(line)),
            scope=self.scope,
            trail=trail,
        ))

    def _handle_enrichment(
        self,
        call: tree_sitter.Node,
        text: bytes,
        target_var: str,
        target_fqn: str,
        method_name: str,
        args_node: tree_sitter.Node,
        path_prefix: str,
        imports: dict[str, str],
        mapper_id: str,
        mapper_kind: str,
        result: ExtractResult,
        line: int,
    ) -> None:
        obj = _child_by_field(call, "object")
        receiver = _text(obj, text) if obj is not None else "?"
        helper_fqn = imports.get(receiver, receiver) + "." + method_name

        for arg in _children_of_type(args_node, "method_invocation") + _children_of_type(args_node, "field_access"):
            chain = _path_from_target_chain(arg, text, target_var)
            if not chain:
                continue
            full_path = f"{path_prefix}.{chain}" if path_prefix else chain
            target_field = self._field_ref(target_fqn, full_path, self.default_target)
            result.edges.append(Edge(
                pair_id=self.pair.id,
                mapper_id=mapper_id,
                mapper_kind=mapper_kind,
                kind="enrichment",
                source=None,
                target=target_field,
                expression=_text(call, text),
                static_helper_fqn=helper_fqn,
                format_spec=None,
                git=GitRef(self.repo.id, self.sha, self.rel, line, self._browse_url(line)),
                scope=self.scope,
            ))

    # ── helpers ──

    def _classify_class(self, text: bytes, class_fqn: str) -> str:
        if "/target/generated-sources/" in self.rel and b"org.mapstruct.ap.MappingProcessor" in text:
            return "mapstruct-impl"
        if b"@Mapper" in text:
            return "mapstruct-interface"
        for tgt in (self.default_target, *self.pair.effective_targets()):
            if tgt.kind == "fixedlen":
                return "fixedlen"
            if tgt.kind == "tagged":
                return "tagged"
        return "setter"

    def _parse_params(
        self, method: tree_sitter.Node, text: bytes, imports: dict[str, str]
    ) -> dict[str, ParamBinding]:
        params_node = _child_by_field(method, "parameters")
        out: dict[str, ParamBinding] = {}
        if params_node is None:
            return out
        for p in _children_of_type(params_node, "formal_parameter"):
            type_node = _child_by_field(p, "type")
            name_node = _child_by_field(p, "name")
            if type_node is None or name_node is None:
                continue
            type_str = _text(type_node, text).split("<")[0].strip()
            name = _text(name_node, text)
            type_fqn = imports.get(type_str.split(".")[0], type_str)
            schema_id = self._schema_id_for_fqn(type_fqn, source=True)
            out[name] = ParamBinding(name, type_fqn, schema_id)
        return out

    def _alias_caller_bindings(
        self,
        helper_params: dict[str, ParamBinding],
        inner_args: tree_sitter.Node,
        text: bytes,
        caller_params: dict[str, ParamBinding],
    ) -> dict[str, ParamBinding]:
        # Sibling-method recursion: alias each helper param to the caller's
        # binding when the arg is a bare identifier. Preserves the caller's
        # path_prefix so chains stay traceable across sibling-method hops.
        args_list = [
            c for c in inner_args.children
            if c.type not in (",", "(", ")") and c.is_named
        ]
        out: dict[str, ParamBinding] = {}
        helper_names = list(helper_params.keys())
        for i, name in enumerate(helper_names):
            if i < len(args_list) and args_list[i].type == "identifier":
                caller_var = _text(args_list[i], text)
                caller = caller_params.get(caller_var)
                if caller is not None:
                    out[name] = ParamBinding(
                        var_name=name,
                        type_fqn=caller.type_fqn,
                        schema_id=caller.schema_id,
                        path_prefix=caller.path_prefix,
                    )
                    continue
            out[name] = helper_params[name]
        return out

    def _schema_id_for_fqn(self, fqn: str, *, source: bool) -> str:
        m = self.fqn_to_source if source else self.fqn_to_target
        ref = m.get(fqn) or (self.default_source if source else self.default_target)
        return Path(ref.file).name

    def _schema_id_for_target(self, target_fqn: str) -> str:
        ref = self.fqn_to_target.get(target_fqn, self.default_target)
        return Path(ref.file).name

    def _entry_point_id(
        self,
        class_fqn: str,
        method_name: str,
        params: dict[str, ParamBinding],
        return_type: str,
    ) -> str:
        param_sig = ",".join(p.type_fqn.split(".")[-1] for p in params.values())
        raw = f"{self.repo.id}|{self.pair.id}|{class_fqn}#{method_name}({param_sig})->{return_type}"
        h = hashlib.sha1(raw.encode()).hexdigest()[:12]
        return f"{self.repo.id}.{self.pair.id}.ep_{h}"

    def _field_ref(self, type_fqn: str, path: str, default_ref: SchemaRef) -> FieldRef:
        ref = self.fqn_to_target.get(type_fqn, default_ref)
        schema_id = Path(ref.file).name
        bk = (self.business_keys.get(ref.file, {}).get(path)
              or FieldAttrs()).business_key
        return FieldRef(schema_id=schema_id, path=path, business_key=bk, type_fqn=type_fqn)

    def _field_ref_for_binding(self, binding: ParamBinding, path: str) -> FieldRef:
        ref = self.fqn_to_source.get(binding.type_fqn, self.default_source)
        schema_id = Path(ref.file).name
        bk = (self.business_keys.get(ref.file, {}).get(path)
              or FieldAttrs()).business_key
        return FieldRef(schema_id=schema_id, path=path, business_key=bk,
                        type_fqn=binding.type_fqn)

    def _browse_url(self, line: int) -> str:
        if not self.browse_template:
            return ""
        project = self.repo.project or "?"
        return self.browse_template.format(
            base=os.path.dirname(self.browse_template).rstrip("/"),
            project=project,
            repo=self.repo.id,
            file=self.rel,
            sha=self.sha,
            line=line,
        )

    def _package(self, cu: tree_sitter.Node, text: bytes) -> str:
        for n in _children_of_type(cu, "package_declaration"):
            for c in n.children:
                if c.type in ("scoped_identifier", "identifier"):
                    return _text(c, text)
        return ""

    def _imports(self, cu: tree_sitter.Node, text: bytes) -> dict[str, str]:
        out: dict[str, str] = {}
        for n in _children_of_type(cu, "import_declaration"):
            ident = None
            for c in n.children:
                if c.type in ("scoped_identifier", "identifier"):
                    ident = c
                    break
            if ident is None:
                continue
            fqn = _text(ident, text).rstrip(";")
            if fqn.endswith(".*"):
                continue
            simple = fqn.rsplit(".", 1)[-1]
            out.setdefault(simple, fqn)
        return out


# ─────────────────────────────────────────────────────────────────────────────
# Tree-sitter helpers (no .query() — uses children iteration; broadly compatible)
# ─────────────────────────────────────────────────────────────────────────────


def _text(node: tree_sitter.Node | None, source: bytes) -> str:
    if node is None:
        return ""
    return source[node.start_byte:node.end_byte].decode("utf-8", errors="replace")


def _child_by_field(node: tree_sitter.Node, name: str) -> tree_sitter.Node | None:
    return node.child_by_field_name(name)


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


def _first_arg(arguments: tree_sitter.Node) -> tree_sitter.Node | None:
    for c in arguments.children:
        if c.is_named and c.type not in (",", "(", ")"):
            return c
    return None


def _method_signature(method: tree_sitter.Node, text: bytes) -> str:
    """Slice from method start to body's open brace — captures modifiers,
    return type, name, parameters, and any throws clause. Single-line form."""
    body = _child_by_field(method, "body")
    if body is None:
        return _text(method, text).strip().rstrip(";")
    sig = text[method.start_byte:body.start_byte].decode("utf-8", errors="replace")
    return " ".join(sig.split()).strip()


# ─────────────────────────────────────────────────────────────────────────────
# Source-side resolution
# ─────────────────────────────────────────────────────────────────────────────


def _classify(node: tree_sitter.Node, text: bytes) -> str:
    t = node.type
    if t in ("string_literal", "decimal_integer_literal", "hex_integer_literal",
             "octal_integer_literal", "binary_integer_literal",
             "decimal_floating_point_literal", "hex_floating_point_literal",
             "true", "false", "null_literal", "character_literal"):
        return "constant"
    if t == "object_creation_expression":
        return "construction"
    if t == "array_creation_expression":
        return "construction"
    if t == "binary_expression":
        return "concat"
    if t == "ternary_expression":
        return "expression"
    if t == "method_invocation":
        name_node = _child_by_field(node, "name")
        obj = _child_by_field(node, "object")
        if name_node is not None and obj is not None:
            name = _text(name_node, text)
            scope = _text(obj, text)
            if scope and scope[0].isupper():
                return "static_call"
            if name.startswith("get") or name.endswith("substring") or name.endswith("toString"):
                return "format" if name in ("substring", "toString") else "rename"
        return "expression"
    if t in ("identifier", "field_access"):
        return "rename"
    return "expression"


def _extract_source(
    node: tree_sitter.Node, text: bytes, params: dict[str, ParamBinding]
) -> tuple[ParamBinding, str] | None:
    """Walk the RHS to find a source param + its dotted path. Recurses into
    method-invocation arguments when the call itself doesn't ground in a param
    (qualifier wrapper recovery)."""
    t = node.type
    if t in ("string_literal", "decimal_integer_literal", "hex_integer_literal",
             "octal_integer_literal", "binary_integer_literal",
             "decimal_floating_point_literal", "true", "false",
             "null_literal", "character_literal"):
        return None

    if t == "identifier":
        name = _text(node, text)
        b = params.get(name)
        return (b, "") if b is not None else None

    if t == "field_access":
        obj = _child_by_field(node, "object")
        field_node = _child_by_field(node, "field")
        if obj is None or field_node is None:
            return None
        head = _extract_source(obj, text, params)
        if head is None:
            return None
        binding, path = head
        seg = _text(field_node, text)
        return binding, f"{path}.{seg}" if path else seg

    if t == "method_invocation":
        name_node = _child_by_field(node, "name")
        obj = _child_by_field(node, "object")
        args_node = _child_by_field(node, "arguments")
        method_name = _text(name_node, text) if name_node is not None else ""

        # Direct getter chain: x.getY().getZ()
        if obj is not None and method_name.startswith("get"):
            head = _extract_source(obj, text, params)
            if head is not None:
                binding, path = head
                fld = _getter_to_field(method_name)
                return binding, f"{path}.{fld}" if path else fld

        # Wrapper: try each argument until one resolves.
        if args_node is not None:
            for arg in args_node.children:
                if arg.is_named and arg.type not in (",", "(", ")"):
                    inner = _extract_source(arg, text, params)
                    if inner is not None:
                        return inner
        return None

    if t == "ternary_expression":
        for child_name in ("consequence", "alternative"):
            sub = _child_by_field(node, child_name)
            if sub is not None:
                m = _extract_source(sub, text, params)
                if m is not None:
                    return m
        return None

    if t == "parenthesized_expression":
        for c in node.children:
            if c.is_named:
                return _extract_source(c, text, params)
        return None

    if t == "cast_expression":
        for c in node.children:
            if c.is_named and c.type != "type_identifier" and c.type != "scoped_type_identifier":
                return _extract_source(c, text, params)
        return None

    return None


def _extract_static_helper_fqn(
    node: tree_sitter.Node, text: bytes, imports: dict[str, str]
) -> str | None:
    if node.type != "method_invocation":
        return None
    obj = _child_by_field(node, "object")
    name_node = _child_by_field(node, "name")
    if obj is None or name_node is None:
        return None
    scope = _text(obj, text)
    if not scope or not scope[0].isupper():
        return None
    method = _text(name_node, text)
    head = scope.split(".")[0]
    fqn_head = imports.get(head, scope)
    if "." in scope:
        tail = scope.split(".", 1)[1]
        return f"{fqn_head}.{tail}.{method}"
    return f"{fqn_head}.{method}"


# ─────────────────────────────────────────────────────────────────────────────
# Target-var detection + helper utilities
# ─────────────────────────────────────────────────────────────────────────────


def _find_target_var(
    body: tree_sitter.Node,
    text: bytes,
    return_type: str,
    params: dict[str, ParamBinding],
    imports: dict[str, str],
) -> str | None:
    rt = return_type.split("<")[0].strip()
    # 1. local of return-type with `new T()` initialiser
    for v in _descendants_of_type(body, "local_variable_declaration"):
        type_node = _child_by_field(v, "type")
        type_str = _text(type_node, text).split("<")[0].strip() if type_node else ""
        for declr in _descendants_of_type(v, "variable_declarator"):
            name_node = _child_by_field(declr, "name")
            init = _child_by_field(declr, "value")
            if name_node is None:
                continue
            name = _text(name_node, text)
            init_text = _text(init, text) if init is not None else ""
            if (type_str == rt or type_str.endswith(f".{rt}")) and ("new " in init_text or True):
                return name
    # 2. parameter typed as the target
    for n, b in params.items():
        if b.type_fqn.split(".")[-1] == rt:
            return n
    return None


def _has_target_var(method: tree_sitter.Node, text: bytes, imports: dict[str, str]) -> bool:
    body = _child_by_field(method, "body")
    return body is not None and len(_descendants_of_type(body, "local_variable_declaration")) > 0


def _has_override(method: tree_sitter.Node, text: bytes) -> bool:
    for c in method.children:
        if c.type == "modifiers":
            for sub in c.children:
                if sub.type in ("marker_annotation", "annotation"):
                    name_node = _child_by_field(sub, "name")
                    if name_node is not None and _text(name_node, text) == "Override":
                        return True
    return False


def _arg_is_target_chain(args_node: tree_sitter.Node, text: bytes, target_var: str) -> bool:
    for c in args_node.children:
        if not c.is_named:
            continue
        if _path_from_target_chain(c, text, target_var):
            return True
    return False


def _path_from_target_chain(node: tree_sitter.Node, text: bytes, target_var: str) -> str:
    """If node is a `target_var.getX().getY()` chain, return `x.y`. Else "" """
    if node.type == "identifier":
        return ""
    if node.type == "field_access":
        obj = _child_by_field(node, "object")
        field_node = _child_by_field(node, "field")
        if obj is None or field_node is None:
            return ""
        head = _path_from_target_chain(obj, text, target_var) if obj.type != "identifier" else (
            "" if _text(obj, text) != target_var else ""
        )
        if obj.type == "identifier":
            if _text(obj, text) == target_var:
                return _text(field_node, text)
            return ""
        return f"{head}.{_text(field_node, text)}" if head else ""
    if node.type == "method_invocation":
        name_node = _child_by_field(node, "name")
        obj = _child_by_field(node, "object")
        if obj is None or name_node is None:
            return ""
        method_name = _text(name_node, text)
        if not method_name.startswith("get"):
            return ""
        if obj.type == "identifier":
            if _text(obj, text) != target_var:
                return ""
            return _getter_to_field(method_name)
        head = _path_from_target_chain(obj, text, target_var)
        if not head:
            return ""
        return f"{head}.{_getter_to_field(method_name)}"
    return ""


def _setter_to_field(setter: str) -> str:
    if not setter.startswith("set"):
        return setter
    n = setter[3:]
    return n if not n else n[0].lower() + n[1:]


def _getter_to_field(getter: str) -> str:
    if getter.startswith("get"):
        n = getter[3:]
        return n if not n else n[0].lower() + n[1:]
    if getter.startswith("is"):
        n = getter[2:]
        return n if not n else n[0].lower() + n[1:]
    return getter


# ─────────────────────────────────────────────────────────────────────────────
# Misc helpers
# ─────────────────────────────────────────────────────────────────────────────


def _build_business_keys(cfg: AtlasConfig, cfg_dir: Path) -> dict[str, dict[str, FieldAttrs]]:
    out: dict[str, dict[str, FieldAttrs]] = {}
    for pair in cfg.pairs:
        for ref in [*pair.effective_sources(), *pair.effective_targets()]:
            file = _resolve_ref_file(ref.file, cfg, cfg_dir)
            out[ref.file] = enumerate_fields(file, ref.kind)
    return out


def _resolve_ref_file(ref_file: str, cfg: AtlasConfig, cfg_dir: Path) -> Path:
    """Locate a schema file referenced by ``pair.sources/targets[].file``.

    YAMLs vary in where they place ``file:`` paths — some are relative to
    the directory holding ``atlas.yml`` (the typical Python convention),
    others are relative to the repo root one level up, others target a
    file under one of the configured ``repos[].path`` trees. Try each
    base in turn and stop at the first existing file. Used by
    ``_build_business_keys`` and ``compute_atlas_sha`` so coverage and
    determinism work regardless of which convention a user picked.
    """
    p = Path(os.path.expanduser(ref_file))
    if p.is_absolute() and p.is_file():
        return p
    bases: list[Path] = [cfg_dir, cfg_dir.parent]
    for repo in cfg.repos:
        repo_root = Path(os.path.expanduser(repo.path)).resolve()
        bases.extend([repo_root, repo_root.parent])
    seen: set[Path] = set()
    tried: list[Path] = []
    for base in bases:
        if base in seen:
            continue
        seen.add(base)
        candidate = (base / ref_file).resolve()
        tried.append(candidate)
        if candidate.is_file():
            return candidate
    print(
        f"[atlas] WARNING: schema file not found: {ref_file!r}\n"
        f"  searched: {[str(p) for p in tried]!r}\n"
        f"  coverage and atlas_sha will treat the file as empty.",
        file=sys.stderr,
    )
    return (cfg_dir / ref_file).resolve()


def _build_fqn_map(refs: list[SchemaRef]) -> dict[str, SchemaRef]:
    out: dict[str, SchemaRef] = {}
    for r in refs:
        for fqn in r.type_fqns:
            out[fqn] = r
    return out


_SKIP_DIRS = {".git", ".idea", ".vscode", ".gradle", "node_modules", "build", "out", "bin", "dist"}


def _auto_extend_globs(globs: list[str]) -> list[str]:
    """Add corresponding target/generated-sources/annotations/** for any glob
    that points at src/main/java. MapStruct generated impls live there and
    are the source of truth for mapping edges."""
    extended = list(globs)
    seen: set[str] = set()
    for g in globs:
        idx = g.find("/src/main/java/")
        if idx > 0:
            module_prefix = g[:idx]
            gen = f"{module_prefix}/target/generated-sources/annotations/**/*.java"
            if gen not in seen:
                seen.add(gen)
                extended.append(gen)
    return extended


def _scan_files(cfg_dir: Path, globs: list[str], repo_root: Path) -> list[Path]:
    """Walk repo_root collecting files that match any of `globs` (interpreted relative
    to repo_root). Honors `{captures}` syntax by treating placeholders as one segment."""
    if not repo_root.exists():
        return []
    patterns = [_glob_to_regex(g) for g in globs]
    hits: list[Path] = []
    for root, dirs, files in os.walk(repo_root):
        dirs[:] = [d for d in dirs if d not in _SKIP_DIRS or d == "target"]  # keep target/generated-sources
        for f in files:
            if not f.endswith(".java"):
                continue
            full = Path(root) / f
            rel = full.relative_to(repo_root.parent if repo_root.parent.exists() else repo_root)
            rel_str = str(rel).replace("\\", "/")
            for pat in patterns:
                if pat.match(rel_str):
                    hits.append(full)
                    break
    hits.sort(key=lambda p: str(p).lower())
    return hits


def _glob_to_regex(glob: str) -> re.Pattern[str]:
    parts = []
    i = 0
    while i < len(glob):
        c = glob[i]
        if c == "{":
            end = glob.index("}", i)
            parts.append(r"[^/]+")
            i = end + 1
        elif c == "*" and i + 1 < len(glob) and glob[i + 1] == "*":
            parts.append(r".*")
            i += 2
            if i < len(glob) and glob[i] == "/":
                i += 1
        elif c == "*":
            parts.append(r"[^/]*")
            i += 1
        elif c in r".^$+|()[]\\":
            parts.append(re.escape(c))
            i += 1
        else:
            parts.append(c)
            i += 1
    return re.compile("^" + "".join(parts) + "$")


def _infer_scope(rel: str, _globs: list[str], rules: list[Any]) -> dict[str, Any]:
    """Apply scope_rules in order; first match wins.

    Each rule is either:
      - glob-based: matches the relative file path. Optional `capture` lists
        named placeholders ({country}, {clearing}, ...) in the glob; their
        captured values populate scope. `scope` literal is merged on top.
      - filename_pattern-based: a Python regex with named groups applied to
        the simple file name (basename). Named groups become scope entries.
    """
    rel_unix = rel.replace("\\", "/")
    basename = rel_unix.rsplit("/", 1)[-1]
    out: dict[str, Any] = {}

    for r in rules:
        scope_payload = dict(r.scope or {})

        if getattr(r, "glob", None):
            regex, group_names = _glob_to_regex_with_groups(r.glob)
            m = regex.match(rel_unix)
            if m:
                for name in group_names:
                    val = m.group(name)
                    if val:
                        scope_payload.setdefault(name, _normalise(val))
                out.update(scope_payload)
                return out

        if getattr(r, "filename_pattern", None):
            pat = re.compile(r.filename_pattern)
            m = pat.match(basename)
            if m:
                for name, val in m.groupdict().items():
                    if val:
                        scope_payload.setdefault(name, _normalise(val))
                out.update(scope_payload)
                return out

    return out


def _normalise(s: str) -> str:
    """sg_fast → SG_FAST. ar → AR. Coelsa → COELSA."""
    return re.sub(r"[^A-Za-z0-9]+", "_", s).strip("_").upper()


def _glob_to_regex_with_groups(glob: str) -> tuple[re.Pattern[str], list[str]]:
    """Convert {placeholder} to (?P<placeholder>[^/]+); ** → .*; * → [^/]*."""
    parts: list[str] = []
    groups: list[str] = []
    i = 0
    while i < len(glob):
        c = glob[i]
        if c == "{":
            end = glob.index("}", i)
            name = glob[i + 1 : end]
            groups.append(name)
            parts.append(f"(?P<{name}>[^/]+)")
            i = end + 1
        elif c == "*" and i + 1 < len(glob) and glob[i + 1] == "*":
            parts.append(r".*")
            i += 2
            if i < len(glob) and glob[i] == "/":
                i += 1
        elif c == "*":
            parts.append(r"[^/]*")
            i += 1
        elif c in r".^$+|()[]\\":
            parts.append(re.escape(c))
            i += 1
        else:
            parts.append(c)
            i += 1
    return re.compile("^" + "".join(parts) + "$"), groups


def _git_sha(repo_path: str) -> str:
    try:
        out = subprocess.run(
            ["git", "-C", os.path.expanduser(repo_path), "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=5,
        )
        if out.returncode == 0:
            return out.stdout.strip()
    except Exception:
        pass
    return "0" * 40


def _rel_to_repo(file: Path, repo_root: Path) -> str:
    try:
        return str(file.relative_to(repo_root.parent)).replace("\\", "/")
    except ValueError:
        try:
            return str(file.relative_to(repo_root)).replace("\\", "/")
        except ValueError:
            return str(file)


# ─────────────────────────────────────────────────────────────────────────────
# Snapshot SHA + DB persistence
# ─────────────────────────────────────────────────────────────────────────────


def compute_atlas_sha(cfg: AtlasConfig, cfg_dir: Path, results: dict[tuple[str, str], ExtractResult]) -> str:
    inputs: list[Any] = [("extractor_version", ATLAS_VERSION),
                          ("tree_sitter_java_version", TS_JAVA_VERSION)]
    for repo in cfg.repos:
        inputs.append(("repo", repo.id, _git_sha(repo.path)))
    for pair in cfg.pairs:
        for ref in [*pair.effective_sources(), *pair.effective_targets()]:
            file = _resolve_ref_file(ref.file, cfg, cfg_dir)
            h = hashlib.sha256(file.read_bytes()).hexdigest() if file.is_file() else "0" * 64
            inputs.append(("schema", ref.file, h))
    inputs.sort(key=str)
    return hashlib.sha256(json.dumps(inputs, sort_keys=True, default=str).encode()).hexdigest()


def _populate_coverage(
    cur,
    cfg: AtlasConfig,
    results: dict[tuple[str, str], ExtractResult],
    business_keys: dict[str, dict[str, FieldAttrs]],
) -> None:
    """Compute and persist two distinct, non-interchangeable metrics.

    * **Pair-level ``coverage_percent``** (on ``coverage``): fraction of
      the union of every target schema's leaves that at least one edge
      writes. Answers "is the (repo, pair) mapping complete?".
    * **Per-entry-point ``resolution_percent``** (on ``entry_point``):
      fraction of this EP's own edges whose ``source_field_id`` landed
      on a real schema path. Answers "did the resolver succeed for the
      fields this method writes?".

    Pair-level uses the schema as denominator (so a fully-implemented
    pair is 100%). Per-EP uses the EP's own edge count as denominator
    (so a narrow-scope EP that resolves all 5 of its 5 edges is 100%,
    not 0.5%). Conflating the two would mislead a BA scanning the
    index — the advisor caught this and we keep the metrics named for
    what they actually measure.
    """
    pairs_by_id: dict[str, Pair] = {p.id: p for p in cfg.pairs}

    for (repo_id, pair_id), res in results.items():
        pair = pairs_by_id.get(pair_id)
        if pair is None:
            continue
        target_leaves = _target_leaves(pair, business_keys)
        denom = len(target_leaves)
        if denom == 0:
            continue
        covered_paths = {
            r[0] for r in cur.execute(
                """SELECT DISTINCT tf.path
                   FROM edge e JOIN field tf ON e.target_field_id = tf.id
                   JOIN mapper m ON e.mapper_id = m.id
                   WHERE e.pair_id = ? AND m.repo_id = ?""",
                (pair_id, repo_id),
            )
        }
        intersect = covered_paths & target_leaves
        unmatched = sorted(target_leaves - covered_paths)
        pct = round(100.0 * len(intersect) / denom, 2)
        cur.execute(
            """UPDATE coverage SET unmatched_json = ?, target_field_count = ?,
               coverage_percent = ? WHERE repo_id = ? AND pair_id = ?""",
            (json.dumps(unmatched, sort_keys=True), denom, pct, repo_id, pair_id),
        )

    # Per-entry-point resolution % — one global pass, computed off the
    # edge table directly. Independent of pair-level coverage.
    ep_resolution = cur.execute(
        """SELECT entry_point_id,
                  COUNT(*)                                         AS total,
                  SUM(CASE WHEN source_field_id IS NOT NULL
                           THEN 1 ELSE 0 END)                      AS resolved
           FROM edge
           WHERE entry_point_id IS NOT NULL
           GROUP BY entry_point_id""",
    ).fetchall()
    for ep_id, total, resolved in ep_resolution:
        if total == 0:
            continue
        pct = round(100.0 * resolved / total, 2)
        cur.execute(
            "UPDATE entry_point SET resolution_percent = ? WHERE id = ?",
            (pct, ep_id),
        )


def _target_leaves(
    pair: Pair, business_keys: dict[str, dict[str, FieldAttrs]],
) -> set[str]:
    out: set[str] = set()
    for tgt in pair.effective_targets():
        out.update(business_keys.get(tgt.file, {}).keys())
    return out




def persist(
    conn,
    cfg: AtlasConfig,
    cfg_dir: Path,
    results: dict[tuple[str, str], ExtractResult],
    business_keys: dict[str, dict[str, FieldAttrs]],
    atlas_sha: str,
) -> None:
    cur = conn.cursor()
    # repo
    for repo in cfg.repos:
        sha = _git_sha(repo.path)
        browse = (cfg.bitbucket and cfg.bitbucket.browse_template) or ""
        cur.execute("INSERT OR REPLACE INTO repo VALUES (?, ?, ?, ?, ?)",
                    (repo.id, repo.project, repo.branch or "main", sha, browse))
    # schema + field
    for pair in cfg.pairs:
        for ref in [*pair.effective_sources(), *pair.effective_targets()]:
            schema_id = Path(ref.file).name
            cur.execute("INSERT OR REPLACE INTO schema VALUES (?, ?, ?, ?)",
                        (schema_id, ref.name, ref.kind, ref.file))
            for path, attrs in business_keys.get(ref.file, {}).items():
                fid = f"{schema_id}#{path}"
                cur.execute(
                    "INSERT OR REPLACE INTO field VALUES (?, ?, ?, ?, ?)",
                    (fid, schema_id, path, attrs.business_key, attrs.type_hint),
                )
                cur.execute(
                    "INSERT INTO field_fts (field_id, schema, path, business_key, type) VALUES (?, ?, ?, ?, ?)",
                    (fid, schema_id, path, attrs.business_key or "", attrs.type_hint or ""),
                )
    # mappers + entry_points + edges + helpers + coverage
    seen_field_ids: set[str] = set()
    seen_helper_fqns: set[str] = set()
    edge_total = 0
    mapper_total = 0
    entry_point_total = 0
    # Pre-aggregate edge counts per entry-point id across all results.
    edges_per_ep: dict[str, int] = {}
    for (_repo_id, _pair_id), res in results.items():
        for e in res.edges:
            if e.entry_point_id:
                edges_per_ep[e.entry_point_id] = edges_per_ep.get(e.entry_point_id, 0) + 1

    for (repo_id, pair_id), res in results.items():
        for m in res.mappers:
            cur.execute(
                "INSERT OR REPLACE INTO mapper VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (m.fqn, m.fqn, m.kind, m.pair_id, m.repo_id, m.file, m.sha, m.browse_url,
                 1 if m.scope.get("common") else 0,
                 m.scope.get("country"), m.scope.get("clearing"),
                 m.scope.get("product"), m.scope.get("field_group")),
            )
            cur.execute(
                "INSERT INTO mapper_fts (mapper_id, fqn, scope_text) VALUES (?, ?, ?)",
                (m.fqn, m.fqn, json.dumps(m.scope, sort_keys=True)),
            )
            mapper_total += 1

        for ep in res.entry_points:
            cur.execute(
                """INSERT OR REPLACE INTO entry_point
                   (id, pair_id, repo_id, class_fqn, method_name, method_signature,
                    source_schema_ids, target_schema_id, file, line, sha, browse_url,
                    scope_common, scope_country, scope_clearing, scope_product,
                    scope_field_group, edge_count, resolution_percent)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (ep.id, ep.pair_id, ep.repo_id, ep.class_fqn, ep.method_name,
                 ep.method_signature,
                 json.dumps(ep.source_schema_ids, sort_keys=True),
                 ep.target_schema_id, ep.file, ep.line, ep.sha, ep.browse_url,
                 1 if ep.scope.get("common") else 0,
                 ep.scope.get("country"), ep.scope.get("clearing"),
                 ep.scope.get("product"), ep.scope.get("field_group"),
                 edges_per_ep.get(ep.id, 0), None),
            )
            entry_point_total += 1

        for e in res.edges:
            tgt_fid = f"{e.target.schema_id}#{e.target.path}"
            if tgt_fid not in seen_field_ids:
                cur.execute(
                    "INSERT OR IGNORE INTO field VALUES (?, ?, ?, ?, ?)",
                    (tgt_fid, e.target.schema_id, e.target.path, e.target.business_key, None),
                )
                seen_field_ids.add(tgt_fid)
            src_fid = None
            if e.source is not None:
                src_fid = f"{e.source.schema_id}#{e.source.path}"
                if src_fid not in seen_field_ids:
                    cur.execute(
                        "INSERT OR IGNORE INTO field VALUES (?, ?, ?, ?, ?)",
                        (src_fid, e.source.schema_id, e.source.path, e.source.business_key, None),
                    )
                    seen_field_ids.add(src_fid)

            # Populate static_helper_fqn from the trail when the resolver walked
            # into a helper (qualifier or static_call). Lets BAs filter edges by
            # helper FQN directly without joining edge_resolution.
            static_helper_fqn = e.static_helper_fqn
            if not static_helper_fqn:
                for step in reversed(e.trail):
                    if step.kind in ("qualifier", "static_call", "intra_class") and step.helper_fqn:
                        static_helper_fqn = step.helper_fqn
                        break

            eid = e.edge_id(repo_id)
            cur.execute(
                """INSERT OR REPLACE INTO edge
                   (id, pair_id, mapper_id, entry_point_id, source_field_id, target_field_id,
                    kind, expression, static_helper_fqn, format_spec_json,
                    file, line, sha, browse_url)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (eid, e.pair_id, e.mapper_id, e.entry_point_id, src_fid, tgt_fid,
                 e.kind, e.expression, static_helper_fqn,
                 json.dumps(e.format_spec, sort_keys=True) if e.format_spec else None,
                 e.git.file, e.git.line, e.git.sha, e.git.browse_url),
            )
            cur.execute("DELETE FROM edge_resolution WHERE edge_id = ?", (eid,))
            for seq, step in enumerate(e.trail):
                cur.execute(
                    "INSERT INTO edge_resolution VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (eid, seq, step.kind, step.file, step.line, step.snippet, step.helper_fqn),
                )
                # Dedupe helper bodies into the helper table — first non-null wins.
                if (step.helper_fqn and step.helper_body
                        and step.helper_fqn not in seen_helper_fqns):
                    body_sha = hashlib.sha256(step.helper_body.encode("utf-8")).hexdigest()
                    cur.execute(
                        """INSERT OR REPLACE INTO helper
                           (fqn, file, start_line, end_line, signature, body, body_sha256)
                           VALUES (?, ?, ?, ?, ?, ?, ?)""",
                        (step.helper_fqn,
                         step.helper_file or "",
                         step.helper_start_line or 0,
                         step.helper_end_line or 0,
                         step.helper_signature or "",
                         step.helper_body,
                         body_sha),
                    )
                    seen_helper_fqns.add(step.helper_fqn)
            edge_total += 1
        cur.execute(
            """INSERT OR REPLACE INTO coverage
               (repo_id, pair_id, files_scanned, mappers_detected, edges_emitted,
                unparseable_json, unmatched_json, target_field_count, coverage_percent)
               VALUES (?, ?, ?, ?, ?, ?, ?, NULL, NULL)""",
            (repo_id, pair_id, res.files_scanned, len(res.mappers), len(res.edges),
             json.dumps(res.unparseable, sort_keys=True), "[]"),
        )

    # Coverage % — pair-level and per-entry-point. The denominator is the
    # set of leaf paths in every target schema bound to the pair; the
    # numerator is the set of those paths that at least one edge writes.
    # Stored on `coverage` (per repo, pair) and `entry_point.coverage_percent`
    # so a BA can sort or filter by completeness without re-deriving.
    _populate_coverage(cur, cfg, results, business_keys)
    # snapshot
    cur.execute("DELETE FROM snapshot")
    cur.execute(
        "INSERT INTO snapshot VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (atlas_sha, time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
         ATLAS_VERSION, edge_total, mapper_total, len(seen_field_ids), 0,
         json.dumps({"checksum_ok": True}, sort_keys=True)),
    )
    conn.commit()
