"""Edge + resolution-trail response models."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class ResolutionStep(BaseModel):
    """One hop the resolver walked: setter site, wrapper-arg, qualifier
    body, static helper body, or intra-class helper body."""
    model_config = ConfigDict(frozen=True)

    seq: int
    kind: str
    file: str
    line: int
    snippet: str
    helper_fqn: str | None = None


class EdgeRow(BaseModel):
    """Compact edge row. Source / target paths are surfaced as strings
    rather than field IDs because BAs care about paths, not the
    internal schema-id#path concatenation."""
    model_config = ConfigDict(frozen=True)

    id: str
    pair_id: str
    mapper_id: str
    entry_point_id: str | None = None
    kind: str
    expression: str
    source_schema_id: str | None = None
    source_path: str | None = None
    target_schema_id: str
    target_path: str
    static_helper_fqn: str | None = None
    file: str
    line: int
    browse_url: str | None = None


class EdgeWithResolution(EdgeRow):
    """Edge plus its full resolution trail. Use for audit / detail views."""
    trail: list[ResolutionStep]
