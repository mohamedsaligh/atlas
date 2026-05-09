"""Force-graph endpoint.

Returns a compact ``{nodes, links}`` graph filtered by scope. The
frontend force-graph view consumes this directly; cardinality is
controlled by ``limit`` to keep client-side rendering smooth at scale
(default 4000 entry points, ≈20k field nodes).
"""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, Query

from ..deps import get_db
from ..models import GraphLink, GraphNode, GraphResponse

router = APIRouter(tags=["graph"])


@router.get(
    "/graph",
    response_model=GraphResponse,
    summary="Force-graph view of entry points + their source/target fields",
)
def graph(
    repo: str | None = Query(None),
    pair: str | None = Query(None),
    country: str | None = Query(None),
    clearing: str | None = Query(None),
    product: str | None = Query(None),
    class_fqn: str | None = Query(None),
    limit: int = Query(2000, ge=1, le=10000),
    conn: sqlite3.Connection = Depends(get_db),
) -> GraphResponse:
    where: list[str] = []
    args: list[object] = []
    if repo:
        where.append("ep.repo_id = ?")
        args.append(repo)
    if pair:
        where.append("ep.pair_id = ?")
        args.append(pair)
    if country:
        where.append("ep.scope_country = ?")
        args.append(country)
    if clearing:
        where.append("ep.scope_clearing = ?")
        args.append(clearing)
    if product:
        where.append("ep.scope_product = ?")
        args.append(product)
    if class_fqn:
        where.append("ep.class_fqn = ?")
        args.append(class_fqn)
    where_sql = ("WHERE " + " AND ".join(where)) if where else ""

    total = conn.execute(
        f"SELECT COUNT(*) AS n FROM entry_point ep {where_sql}", args
    ).fetchone()["n"]
    truncated = total > limit

    ep_rows = conn.execute(
        f"""SELECT ep.id, ep.class_fqn, ep.method_name,
                   ep.scope_country, ep.scope_clearing, ep.scope_product,
                   ep.edge_count, ep.resolution_percent
            FROM entry_point ep
            {where_sql}
            ORDER BY ep.edge_count DESC
            LIMIT ?""",
        [*args, limit],
    ).fetchall()
    if not ep_rows:
        return GraphResponse(nodes=[], links=[], truncated=False)

    ep_ids = [r["id"] for r in ep_rows]
    placeholders = ",".join("?" * len(ep_ids))

    edge_rows = conn.execute(
        f"""SELECT e.entry_point_id,
                   sf.id AS source_field_id, sf.schema_id AS source_schema, sf.path AS source_path,
                   tf.id AS target_field_id, tf.schema_id AS target_schema, tf.path AS target_path
            FROM edge e
            LEFT JOIN field sf ON e.source_field_id = sf.id
            LEFT JOIN field tf ON e.target_field_id = tf.id
            WHERE e.entry_point_id IN ({placeholders})""",
        ep_ids,
    ).fetchall()

    nodes: dict[str, GraphNode] = {}
    links: list[GraphLink] = []

    for r in ep_rows:
        nodes[r["id"]] = GraphNode(
            id=r["id"],
            label=f"{r['class_fqn'].rsplit('.', 1)[-1]}.{r['method_name']}",
            kind="entry_point",
            country=r["scope_country"],
            clearing=r["scope_clearing"],
            product=r["scope_product"],
            edge_count=r["edge_count"],
            resolution_percent=r["resolution_percent"],
        )

    for r in edge_rows:
        ep_id = r["entry_point_id"]
        if ep_id is None or ep_id not in nodes:
            continue

        if r["target_field_id"]:
            tid = r["target_field_id"]
            nodes.setdefault(
                tid,
                GraphNode(
                    id=tid,
                    label=r["target_path"],
                    kind="field",
                    schema_id=r["target_schema"],
                ),
            )
            links.append(GraphLink(source=ep_id, target=tid, kind="writes"))

        if r["source_field_id"]:
            sid = r["source_field_id"]
            nodes.setdefault(
                sid,
                GraphNode(
                    id=sid,
                    label=r["source_path"],
                    kind="field",
                    schema_id=r["source_schema"],
                ),
            )
            links.append(GraphLink(source=sid, target=ep_id, kind="reads"))

    return GraphResponse(
        nodes=list(nodes.values()),
        links=links,
        truncated=truncated,
    )
