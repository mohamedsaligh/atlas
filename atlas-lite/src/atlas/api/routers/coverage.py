"""Pair-level coverage endpoint."""

from __future__ import annotations

import json
import sqlite3

from fastapi import APIRouter, Depends, Query

from ..deps import get_db
from ..models import CoverageRow, Page

router = APIRouter(tags=["coverage"])


@router.get(
    "/coverage",
    response_model=Page[CoverageRow],
    summary="Pair-level coverage rows, sorted lowest first",
)
def list_coverage(
    repo: str | None = Query(None, description="Restrict to a single repo_id"),
    pair: str | None = Query(None, description="Restrict to a single pair_id"),
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=500),
    conn: sqlite3.Connection = Depends(get_db),
) -> Page[CoverageRow]:
    where: list[str] = []
    args: list[object] = []
    if repo:
        where.append("repo_id = ?")
        args.append(repo)
    if pair:
        where.append("pair_id = ?")
        args.append(pair)
    where_sql = ("WHERE " + " AND ".join(where)) if where else ""

    total = conn.execute(f"SELECT COUNT(*) AS n FROM coverage {where_sql}", args).fetchone()["n"]

    rows = conn.execute(
        f"""SELECT repo_id, pair_id, target_field_count, coverage_percent,
                   edges_emitted, files_scanned, mappers_detected, unmatched_json
            FROM coverage {where_sql}
            ORDER BY coverage_percent IS NULL, coverage_percent ASC,
                     repo_id, pair_id
            LIMIT ? OFFSET ?""",
        [*args, size, (page - 1) * size],
    ).fetchall()
    items = [
        CoverageRow(
            repo_id=r["repo_id"],
            pair_id=r["pair_id"],
            target_field_count=r["target_field_count"],
            coverage_percent=r["coverage_percent"],
            edges_emitted=r["edges_emitted"],
            files_scanned=r["files_scanned"],
            mappers_detected=r["mappers_detected"],
            unmatched=json.loads(r["unmatched_json"] or "[]"),
        )
        for r in rows
    ]
    return Page[CoverageRow](items=items, page=page, size=size, total=total)
