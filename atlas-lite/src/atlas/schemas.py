"""Schema parsers: enumerate every leaf field with its business_key + ignored flag.

Three kinds supported:
  - json-schema   (with optional `x-atlas-business-key` and `x-atlas-ignore`)
  - xsd           (with <xs:appinfo><atlas:business-key> and <atlas:ignore>)
  - java-class    (regex walker over Java domain class trees)

Returns a flat dict {dotted_path: FieldAttrs}. Lessons applied from atlas-java:
  - JSON walker honours nested `properties` and skips method internals.
  - XSD walker resolves named complexTypes referenced by `type=`.
  - Java walker requires a visibility modifier on field declarations to avoid
    matching method-body identifiers, and recurses through inner static classes
    + sibling source-tree references.
"""

from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class FieldAttrs:
    business_key: str | None = None
    ignored: bool = False
    type_hint: str | None = None


def enumerate_fields(schema_file: Path, kind: str) -> dict[str, FieldAttrs]:
    if not schema_file.is_file():
        return {}
    if kind == "json-schema":
        return _enum_json_schema(schema_file)
    if kind == "xsd":
        return _enum_xsd(schema_file)
    if kind == "java-class":
        return _enum_java_class(schema_file)
    return {}


# ── json-schema ──────────────────────────────────────────────────────────────


