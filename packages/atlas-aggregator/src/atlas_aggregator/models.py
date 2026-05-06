"""Pydantic v2 models mirroring schemas/manifest.schema.json + edge.schema.json.

Models are frozen for determinism (no in-place mutation after construction).
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

EdgeKind = Literal[
    "field_copy",
    "format",
    "expression",
    "constant",
    "static_call",
    "enrichment",
    "conditional",
    "collection_map",
    "unmapped",
    "intra_domain",
    "opaque_copy",
]


class FieldRef(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    type: str
    path: str
    schemaFile: str
    businessKey: str | None = None


class GitRef(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    repo: str
    sha: str
    file: str
    line: int
    browseUrl: str | None = None
    blobSha: str | None = None


class Edge(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    edgeId: str
    mapperId: str
    mapperKind: str
    kind: EdgeKind
    source: FieldRef | None = None
    target: FieldRef
    expression: str | None = None
    staticHelperFqn: str | None = None
    cardinality: str | None = None
    branchCondition: str | None = None
    formatSpec: dict[str, Any] | None = None
    scope: dict[str, Any] | None = None
    git: GitRef
    testIds: list[str] = Field(default_factory=list)
    confidence: Literal["high", "medium", "low"]


class ExtractorEntry(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    version: str
    options: dict[str, Any] | None = None


class ManifestSchemaRef(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    schemaFile: str
    schemaKind: Literal["xsd", "json-schema", "proto", "fixedlen", "tagged"]


class ManifestGit(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    repo: str
    sha: str
    branch: str


class Stats(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    filesScanned: int = 0
    mappersDetected: int = 0
    edgesEmitted: int = 0
    byKind: dict[str, int] = Field(default_factory=dict)
    byMapperKind: dict[str, int] = Field(default_factory=dict)


class Manifest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    atlasVersion: str
    schemaVersion: int
    projectId: str
    repoId: str
    pairId: str
    git: ManifestGit
    source: ManifestSchemaRef
    target: ManifestSchemaRef
    extractors: list[ExtractorEntry]
    edges: list[Edge]
    stats: Stats | None = None
    checksum: str
