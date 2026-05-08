"""Impact-analysis row model — one per affected target field."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from .common import Scope


class ImpactRow(BaseModel):
    """One affected (target field, mapper, entry-point) for a given
    source field change. The reverse-edge BFS produces a sequence of
    these grouped by scope on the rendering side."""
    model_config = ConfigDict(frozen=True)

    entry_point_id: str | None = None
    class_fqn: str | None = None
    method_name: str | None = None
    scope: Scope
    edge_id: str
    kind: str
    helper: str | None = None
    source_schema_id: str
    source_path: str
    target_schema_id: str
    target_path: str
    line: int
    browse_url: str | None = None
