"""Snapshot detail endpoint — exposes the loaded SQLite metadata."""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, HTTPException, status

from ..deps import get_db
from ..models import SnapshotInfo

router = APIRouter(tags=["snapshot"])


@router.get(
    "/snapshot",
    response_model=SnapshotInfo,
    summary="The currently-loaded SQLite snapshot",
)
def snapshot(conn: sqlite3.Connection = Depends(get_db)) -> SnapshotInfo:
    row = conn.execute(
        """SELECT atlas_sha, built_at, extractor_ver, edge_count,
                  mapper_count, field_count, test_count
           FROM snapshot LIMIT 1"""
    ).fetchone()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="snapshot table is empty — run `atlas extract` first",
        )
    return SnapshotInfo(
        atlas_sha=row["atlas_sha"],
        built_at=row["built_at"],
        extractor_version=row["extractor_ver"],
        edge_count=row["edge_count"],
        mapper_count=row["mapper_count"],
        field_count=row["field_count"],
        test_count=row["test_count"],
    )