def _enum_json_schema(file: Path) -> dict[str, FieldAttrs]:
    try:
        doc = json.loads(file.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return {}
    out: dict[str, FieldAttrs] = {}
    _walk_json(doc, "", out)
    return out


def _walk_json(node: Any, path: str, out: dict[str, FieldAttrs]) -> None:
    if not isinstance(node, dict):
        return
    props = node.get("properties")
    if isinstance(props, dict) and props:
        if path and ("x-atlas-business-key" in node or node.get("x-atlas-ignore")):
            out[path] = FieldAttrs(
                business_key=str(node["x-atlas-business-key"])
                if "x-atlas-business-key" in node
                else None,
                ignored=bool(node.get("x-atlas-ignore", False)),
                type_hint=node.get("type"),
            )
        for name, sub in props.items():
            sub_path = f"{path}.{name}" if path else name
            _walk_json(sub, sub_path, out)
        return
    if path:
        out[path] = FieldAttrs(
            business_key=str(node["x-atlas-business-key"])
            if "x-atlas-business-key" in node
            else None,
            ignored=bool(node.get("x-atlas-ignore", False)),
            type_hint=node.get("type"),
        )


# ── xsd ──────────────────────────────────────────────────────────────────────


def _enum_xsd(file: Path) -> dict[str, FieldAttrs]:
    XS = "{http://www.w3.org/2001/XMLSchema}"
    BK_RE = re.compile(r"<(?:[A-Za-z0-9_-]+:)?business-key[^>]*>([^<]+)</")
    IGNORE_RE = re.compile(r"<(?:[A-Za-z0-9_-]+:)?ignore[^>]*>\s*(true|1)\s*</")

    out: dict[str, FieldAttrs] = {}
    try:
        tree = ET.parse(file)
    except ET.ParseError:
        return {}
    root = tree.getroot()

    types_by_name: dict[str, ET.Element] = {}
    for ct in root.findall(f"{XS}complexType"):
        name = ct.attrib.get("name")
        if name:
            types_by_name[name] = ct

    def attrs(el: ET.Element) -> tuple[str | None, bool]:
        bk: str | None = None
        ignored = False
        for ann in el.findall(f"{XS}annotation"):
            for ai in ann.findall(f"{XS}appinfo"):
                txt = ET.tostring(ai, encoding="unicode")
                m = BK_RE.search(txt)
                if m:
                    bk = m.group(1).strip()
                if IGNORE_RE.search(txt):
                    ignored = True
        return bk, ignored

    def walk(el: ET.Element, path: str) -> None:
        bk, ignored = attrs(el)
        type_attr = el.attrib.get("type", "").split(":")[-1]
        ct: ET.Element | None = el.find(f"{XS}complexType")
        if ct is None and type_attr in types_by_name:
            ct = types_by_name[type_attr]
        if ct is not None:
            if path and (bk or ignored):
                out[path] = FieldAttrs(business_key=bk, ignored=ignored)
            for seq in ct.findall(f"{XS}sequence"):
                for child in seq.findall(f"{XS}element"):
                    name = child.attrib.get("name")
                    if not name:
                        continue
                    sub_path = f"{path}.{name}" if path else name
                    walk(child, sub_path)
        elif path:
            out[path] = FieldAttrs(business_key=bk, ignored=ignored)

    for top in root.findall(f"{XS}element"):
        walk(top, "")
    return out


# ── java-class ───────────────────────────────────────────────────────────────

_LEAF_PREFIXES = (
    "java.",
    "Boolean",
    "Byte",
    "Character",
    "Short",
    "Integer",
    "Long",
    "Float",
    "Double",
    "String",
    "Object",
    "Number",
    "BigDecimal",
    "BigInteger",
    "LocalDate",
    "LocalDateTime",
    "LocalTime",
    "Date",
    "Instant",
    "OffsetDateTime",
    "ZonedDateTime",
    "Duration",
    "Period",
    "UUID",
)
_PRIMITIVES = {"boolean", "byte", "char", "short", "int", "long", "float", "double", "void"}

_FIELD_RE = re.compile(
    r"(?ms)"
    r"((?:@\w+(?:\([^)]*\))?\s+)*)"
    r"(?:public|private|protected)\s+"
    r"(?:(?:static|final|volatile|transient)\s+)*"
    r"([\w.<>,\s\[\]?]+?)\s+"
    r"(\w+)\s*[;=]"
)
_BK_ANNO_RE = re.compile(r'@AtlasField\s*\(\s*businessKey\s*=\s*"([^"]+)"')
_IGNORE_ANNO_RE = re.compile(r"@AtlasIgnore\b")


def _enum_java_class(file: Path) -> dict[str, FieldAttrs]:
    out: dict[str, FieldAttrs] = {}
    src_root = _find_java_source_root(file)
    file_index = _index_java_files(src_root) if src_root else {file.stem: file}
    try:
        text = file.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return out
    root_class = _root_class_name(text) or file.stem
    body = _extract_class_block(text, root_class)
    if body is None:
        return out
    _walk_java(body, file, "", file_index, out, set())
    return out


def _find_java_source_root(file: Path) -> Path | None:
    p = file.parent
    while p != p.parent:
        if p.name == "java" and p.parent.name == "main" and p.parent.parent.name == "src":
            return p
        p = p.parent
    return None


def _index_java_files(root: Path) -> dict[str, Path]:
    return {f.stem: f for f in root.rglob("*.java") if f.is_file()}


def _root_class_name(text: str) -> str | None:
    m = re.search(r"(?:public\s+|abstract\s+|final\s+)*class\s+(\w+)\b", text)
    return m.group(1) if m else None


def _extract_class_block(text: str, class_name: str) -> str | None:
    m = re.search(
        r"(?:public\s+|private\s+|protected\s+|static\s+|final\s+|abstract\s+)*"
        r"class\s+" + re.escape(class_name) + r"\b[^{]*\{",
        text,
    )
    if not m:
        return None
    start = m.end()
    depth = 1
    i = start
    while i < len(text) and depth > 0:
        c = text[i]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
        i += 1
    return text[start : i - 1] if depth == 0 else None


def _strip_inner_classes(body: str) -> str:
    out_chars = list(body)
    inner_re = re.compile(
        r"(?:public\s+|private\s+|protected\s+|static\s+|final\s+|abstract\s+)*class\s+\w+\b[^{]*\{"
    )
    for m in inner_re.finditer(body):
        start = m.end()
        depth = 1
        i = start
        while i < len(body) and depth > 0:
            c = body[i]
            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
            i += 1
        for k in range(start, i - 1):
            if out_chars[k] != "\n":
                out_chars[k] = " "
    return "".join(out_chars)


def _is_leaf_type(t: str) -> bool:
    base = t.strip().split("<")[0].strip()
    if base in _PRIMITIVES:
        return True
    if any(base.startswith(p) for p in _LEAF_PREFIXES):
        return True
    if base.endswith("[]"):
        return True
    return False


def _walk_java(
    body: str,
    file: Path,
    prefix: str,
    file_index: dict[str, Path],
    out: dict[str, FieldAttrs],
    seen: set[Path],
) -> None:
    shallow = _strip_inner_classes(body)

    for m in _FIELD_RE.finditer(shallow):
        anno_block, type_name, field_name = m.group(1) or "", m.group(2).strip(), m.group(3)
        if "(" in type_name:
            continue
        bk_m = _BK_ANNO_RE.search(anno_block)
        ignored = bool(_IGNORE_ANNO_RE.search(anno_block))
        type_simple = type_name.split(".")[-1].split("<")[0].strip()
        path = f"{prefix}.{field_name}" if prefix else field_name

        if _is_leaf_type(type_name):
            out[path] = FieldAttrs(
                business_key=bk_m.group(1) if bk_m else None,
                ignored=ignored,
                type_hint=type_name,
            )
            continue

        inner_body = _extract_class_block(body, type_simple)
        if inner_body is not None:
            if bk_m or ignored:
                out[path] = FieldAttrs(
                    business_key=bk_m.group(1) if bk_m else None,
                    ignored=ignored,
                )
            _walk_java(inner_body, file, path, file_index, out, seen)
            continue

        sibling = file_index.get(type_simple)
        if sibling and sibling != file and sibling not in seen:
            seen.add(sibling)
            try:
                sibling_text = sibling.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            sibling_block = _extract_class_block(sibling_text, type_simple)
            if sibling_block is not None:
                if bk_m or ignored:
                    out[path] = FieldAttrs(
                        business_key=bk_m.group(1) if bk_m else None,
                        ignored=ignored,
                    )
                _walk_java(sibling_block, sibling, path, file_index, out, seen)
                continue

        out[path] = FieldAttrs(
            business_key=bk_m.group(1) if bk_m else None,
            ignored=ignored,
            type_hint=type_name,
        )
