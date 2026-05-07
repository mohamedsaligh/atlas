"""Markdown + JSON-LD renderer over the SQLite snapshot."""

from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path

from jinja2 import Environment, BaseLoader, StrictUndefined

MAPPER_TEMPLATE = """\
---
atlas_sha: {{ atlas_sha }}
mapper_id: {{ mapper.id }}
mapper_kind: {{ mapper.kind }}
pair_id: {{ mapper.pair_id }}
repo: {{ mapper.repo_id }}
sha: {{ mapper.sha }}
file: {{ mapper.file }}
browse_url: {{ mapper.browse_url }}
scope: { common: {{ mapper.scope_common }}, country: {{ mapper.scope_country }}, clearing: {{ mapper.scope_clearing }} }
edges_count: {{ edges | length }}
---

# {{ mapper.fqn.split('.')[-1] }}

`{{ mapper.fqn }}` — {{ mapper.kind }} mapper.

## Field-level edges

| edge_id | source | → | target | kind | expression | code |
|---|---|---|---|---|---|---|
{% for e in edges -%}
| `{{ e.id }}` | `{{ e.source_path or '_(constant)_' }}` | → | `{{ e.target_path }}` | {{ e.kind }} | `{{ e.expression }}` | [L{{ e.line }}]({{ e.browse_url or '#' }}) |
{% endfor %}
"""


def render_site(conn: sqlite3.Connection, out_dir: Path) -> dict[str, int]:
    out_dir = Path(os.path.expanduser(str(out_dir)))
    out_dir.mkdir(parents=True, exist_ok=True)
    counts = {"mapper_md": 0, "service_jsonld": 0}

    snapshot_row = conn.execute("SELECT atlas_sha FROM snapshot LIMIT 1").fetchone()
    atlas_sha = snapshot_row[0] if snapshot_row else "0" * 64
    (out_dir / "snapshot.json").write_text(
        json.dumps({"atlas_sha": atlas_sha}, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )

    env = Environment(loader=BaseLoader(), undefined=StrictUndefined,
                      autoescape=False, keep_trailing_newline=True)
    template = env.from_string(MAPPER_TEMPLATE)

    mappers = conn.execute(
        "SELECT id, fqn, kind, pair_id, repo_id, file, sha, browse_url, "
        "scope_common, scope_country, scope_clearing, scope_product "
        "FROM mapper ORDER BY id"
    ).fetchall()

    for row in mappers:
        m = {
            "id": row[0], "fqn": row[1], "kind": row[2], "pair_id": row[3],
            "repo_id": row[4], "file": row[5], "sha": row[6], "browse_url": row[7],
            "scope_common": bool(row[8]), "scope_country": row[9],
            "scope_clearing": row[10], "scope_product": row[11],
        }
        edges = conn.execute(
            """
            SELECT e.id, e.kind, e.expression, e.line, e.browse_url,
                   sf.path AS source_path, tf.path AS target_path
            FROM edge e
            LEFT JOIN field sf ON e.source_field_id = sf.id
            LEFT JOIN field tf ON e.target_field_id = tf.id
            WHERE e.mapper_id = ?
            ORDER BY e.line, e.id
            """,
            (m["id"],),
        ).fetchall()
        edge_dicts = [
            {"id": e[0], "kind": e[1], "expression": (e[2] or "")[:60],
             "line": e[3], "browse_url": e[4], "source_path": e[5], "target_path": e[6]}
            for e in edges
        ]
        body = template.render(atlas_sha=atlas_sha, mapper=m, edges=edge_dicts)
        path = out_dir / "services" / m["repo_id"] / m["pair_id"] / "mappers" / (
            m["fqn"].rsplit(".", 1)[-1] + ".md"
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
        counts["mapper_md"] += 1

    # Per-service JSON-LD (compact)
    services = conn.execute("SELECT DISTINCT repo_id FROM mapper").fetchall()
    for (svc,) in services:
        nodes = []
        for row in conn.execute(
            "SELECT id, fqn, kind, pair_id, file, browse_url FROM mapper WHERE repo_id = ?",
            (svc,),
        ):
            nodes.append({
                "@id": f"mapper:{row[0]}", "@type": "Mapper",
                "fqn": row[1], "kind": row[2], "pair": row[3],
                "file": row[4], "browse_url": row[5],
            })
        for row in conn.execute(
            """
            SELECT e.id, e.pair_id, e.mapper_id, e.kind, e.expression, e.line, e.browse_url,
                   sf.id AS sf_id, tf.id AS tf_id
            FROM edge e
            JOIN mapper m ON e.mapper_id = m.id
            LEFT JOIN field sf ON e.source_field_id = sf.id
            LEFT JOIN field tf ON e.target_field_id = tf.id
            WHERE m.repo_id = ?
            """,
            (svc,),
        ):
            nodes.append({
                "@id": f"edge:{row[0]}", "@type": "Edge",
                "pair": row[1], "mapper": f"mapper:{row[2]}",
                "kind": row[3], "expression": row[4], "line": row[5],
                "browse_url": row[6], "source": row[7], "target": row[8],
            })
        doc = {
            "@context": {"@vocab": "https://atlas.x/v1/"},
            "@graph": sorted(nodes, key=lambda d: d["@id"]),
        }
        out = out_dir / "services" / svc / "graph.jsonld"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(doc, sort_keys=True, indent=2, ensure_ascii=False) + "\n",
                       encoding="utf-8")
        counts["service_jsonld"] += 1

    return counts
