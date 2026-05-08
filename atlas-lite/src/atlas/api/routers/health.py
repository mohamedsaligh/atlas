"""Health and snapshot identity endpoints."""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends

from ..deps import get_db
from ..models import HealthResponse

router = APIRouter(tags=["health"])


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Liveness + snapshot identity probe",
)
def health(conn: sqlite3.Connection = Depends(get_db)) -> HealthResponse:
    row = conn.execute(
        "SELECT atlas_sha, extractor_ver, built_at FROM snapshot LIMIT 1"
    ).fetchone()
    if row is None:
        return HealthResponse(status="ok")
    return HealthResponse(
        status="ok",
        atlas_sha=row["atlas_sha"],
        extractor_version=row["extractor_ver"],
        snapshot_built_at=row["built_at"],
    )
