"""Parse `x-atlas-business-key` annotations from JSON Schema and XSD files.

Returns a flat dict {field_path: business_key} per schema file. Path is dotted
against the JSON / XSD field tree.
"""

from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any


def parse(schema_file: Path, kind: str) -> dict[str, str]:
    if not schema_file.is_file():
        return {}
    if kind == "json-schema":
        return _parse_json_schema(schema_file)
    if kind == "xsd":
        return _parse_xsd(schema_file)
    return {}


def _parse_json_schema(file: Path) -> dict[str, str]:
    doc = json.loads(file.read_text(encoding="utf-8"))
    out: dict[str, str] = {}
    _walk_json(doc, "", out)
    return out


def _walk_json(node: Any, path: str, out: dict[str, str]) -> None:
    if not isinstance(node, dict):
        return
    if "x-atlas-business-key" in node and path:
        out[path] = str(node["x-atlas-business-key"])
    props = node.get("properties")
    if isinstance(props, dict):
        for name, sub in props.items():
            sub_path = f"{path}.{name}" if path else name
            _walk_json(sub, sub_path, out)


def _parse_xsd(file: Path) -> dict[str, str]:
    """Best-effort XSD walker. Captures appinfo>business-key on each xs:element.
    Path is the dotted chain of element names rooted at the top-level element.
    """
    XS = "{http://www.w3.org/2001/XMLSchema}"
    BK_RE = re.compile(r"<(?:[A-Za-z0-9_-]+:)?business-key[^>]*>([^<]+)</")

    out: dict[str, str] = {}
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

    def walk_element(el: ET.Element, path: str) -> None:
        # business-key on this element's appinfo
        for ann in el.findall(f"{XS}annotation"):
            for ai in ann.findall(f"{XS}appinfo"):
                txt = ET.tostring(ai, encoding="unicode")
                m = BK_RE.search(txt)
                if m and path:
                    out[path] = m.group(1).strip()
        # walk into the element's complexType (inline or referenced)
        type_attr = el.attrib.get("type", "").split(":")[-1]
        ct: ET.Element | None = el.find(f"{XS}complexType")
        if ct is None and type_attr in types_by_name:
            ct = types_by_name[type_attr]
        if ct is not None:
            for seq in ct.findall(f"{XS}sequence"):
                for child in seq.findall(f"{XS}element"):
                    name = child.attrib.get("name")
                    if not name:
                        continue
                    sub_path = f"{path}.{name}" if path else name
                    walk_element(child, sub_path)

    for top in root.findall(f"{XS}element"):
        name = top.attrib.get("name", "")
        # The conventional Java mapping doesn't include the top-level element
        # in the path (e.g. MT103 wraps field_50K -> path "field_50K", not "MT103.field_50K").
        walk_element(top, "")
    return out
