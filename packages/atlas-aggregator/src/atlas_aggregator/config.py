"""Loader + jsonschema validator for atlas.yml."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import jsonschema
import yaml
from pydantic import BaseModel, ConfigDict


class SchemaRef(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    name: str
    schema_file: str
    schema_kind: str


class ScopeRule(BaseModel):
    model_config = ConfigDict(frozen=True, extra="allow")
    pattern: str
    scope: dict[str, Any] | None = None
    capture: list[str] | None = None


class ExtractorSpec(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    type: str
    options: dict[str, Any] | None = None


class DomainPair(BaseModel):
    model_config = ConfigDict(frozen=True, extra="allow")
    id: str
    source: SchemaRef
    target: SchemaRef
    scan_packages: list[str]
    scope_inference: dict[str, Any] | None = None
    extractors: list[ExtractorSpec] | None = None


class Repo(BaseModel):
    model_config = ConfigDict(frozen=True, extra="allow")
    id: str
    path: str
    bitbucket: dict[str, Any] | None = None
    branches: dict[str, Any] | None = None


class Project(BaseModel):
    model_config = ConfigDict(frozen=True, extra="allow")
    id: str
    description: str | None = None
    repos: list[Repo]
    domain_pairs: list[DomainPair]


class Storage(BaseModel):
    model_config = ConfigDict(frozen=True, extra="allow")
    atlas_kb_path: str | None = None
    atlas_kb_repo: str | None = None
    local_cache: str | None = None
    sqlite_path: str | None = None


class AtlasConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="allow")
    version: int
    projects: list[Project]
    storage: Storage | None = None


def load_config(path: Path, schema_path: Path | None = None) -> AtlasConfig:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if schema_path is None:
        schema_path = _find_schema(path, "atlas-config.schema.json")
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator(schema).validate(raw)
    return AtlasConfig.model_validate(raw)


def _find_schema(start: Path, name: str) -> Path:
    p = start.parent
    while p != p.parent:
        candidate = p / "schemas" / name
        if candidate.is_file():
            return candidate
        p = p.parent
    raise FileNotFoundError(f"could not locate schemas/{name} starting from {start}")
