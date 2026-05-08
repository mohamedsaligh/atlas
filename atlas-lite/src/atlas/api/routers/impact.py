"""Impact endpoint — reverse-edge lookup for "if I change X, what breaks?"."""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, Query

from ..deps import get_db
from ..models import ImpactRow, Page, Scope

router = APIRouter(tags=["impact"])


@router.get(
    "/impact",
    response_model=Page[ImpactRow],
    summary="Reverse-edge BFS for a source field path",
    description=(
        "Surface every target field affected by changing the given source "
        "schema:path. Direct hits only — multi-pair chaining via "
        "`business_key` is a follow-up. Use the `path` parameter as either "
        "an exact path or a subtree root (the `.subpath` descendants are "
        "included automatically)."
    ),
)
def impact(
    schema: str = Query(..., description="Source schema id (basename, e.g. Mt103.json)"),
    path: str = Query(..., description="Exact field path or subtree root"),
    page: int = Query(1, ge=1),
    size: int = Query(100, ge=1, le=1000),
    conn: sqlite3.Connection = Depends(get_db),
) -> Page[ImpactRow]:
    where = "WHERE sf.schema_id = ? AND (sf.path = ? OR sf.path LIKE ? || '.%')"
    args = (schema, path, path)

    total = conn.execute(
        f"""SELECT COUNT(*) AS n
            FROM edge e
            JOIN field sf ON e.source_field_id = sf.id
            {where}""",
        args,
    ).fetchone()["n"]

    rows = conn.execute(
        f"""SELECT ep.id AS ep_id, ep.class_fqn, ep.method_name,
                   ep.scope_common, ep.scope_country, ep.scope_clearing,
                   ep.scope_product, ep.scope_field_group,
                   e.id AS edge_id, e.kind, e.line, e.browse_url,
                   e.static_helper_fqn,
                   sf.schema_id AS source_schema_id, sf.path AS source_path,
                   tf.schema_id AS target_schema_id, tf.path AS target_path
            FROM edge e
            JOIN field sf ON e.source_field_id = sf.id
            JOIN field tf ON e.target_field_id = tf.id
            LEFT JOIN entry_point ep ON e.entry_point_id = ep.id
            {where}
            ORDER BY ep.scope_country, ep.scope_clearing, ep.scope_product,
                     ep.class_fqn, ep.method_name, e.line
            LIMIT ? OFFSET ?""",
        (*args, size, (page - 1) * size),
    ).fetchall()

    items = [
        ImpactRow(
            entry_point_id=r["ep_id"],
            class_fqn=r["class_fqn"],
            method_name=r["method_name"],
            scope=Scope(
                common=bool(r["scope_common"] or 0),
                country=r["scope_country"],
                clearing=r["scope_clearing"],
                product=r["scope_product"],
                field_group=r["scope_field_group"],
            ),
            edge_id=r["edge_id"],
            kind=r["kind"],
            helper=r["static_helper_fqn"],
            source_schema_id=r["source_schema_id"],
            source_path=r["source_path"],
            target_schema_id=r["target_schema_id"],
            target_path=r["target_path"],
            line=r["line"],
            browse_url=r["browse_url"] or None,
        )
        for r in rows
    ]
    return Page[ImpactRow](items=items, page=page, size=size, total=total)
