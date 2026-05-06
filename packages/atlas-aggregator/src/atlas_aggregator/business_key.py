"""Parse JSON Schema and XSD files, returning per-field metadata.

`enumerate_fields` returns a flat dict `{path: FieldAttrs}` for every leaf
field in the schema, with optional `business_key` and `ignored` flags.

`parse` is a back-compat shortcut returning only `{path: business_key}` for
fields that have one.
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


def parse(schema_file: Path, kind: str) -> dict[str, str]:
    """Back-compat: flat path → business_key for fields that have one."""
    fields = enumerate_fields(schema_file, kind)
    return {p: a.business_key for p, a in fields.items() if a.business_key is not None}


def enumerate_fields(schema_file: Path, kind: str) -> dict[str, FieldAttrs]:
    """Every leaf field path with its attrs (business_key, ignored)."""
    if not schema_file.is_file():
        return {}
    if kind == "json-schema":
        return _enum_json_schema(schema_file)
    if kind == "xsd":
        return _enum_xsd(schema_file)
    return {}


def _enum_json_schema(file: Path) -> dict[str, FieldAttrs]:
    try:
        doc = json.loads(file.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return {}
    out: dict[str, FieldAttrs] = {}
    _walk_json_full(doc, "", out)
    return out


def _walk_json_full(node: Any, path: str, out: dict[str, FieldAttrs]) -> None:
    if not isinstance(node, dict):
        return
    props = node.get("properties")
    if isinstance(props, dict) and props:
        # Inner node — recurse, but ALSO honor x-atlas-business-key on the inner node itself.
        if path and ("x-atlas-business-key" in node or node.get("x-atlas-ignore")):
            out[path] = FieldAttrs(
                business_key=str(node["x-atlas-business-key"]) if "x-atlas-business-key" in node else None,
                ignored=bool(node.get("x-atlas-ignore", False)),
            )
        for name, sub in props.items():
            sub_path = f"{path}.{name}" if path else name
            _walk_json_full(sub, sub_path, out)
        return
    if path:
        out[path] = FieldAttrs(
            business_key=str(node["x-atlas-business-key"]) if "x-atlas-business-key" in node else None,
            ignored=bool(node.get("x-atlas-ignore", False)),
        )


def _enum_xsd(file: Path) -> dict[str, FieldAttrs]:
    """Best-effort XSD walker. Captures appinfo>business-key and appinfo>ignore on each xs:element."""
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

    def attrs_from_appinfo(el: ET.Element) -> tuple[str | None, bool]:
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

    def walk_element(el: ET.Element, path: str) -> None:
        bk, ignored = attrs_from_appinfo(el)
        type_attr = el.attrib.get("type", "").split(":")[-1]
        ct: ET.Element | None = el.find(f"{XS}complexType")
        if ct is None and type_attr in types_by_name:
            ct = types_by_name[type_attr]
        if ct is not None:
            # Inner node — record only if it has annotations; recurse into children.
            if path and (bk is not None or ignored):
                out[path] = FieldAttrs(business_key=bk, ignored=ignored)
            for seq in ct.findall(f"{XS}sequence"):
                for child in seq.findall(f"{XS}element"):
                    name = child.attrib.get("name")
                    if not name:
                        continue
                    sub_path = f"{path}.{name}" if path else name
                    walk_element(child, sub_path)
        elif path:
            # Leaf — always record, even if no annotations.
            out[path] = FieldAttrs(business_key=bk, ignored=ignored)

    for top in root.findall(f"{XS}element"):
        # The conventional Java mapping doesn't include the top-level element
        # in the path (e.g. MT103 wraps field_50K -> path "field_50K", not "MT103.field_50K").
        walk_element(top, "")
    return out
