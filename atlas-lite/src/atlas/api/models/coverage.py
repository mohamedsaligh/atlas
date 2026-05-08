"""Coverage row — one per (repo, pair)."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class CoverageRow(BaseModel):
    """Pair-level coverage. Mirrors the ``coverage`` SQLite table."""
    model_config = ConfigDict(frozen=True)

    repo_id: str
    pair_id: str
    target_field_count: int | None = None
    coverage_percent: float | None = None
    edges_emitted: int
    files_scanned: int
    mappers_detected: int
    unmatched: list[str]
