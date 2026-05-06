"""Discover, validate, and load manifest files."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import jsonschema

from .config import AtlasConfig
from .models import Manifest


def find_schema(start: Path, name: str) -> Path:
    p = start
    while p != p.parent:
        candidate = p / "schemas" / name
        if candidate.is_file():
            return candidate
        p = p.parent
    raise FileNotFoundError(f"could not locate schemas/{name}")


def collect_manifests(
    cfg: AtlasConfig,
    config_dir: Path,
    schemas_dir: Path | None = None,
) -> list[Manifest]:
    schemas_dir = schemas_dir or find_schema(config_dir, "manifest.schema.json").parent
    manifest_schema = json.loads((schemas_dir / "manifest.schema.json").read_text(encoding="utf-8"))
    edge_schema = json.loads((schemas_dir / "edge.schema.json").read_text(encoding="utf-8"))
    store: dict[str, dict] = {
        edge_schema["$id"]: edge_schema,
        manifest_schema["$id"]: manifest_schema,
    }
    resolver = jsonschema.RefResolver.from_schema(manifest_schema, store=store)
    validator = jsonschema.Draft202012Validator(manifest_schema, resolver=resolver)

    manifests: list[Manifest] = []
    for project in cfg.projects:
        for repo in project.repos:
            repo_root = (config_dir / repo.path).resolve()
            for pair in project.domain_pairs:
                manifest_path = repo_root / "target" / "atlas" / "manifests" / f"{pair.id}.manifest.json"
                if not manifest_path.is_file():
                    continue
                raw = json.loads(manifest_path.read_text(encoding="utf-8"))
                validator.validate(raw)
                _verify_checksum(raw)
                manifests.append(Manifest.model_validate(raw))
    return manifests


def _verify_checksum(raw: dict) -> None:
    stored = raw.get("checksum", "")
    blanked = dict(raw)
    blanked["checksum"] = ""
    canonical = json.dumps(
        blanked, sort_keys=True, indent=2, ensure_ascii=False, separators=(",", ": ")
    )
    if not canonical.endswith("\n"):
        canonical += "\n"
    actual = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    if actual != stored:
        raise ValueError(
            f"manifest checksum mismatch: stored={stored} computed={actual}\n"
            f"(determinism rules: sorted_keys=True, indent=2, ensure_ascii=False, LF + trailing newline)"
        )
