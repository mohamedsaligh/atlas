"""Entry-point list + detail. The BA-facing resource."""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status

from ..deps import get_db
from ..models import (
    EdgeRow,
    EntryPointDetail,
    EntryPointSummary,
    HelperBody,
    Page,
    Scope,
)

router = APIRouter(tags=["entry-points"])


# ─────────────────────────────────────────────────────────────────────────────
# List
# ─────────────────────────────────────────────────────────────────────────────


@router.get(
    "/entry-points",
    response_model=Page[EntryPointSummary],
    summary="List entry points filtered by scope",
)
def list_entry_points(
    repo: str | None = Query(None),
    pair: str | None = Query(None),
    country: str | None = Query(None),
    clearing: str | None = Query(None),
    product: str | None = Query(None),
    class_fqn: str | None = Query(None),
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=500),
    conn: sqlite3.Connection = Depends(get_db),
) -> Page[EntryPointSummary]:
    where: list[str] = []
    args: list[object] = []
    if repo:
        where.append("repo_id = ?")
        args.append(repo)
    if pair:
        where.append("pair_id = ?")
        args.append(pair)
    if country:
        where.append("scope_country = ?")
        args.append(country)
    if clearing:
        where.append("scope_clearing = ?")
        args.append(clearing)
    if product:
        where.append("scope_product = ?")
        args.append(product)
    if class_fqn:
        where.append("class_fqn = ?")
        args.append(class_fqn)
    where_sql = ("WHERE " + " AND ".join(where)) if where else ""

    total = conn.execute(f"SELECT COUNT(*) AS n FROM entry_point {where_sql}", args).fetchone()["n"]

    rows = conn.execute(
        f"""SELECT id, pair_id, repo_id, class_fqn, method_name, method_signature,
                   source_schema_ids, target_schema_id, file, line, sha, browse_url,
                   scope_common, scope_country, scope_clearing, scope_product,
                   scope_field_group, edge_count, resolution_percent
            FROM entry_point {where_sql}
            ORDER BY repo_id, pair_id, class_fqn, method_name, id
            LIMIT ? OFFSET ?""",
        [*args, size, (page - 1) * size],
    ).fetchall()
    items = [_to_summary(r) for r in rows]
    return Page[EntryPointSummary](items=items, page=page, size=size, total=total)


# ─────────────────────────────────────────────────────────────────────────────
# Detail (with edges + helpers)
# ─────────────────────────────────────────────────────────────────────────────


