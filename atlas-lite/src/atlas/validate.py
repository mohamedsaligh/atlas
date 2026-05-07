"""Atom-grep validator. Every atom in agent/UI output must appear in the
captured MCP transcript; otherwise it's a fabrication.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

ATOM_PATTERNS = {
    "edge_id":     re.compile(r"\b[a-z0-9-]+\.[a-z0-9_-]+\.e_[0-9a-f]{12}\b"),
    "mapper_fqn":  re.compile(r"\b(?:[a-z][a-z0-9_]*\.)+[A-Z][A-Za-z0-9_]+\b"),
    "file_path":   re.compile(r"\b(?:[\w-]+/)+[\w.-]+\.(?:java|json|xsd|yaml|md)\b"),
    "url":         re.compile(r"\bhttps?://\S+\b"),
    "sha":         re.compile(r"\b[0-9a-f]{7,40}\b"),
    "field_path":  re.compile(r"`([a-zA-Z_][\w.]*)`"),
}


@dataclass
class ValidationResult:
    ok: bool
    unverifiable: list[dict]


def collect_seen(transcript: list[dict]) -> dict[str, set[str]]:
    seen = {k: set() for k in ATOM_PATTERNS}
    for call in transcript:
        text = json.dumps(call.get("response", ""), default=str)
        for kind, pat in ATOM_PATTERNS.items():
            for m in pat.finditer(text):
                seen[kind].add(m.group(0) if kind != "field_path" else m.group(1))
    return seen


def validate(draft: str, transcript: list[dict]) -> ValidationResult:
    seen = collect_seen(transcript)
    unverifiable = []
    for kind, pat in ATOM_PATTERNS.items():
        for m in pat.finditer(draft):
            atom = m.group(0) if kind != "field_path" else m.group(1)
            if atom not in seen[kind]:
                unverifiable.append({"atom": atom, "kind": kind, "offset": m.start()})
    return ValidationResult(ok=not unverifiable, unverifiable=unverifiable)
