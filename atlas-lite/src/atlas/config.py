"""atlas.yml loader + JSON-schema validator + auto-detection rules."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import jsonschema
import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator


class SchemaRef(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    name: str
    file: str
    kind: str
    type_fqns: list[str] = Field(default_factory=list)


class Repo(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    id: str
    path: str
    project: str | None = None
    branch: str | None = None


class ScopeRule(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    glob: str | None = None
    filename_pattern: str | None = None
    scope: dict[str, Any] | None = None
    capture: list[str] | None = None


class Pair(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    id: str
    sources: list[SchemaRef] = Field(default_factory=list)
    targets: list[SchemaRef] = Field(default_factory=list)
    scan_globs: list[str]
    scope_rules: list[ScopeRule] = Field(default_factory=list)
    resolvers: ResolverConfig | None = None       # forward ref; defined below
    # Single-form alias kept for spec compatibility (§4); we promote to lists.
    source: SchemaRef | None = None
    target: SchemaRef | None = None

    @field_validator("sources", "targets", mode="before")
    @classmethod
    def _accept_object_or_list(cls, v: Any) -> Any:
        if v is None:
            return []
        if isinstance(v, dict):
            return [v]
        return v

    def effective_sources(self) -> list[SchemaRef]:
        return self.sources or ([self.source] if self.source else [])

    def effective_targets(self) -> list[SchemaRef]:
        return self.targets or ([self.target] if self.target else [])


class Bitbucket(BaseModel):
    model_config = ConfigDict(frozen=True, extra="allow")
    base_url: str | None = None
    api_kind: str | None = None
    auth: dict[str, Any] | None = None
    browse_template: str | None = None


class Storage(BaseModel):
    model_config = ConfigDict(frozen=True, extra="allow")
    db_path: str = "~/.atlas/atlas.db"
    site_path: str = "~/.atlas/site"
    cache_path: str = "~/.atlas/cache"


class SelectorRule(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    class_pattern: str | None = None
    method_pattern: str | None = None
    return_type: str | None = None
    method_fqns: list[str] = Field(default_factory=list)


class ResolverConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    qualifier_classes: list[str] = Field(default_factory=list)
    static_helper_classes: list[str] = Field(default_factory=list)
    max_depth: int = 5
    follow_intra_class: bool = True


class MethodSelector(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    id: str
    description: str | None = None
    selectors: list[SelectorRule]
    target_schema: SchemaRef | None = None
    source_schemas: list[SchemaRef] = Field(default_factory=list)
    resolvers: ResolverConfig = ResolverConfig()
    scope_rules: list[ScopeRule] = Field(default_factory=list)


# Resolve forward reference now that ResolverConfig is defined.
Pair.model_rebuild()


class AtlasConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="allow")
    version: int
    repos: list[Repo]
    pairs: list[Pair] = Field(default_factory=list)
    method_selectors: list[MethodSelector] = Field(default_factory=list)
    bitbucket: Bitbucket | None = None
    schedule: dict[str, Any] | None = None
    storage: Storage = Storage()
    mcp_port: int = 4281
    ui_port: int = 4280
    jira: dict[str, Any] | None = None


def load_config(path: Path, schema_path: Path | None = None) -> AtlasConfig:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    raw = _autodetect(raw, base=path.parent)
    if schema_path is None:
        schema_path = _find_schema(path, "atlas-config.schema.json")
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator(schema).validate(raw)
    return AtlasConfig.model_validate(raw)


def _find_schema(start: Path, name: str) -> Path:
    p = start.resolve().parent
    while p != p.parent:
        candidate = p / "schemas" / name
        if candidate.is_file():
            return candidate
        p = p.parent
    raise FileNotFoundError(f"could not locate schemas/{name}")


def _autodetect(raw: dict[str, Any], base: Path) -> dict[str, Any]:
    """Fill in deterministic defaults for omitted fields. Writes its decisions to stderr."""
    repos = raw.get("repos", [])
    for repo in repos:
        if "path" not in repo or not repo["path"]:
            for root in (Path.home() / "work", Path.home() / "dev", Path.cwd()):
                cand = root / repo["id"]
                if cand.is_dir():
                    repo["path"] = str(cand)
                    print(f"[atlas-config] autodetected repos[{repo['id']}].path = {cand}", file=sys.stderr)
                    break
        # Resolve ~/ in paths
        repo["path"] = os.path.expanduser(repo["path"]) if "path" in repo else repo.get("path")

        if not repo.get("project"):
            git_cfg = Path(repo["path"]) / ".git" / "config" if "path" in repo else None
            if git_cfg and git_cfg.exists():
                m = re.search(r"\[remote \"origin\"\]\s*\n[^\[]*url\s*=\s*([^\n]+)", git_cfg.read_text())
                if m:
                    url = m.group(1).strip()
                    parts = re.split(r"[:/]", url.rstrip(".git"))
                    if len(parts) >= 2:
                        repo["project"] = parts[-2]
                        print(f"[atlas-config] autodetected repos[{repo['id']}].project = {repo['project']}", file=sys.stderr)

        if not repo.get("branch") and repo.get("path"):
            try:
                out = subprocess.run(
                    ["git", "-C", repo["path"], "symbolic-ref", "--short", "refs/remotes/origin/HEAD"],
                    capture_output=True, text=True, timeout=5,
                )
                if out.returncode == 0:
                    repo["branch"] = out.stdout.strip().split("/")[-1] or "main"
            except Exception:
                pass
            if not repo.get("branch"):
                repo["branch"] = "main"

    return raw
