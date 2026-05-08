"""Snapshot + health response models."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class HealthResponse(BaseModel):
    """Liveness + snapshot identity probe.

    Surfaces enough state to be useful as a smoke check — clients can
    compare ``atlas_sha`` across deployments to detect drift.
    """
    model_config = ConfigDict(frozen=True)

    status: str
    atlas_sha: str | None = None
    extractor_version: str | None = None
    snapshot_built_at: str | None = None


class SnapshotInfo(BaseModel):
    """Single-row summary of the loaded SQLite snapshot."""
    model_config = ConfigDict(frozen=True)

    atlas_sha: str
    built_at: str
    extractor_version: str
    edge_count: int
    mapper_count: int
    field_count: int
    test_count: int
