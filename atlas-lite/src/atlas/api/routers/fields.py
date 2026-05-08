"""Field lookup endpoints — search by schema:path, return as-source / as-target."""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Query, status

from ..deps import get_db
from ..models import EdgeRow, FieldRow

router = APIRouter(tags=["fields"])


@router.get(
    "/fields",
    response_model=list[FieldRow],
    summary="Search for fields by schema and path prefix",
)
def search_fields(
    schema: str | None = Query(None),
    path_prefix: str | None = Query(
        None,
        description="Substring match on the field path (case-sensitive).",
    ),
    business_key: str | None = Query(None),
    limit: int = Query(100, ge=1, le=1000),
    conn: sqlite3.Connection = Depends(get_db),
) -> list[FieldRow]:
    where: list[str] = []
    args: list[object] = []
    if schema:
        where.append("schema_id = ?")
        args.append(schema)
    if path_prefix:
        where.append("path LIKE ?")
        args.append(f"%{path_prefix}%")
    if business_key:
        where.append("business_key = ?")
        args.append(business_key)
    where_sql = ("WHERE " + " AND ".join(where)) if where else ""

    rows = conn.execute(
        f"""SELECT id, schema_id, path, business_key, type
            FROM field {where_sql}
            ORDER BY schema_id, path
            LIMIT ?""",
        [*args, limit],
    ).fetchall()
    return [
        FieldRow(
            id=r["id"],
            schema_id=r["schema_id"],
            path=r["path"],
            business_key=r["business_key"],
            type=r["type"],
        )
        for r in rows
    ]


@router.get(
    "/fields/find",
    response_model=FieldRow,
    summary="Look up one field by schema id + exact path",
)
def find_field(
    schema: str = Query(..., description="Schema id (basename of schema file)"),
    path: str = Query(..., description="Exact field path"),
    conn: sqlite3.Connection = Depends(get_db),
) -> FieldRow:
    row = conn.execute(
        "SELECT id, schema_id, path, business_key, type FROM field "
        "WHERE schema_id = ? AND path = ?",
        (schema, path),
    ).fetchone()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"field {schema}:{path} not found",
        )
    return FieldRow(
        id=row["id"],
        schema_id=row["schema_id"],
        path=row["path"],
        business_key=row["business_key"],
        type=row["type"],
    )


@router.get(
    "/fields/find/edges",
    response_model=dict[str, list[EdgeRow]],
    summary="Edges referencing this field as source AND as target",
)
def find_field_edges(
    schema: str = Query(...),
    path: str = Query(...),
    limit: int = Query(500, ge=1, le=5000),
    conn: sqlite3.Connection = Depends(get_db),
) -> dict[str, list[EdgeRow]]:
    field_id = f"{schema}#{path}"
    as_source = _edges_for(conn, "source_field_id", field_id, limit)
    as_target = _edges_for(conn, "target_field_id", field_id, limit)
    return {"as_source": as_source, "as_target": as_target}


def _edges_for(
    conn: sqlite3.Connection,
    column: str,
    field_id: str,
    limit: int,
) -> list[EdgeRow]:
    rows = conn.execute(
        f"""SELECT e.id, e.pair_id, e.mapper_id, e.entry_point_id, e.kind,
                   e.expression, e.static_helper_fqn, e.file, e.line, e.browse_url,
                   sf.schema_id AS source_schema_id, sf.path AS source_path,
                   tf.schema_id AS target_schema_id, tf.path AS target_path
            FROM edge e
            LEFT JOIN field sf ON e.source_field_id = sf.id
            LEFT JOIN field tf ON e.target_field_id = tf.id
            WHERE e.{column} = ?
            ORDER BY e.line, e.id
            LIMIT ?""",
        (field_id, limit),
    ).fetchall()
    return [
        EdgeRow(
            id=r["id"],
            pair_id=r["pair_id"],
            mapper_id=r["mapper_id"],
            entry_point_id=r["entry_point_id"],
            kind=r["kind"],
            expression=r["expression"],
            static_helper_fqn=r["static_helper_fqn"],
            source_schema_id=r["source_schema_id"],
            source_path=r["source_path"],
            target_schema_id=r["target_schema_id"] or "",
            target_path=r["target_path"] or "",
            file=r["file"],
            line=r["line"],
            browse_url=r["browse_url"] or None,
        )
        for r in rows
    ]