@router.get(
    "/entry-points/{entry_point_id}",
    response_model=EntryPointDetail,
    summary="Entry-point detail with its edges and inlined helper bodies",
)
def get_entry_point(
    entry_point_id: str,
    conn: sqlite3.Connection = Depends(get_db),
) -> EntryPointDetail:
    row = conn.execute(
        """SELECT id, pair_id, repo_id, class_fqn, method_name, method_signature,
                  source_schema_ids, target_schema_id, file, line, sha, browse_url,
                  scope_common, scope_country, scope_clearing, scope_product,
                  scope_field_group, edge_count, resolution_percent
           FROM entry_point WHERE id = ?""",
        (entry_point_id,),
    ).fetchone()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"entry_point {entry_point_id} not found",
        )

    summary = _to_summary(row)

    edges_rows = conn.execute(
        """SELECT e.id, e.pair_id, e.mapper_id, e.entry_point_id, e.kind,
                  e.expression, e.static_helper_fqn, e.file, e.line, e.browse_url,
                  sf.schema_id AS source_schema_id, sf.path AS source_path,
                  tf.schema_id AS target_schema_id, tf.path AS target_path
           FROM edge e
           LEFT JOIN field sf ON e.source_field_id = sf.id
           LEFT JOIN field tf ON e.target_field_id = tf.id
           WHERE e.entry_point_id = ?
           ORDER BY e.line, e.id""",
        (entry_point_id,),
    ).fetchall()
    edges = [_edge(r) for r in edges_rows]

    edge_ids = [e.id for e in edges]
    helpers = _load_helpers(conn, edge_ids) if edge_ids else []

    return EntryPointDetail(
        **summary.model_dump(),
        edges=edges,
        helpers=helpers,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Edges paginated (for very large entry points)
# ─────────────────────────────────────────────────────────────────────────────


@router.get(
    "/entry-points/{entry_point_id}/edges",
    response_model=Page[EdgeRow],
    summary="Paginated edges for one entry point",
)
def list_entry_point_edges(
    entry_point_id: str,
    page: int = Query(1, ge=1),
    size: int = Query(100, ge=1, le=1000),
    conn: sqlite3.Connection = Depends(get_db),
) -> Page[EdgeRow]:
    total = conn.execute(
        "SELECT COUNT(*) AS n FROM edge WHERE entry_point_id = ?",
        (entry_point_id,),
    ).fetchone()["n"]
    rows = conn.execute(
        """SELECT e.id, e.pair_id, e.mapper_id, e.entry_point_id, e.kind,
                  e.expression, e.static_helper_fqn, e.file, e.line, e.browse_url,
                  sf.schema_id AS source_schema_id, sf.path AS source_path,
                  tf.schema_id AS target_schema_id, tf.path AS target_path
           FROM edge e
           LEFT JOIN field sf ON e.source_field_id = sf.id
           LEFT JOIN field tf ON e.target_field_id = tf.id
           WHERE e.entry_point_id = ?
           ORDER BY e.line, e.id
           LIMIT ? OFFSET ?""",
        (entry_point_id, size, (page - 1) * size),
    ).fetchall()
    items = [_edge(r) for r in rows]
    return Page[EdgeRow](items=items, page=page, size=size, total=total)


# ─────────────────────────────────────────────────────────────────────────────
# Internal mappers
# ─────────────────────────────────────────────────────────────────────────────


def _to_summary(r: sqlite3.Row) -> EntryPointSummary:
    return EntryPointSummary(
        id=r["id"],
        pair_id=r["pair_id"],
        repo_id=r["repo_id"],
        class_fqn=r["class_fqn"],
        method_name=r["method_name"],
        method_signature=r["method_signature"],
        source_schema_ids=json.loads(r["source_schema_ids"]),
        target_schema_id=r["target_schema_id"],
        file=r["file"],
        line=r["line"],
        sha=r["sha"],
        browse_url=r["browse_url"] or None,
        scope=Scope(
            common=bool(r["scope_common"]),
            country=r["scope_country"],
            clearing=r["scope_clearing"],
            product=r["scope_product"],
            field_group=r["scope_field_group"],
        ),
        edge_count=r["edge_count"],
        resolution_percent=r["resolution_percent"],
    )


def _edge(r: sqlite3.Row) -> EdgeRow:
    return EdgeRow(
        id=r["id"],
        pair_id=r["pair_id"],
        mapper_id=r["mapper_id"],
        entry_point_id=r["entry_point_id"],
        kind=r["kind"],
        expression=r["expression"],
        static_helper_fqn=r["static_helper_fqn"],
        source_schema_id=r["source_schema_id"],
        source_path=r["source_path"],
        target_schema_id=r["target_schema_id"],
        target_path=r["target_path"],
        file=r["file"],
        line=r["line"],
        browse_url=r["browse_url"] or None,
    )


def _load_helpers(
    conn: sqlite3.Connection,
    edge_ids: list[str],
) -> list[HelperBody]:
    placeholders = ",".join("?" * len(edge_ids))
    rows = conn.execute(
        f"""SELECT DISTINCT h.fqn, h.file, h.start_line, h.end_line,
                            h.signature, h.body, h.body_sha256
            FROM edge_resolution er
            JOIN helper h ON er.helper_fqn = h.fqn
            WHERE er.edge_id IN ({placeholders})
              AND er.kind IN ('qualifier','static_call','intra_class')
            ORDER BY h.fqn""",
        edge_ids,
    ).fetchall()
    return [
        HelperBody(
            fqn=r["fqn"],
            file=r["file"],
            start_line=r["start_line"],
            end_line=r["end_line"],
            signature=r["signature"],
            body=r["body"],
            body_sha256=r["body_sha256"],
        )
        for r in rows
    ]


__all__ = [
    "list_entry_points",
    "get_entry_point",
    "list_entry_point_edges",
    "router",
]


# Helpers above use Any-typed sqlite3.Row but we expose typed APIs.
_ = Any  # silence unused-import on some linters
