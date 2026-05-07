"""Deterministic JSON I/O. Parity with atlas-core-java DeterministicJson."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any


def to_canonical_bytes(value: Any) -> bytes:
    """Serialise to UTF-8 with sorted keys, 2-space indent, LF newlines, trailing newline."""
    s = json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False, separators=(",", ": "))
    if not s.endswith("\n"):
        s += "\n"
    return s.encode("utf-8")


def write_atomic(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(to_canonical_bytes(value))
    os.replace(tmp, path)


def write_text_atomic(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not content.endswith("\n"):
        content += "\n"
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(content.encode("utf-8"))
    os.replace(tmp, path)


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()
