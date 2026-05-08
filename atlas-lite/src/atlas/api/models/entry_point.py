"""Entry-point response models — the BA-facing transformation unit."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from .common import Scope
from .edge import EdgeRow
from .helper import HelperBody


class EntryPointSummary(BaseModel):
    """Compact entry-point row for paginated lists."""

    model_config = ConfigDict(frozen=True)

    id: str
    pair_id: str
    repo_id: str
    class_fqn: str
    method_name: str
    method_signature: str
    source_schema_ids: list[str]
    target_schema_id: str
    file: str
    line: int
    sha: str
    browse_url: str | None = None
    scope: Scope
    edge_count: int
    resolution_percent: float | None = Field(
        default=None,
        description=(
            "Fraction of this entry-point's edges that resolved to a real "
            "source schema path. Distinct from pair-level coverage_percent."
        ),
    )


class EntryPointDetail(EntryPointSummary):
    """Full entry-point payload — includes edges + every helper body the
    resolver walked through. Inline helper bodies are how a Business
    Analyst reads the actual transformation logic without leaving the
    response."""

    edges: list[EdgeRow]
    helpers: list[HelperBody]
