"""Markdown + JSON-LD renderer over the SQLite snapshot.

Three artefact layers:

* **Per-mapper Markdown** — one ``.md`` per mapper class, edge-level table.
  Audience: engineers chasing a specific class.
* **Per-entry-point Markdown** — one ``.md`` per top-level transformation
  method (``MapperImpl.toLocal``, ``Encoder.encode``, etc). Each ``.md``
  inlines every helper body the resolver walked through, line-anchored
  to source. Audience: a Business Analyst who needs to read what the
  mapping actually does without going to the IDE. Pivots Markdown around
  the BA-facing unit (the method), not the class or file.
* **Per-service JSON-LD** — graph of mappers and edges per repo. Used by
  the future REST API and Obsidian-style graph view.

All output is deterministic: stable sort everywhere, trailing newline,
no timestamps embedded in the body. The ``atlas_sha`` in frontmatter is
the determinism gate — identical inputs produce byte-identical files.
"""

from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path
from typing import Any

from jinja2 import Environment, BaseLoader, StrictUndefined

# ─────────────────────────────────────────────────────────────────────────────
# Templates (module-level, single source of truth for output layout)
# ─────────────────────────────────────────────────────────────────────────────

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

ENTRY_POINT_TEMPLATE = """\
---
atlas_sha: {{ atlas_sha }}
entry_point_id: {{ ep.id }}
class_fqn: {{ ep.class_fqn }}
method_name: {{ ep.method_name }}
pair_id: {{ ep.pair_id }}
repo: {{ ep.repo_id }}
sha: {{ ep.sha }}
file: {{ ep.file }}
line: {{ ep.line }}
browse_url: {{ ep.browse_url }}
scope:
  country: {{ ep.scope_country or 'COMMON' }}
  clearing: {{ ep.scope_clearing or 'COMMON' }}
  product: {{ ep.scope_product or 'COMMON' }}
sources: {{ ep.source_schema_ids | tojson }}
target: {{ ep.target_schema_id }}
edge_count: {{ ep.edge_count }}
resolution_percent: {% if ep.resolution_percent is none %}null{% else %}{{ ep.resolution_percent }}{% endif %}
---

# {{ ep.class_fqn.split('.')[-1] }}.{{ ep.method_name }}

```java
{{ ep.method_signature }}
```

Defined in `{{ ep.file }}` at [L{{ ep.line }}]({{ ep.browse_url or '#' }}).

***

**Sources** → **Target**

{% for s in ep.source_schema_ids %}
- `{{ s }}` → `{{ ep.target_schema_id }}`
{% endfor %}

**Scope** — country=`{{ ep.scope_country or 'COMMON' }}` · clearing=`{{ ep.scope_clearing or 'COMMON' }}` · product=`{{ ep.scope_product or 'COMMON' }}`{% if ep.scope_field_group %} · field_group=`{{ ep.scope_field_group }}`{% endif %}

***

## Field-level edges ({{ edges | length }})

| # | source / value | → | target path | kind | helper | line |
|---|---|---|---|---|---|---|
{% for e in edges %}
| {{ loop.index }} | `{{ e.display_source }}` | → | `{{ e.target_path }}` | {{ e.kind }} | {% if e.static_helper_fqn %}`{{ e.static_helper_fqn.split('.')[-2] }}.{{ e.static_helper_fqn.split('.')[-1] }}`{% else %}—{% endif %} | [L{{ e.line }}]({{ e.browse_url or '#' }}) |
{% endfor %}

{% if helpers %}
***

## Helper logic

Every `qualifier`, `static_call`, and `intra_class` edge above resolves through one or more helper methods.
Below is the **full body** of each helper the resolver walked through, deduplicated by FQN and line-anchored to source.

{% for h in helpers %}
### `{{ h.fqn }}`

```java
// {{ h.signature }}
// {{ h.file }}:L{{ h.start_line }}-L{{ h.end_line }}
{{ h.body }}
```

{% if h.used_by %}
Used by:

{% for u in h.used_by %}
- → `{{ u.target_path }}` ({{ u.kind }}, [L{{ u.line }}]({{ u.browse_url or '#' }}))
{% endfor %}
{% endif %}

{% endfor %}
{% endif %}
"""

INDEX_TEMPLATE = """\
---
atlas_sha: {{ atlas_sha }}
entry_point_count: {{ entry_points | length }}
---

# Atlas — Entry-point Index

Every top-level transformation method that emits at least one field-level edge.
Grouped by scope (country / clearing / product). Click a method to see its
field-level edges and full helper-body logic.

{% for group in groups %}
## {{ group.country }} · {{ group.clearing }} · {{ group.product }}

| class | method | sources → target | edges | resolution % | source |
|---|---|---|---|---|---|
{% for ep in group.entry_points %}
| `{{ ep.class_short }}` | [`{{ ep.method_name }}`]({{ ep.rel_path }}) | `{{ ep.sources_short }}` → `{{ ep.target_schema_id }}` | {{ ep.edge_count }} | {% if ep.resolution_percent is none %}—{% else %}{{ '%.2f' | format(ep.resolution_percent) }}{% endif %} | [L{{ ep.line }}]({{ ep.browse_url or '#' }}) |
{% endfor %}

{% endfor %}
"""


# ─────────────────────────────────────────────────────────────────────────────
# Public renderer
# ─────────────────────────────────────────────────────────────────────────────


def render_site(conn: sqlite3.Connection, out_dir: Path) -> dict[str, int]:
    """Render every artefact layer (mapper MD + entry-point MD + JSON-LD)."""
    out_dir = Path(os.path.expanduser(str(out_dir)))
    out_dir.mkdir(parents=True, exist_ok=True)
    counts: dict[str, int] = {
        "mapper_md": 0, "entry_point_md": 0, "service_jsonld": 0, "index_md": 0,
    }

    snapshot_row = conn.execute("SELECT atlas_sha FROM snapshot LIMIT 1").fetchone()
    atlas_sha = snapshot_row[0] if snapshot_row else "0" * 64
    (out_dir / "snapshot.json").write_text(
        json.dumps({"atlas_sha": atlas_sha}, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )

    env = _jinja()
    counts["mapper_md"] = _render_mappers(conn, out_dir, atlas_sha, env)
    ep_md, index_md = _render_entry_points(conn, out_dir, atlas_sha, env)
    counts["entry_point_md"] = ep_md
    counts["index_md"] = index_md
    counts["service_jsonld"] = _render_jsonld(conn, out_dir)
    return counts


# ─────────────────────────────────────────────────────────────────────────────
# Mapper layer (kept as-is — small audience: engineers grepping for a class)
# ─────────────────────────────────────────────────────────────────────────────


def _render_mappers(
    conn: sqlite3.Connection, out_dir: Path, atlas_sha: str, env: Environment,
) -> int:
    template = env.from_string(MAPPER_TEMPLATE)
    count = 0
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
        count += 1
    return count


# ─────────────────────────────────────────────────────────────────────────────
# Entry-point layer — the BA-facing artefact
# ─────────────────────────────────────────────────────────────────────────────


def _render_entry_points(
    conn: sqlite3.Connection, out_dir: Path, atlas_sha: str, env: Environment,
) -> tuple[int, int]:
    """Render one ``.md`` per entry-point + a top-level index. Helper bodies
    are inlined verbatim (deduplicated by FQN, line-anchored) so a Business
    Analyst reads the full transformation logic without leaving the page."""
    ep_template = env.from_string(ENTRY_POINT_TEMPLATE)
    index_template = env.from_string(INDEX_TEMPLATE)
    rows = conn.execute(
        """SELECT id, pair_id, repo_id, class_fqn, method_name, method_signature,
                  source_schema_ids, target_schema_id, file, line, sha, browse_url,
                  scope_common, scope_country, scope_clearing, scope_product,
                  scope_field_group, edge_count, resolution_percent
           FROM entry_point
           ORDER BY repo_id, pair_id, class_fqn, method_name, id"""
    ).fetchall()

    index_entries: list[dict[str, Any]] = []
    count = 0
    for row in rows:
        ep = _entry_point_dict(row)
        edges = _load_edges_for_ep(conn, ep["id"])
        helpers = _load_helpers_for_ep(conn, ep["id"], edges)

        body = ep_template.render(
            atlas_sha=atlas_sha, ep=ep, edges=edges, helpers=helpers,
        )
        rel_dir = Path("services") / ep["repo_id"] / ep["pair_id"] / "entry-points"
        filename = _entry_point_filename(ep)
        path = out_dir / rel_dir / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
        count += 1

        index_entries.append({
            "country": ep["scope_country"] or "COMMON",
            "clearing": ep["scope_clearing"] or "COMMON",
            "product": ep["scope_product"] or "COMMON",
            "class_short": ep["class_fqn"].rsplit(".", 1)[-1],
            "method_name": ep["method_name"],
            "sources_short": ", ".join(ep["source_schema_ids"]),
            "target_schema_id": ep["target_schema_id"],
            "edge_count": ep["edge_count"],
            "resolution_percent": ep["resolution_percent"],
            "line": ep["line"],
            "browse_url": ep["browse_url"],
            "rel_path": (Path("..") / rel_dir / filename).as_posix(),
        })

    if not index_entries:
        return count, 0

    groups = _group_index(index_entries)
    index_body = index_template.render(
        atlas_sha=atlas_sha, entry_points=index_entries, groups=groups,
    )
    index_path = out_dir / "entry-points" / "index.md"
    index_path.parent.mkdir(parents=True, exist_ok=True)
    index_path.write_text(index_body, encoding="utf-8")
    return count, 1


def _entry_point_dict(row: tuple[Any, ...]) -> dict[str, Any]:
    return {
        "id": row[0], "pair_id": row[1], "repo_id": row[2],
        "class_fqn": row[3], "method_name": row[4],
        "method_signature": row[5],
        "source_schema_ids": json.loads(row[6]) if row[6] else [],
        "target_schema_id": row[7], "file": row[8], "line": row[9],
        "sha": row[10], "browse_url": row[11],
        "scope_common": bool(row[12]),
        "scope_country": row[13], "scope_clearing": row[14],
        "scope_product": row[15], "scope_field_group": row[16],
        "edge_count": row[17], "resolution_percent": row[18],
    }


def _load_edges_for_ep(
    conn: sqlite3.Connection, entry_point_id: str,
) -> list[dict[str, Any]]:
    rows = conn.execute(
        """SELECT e.id, e.kind, e.expression, e.line, e.browse_url,
                  e.static_helper_fqn,
                  sf.path AS source_path, tf.path AS target_path
           FROM edge e
           LEFT JOIN field sf ON e.source_field_id = sf.id
           LEFT JOIN field tf ON e.target_field_id = tf.id
           WHERE e.entry_point_id = ?
           ORDER BY e.line, e.id""",
        (entry_point_id,),
    ).fetchall()
    out: list[dict[str, Any]] = []
    for r in rows:
        expression = (r[2] or "")
        out.append({
            "id": r[0], "kind": r[1], "expression": expression[:80],
            "line": r[3], "browse_url": r[4], "static_helper_fqn": r[5],
            "source_path": r[6], "target_path": r[7],
            # BA-facing column: when the resolver landed on a real schema
            # path show that; otherwise surface the literal expression so
            # constant / construction / format / expression rows are
            # readable instead of opaque ``_(constant)_`` placeholders.
            "display_source": _display_source(r[6], expression),
        })
    return out


def _display_source(source_path: str | None, expression: str) -> str:
    if source_path:
        return source_path
    expr = (expression or "").strip()
    if not expr:
        return "_(empty)_"
    # Markdown table cells: collapse whitespace and escape pipes.
    expr = " ".join(expr.split()).replace("|", "\\|")
    if len(expr) > 60:
        expr = expr[:59] + "…"
    return expr


def _load_helpers_for_ep(
    conn: sqlite3.Connection,
    entry_point_id: str,
    edges: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Collect every helper FQN walked by any edge under this entry-point —
    NOT just the last one. The full audit trail (edge_resolution) is the
    source of truth: a multi-hop chain (qualifier → static_call) surfaces
    *both* helper bodies, so the BA sees the entire delegation."""
    edge_ids = [e["id"] for e in edges]
    if not edge_ids:
        return []
    placeholders = ",".join("?" * len(edge_ids))
    rows = conn.execute(
        f"""SELECT er.helper_fqn, er.edge_id, er.kind, h.file, h.start_line,
                   h.end_line, h.signature, h.body
            FROM edge_resolution er
            JOIN helper h ON er.helper_fqn = h.fqn
            WHERE er.edge_id IN ({placeholders})
              AND er.kind IN ('qualifier','static_call','intra_class')
            ORDER BY er.helper_fqn, er.edge_id, er.seq""",
        edge_ids,
    ).fetchall()
    edges_by_id = {e["id"]: e for e in edges}
    by_fqn: dict[str, dict[str, Any]] = {}
    for r in rows:
        fqn = r[0]
        if fqn not in by_fqn:
            by_fqn[fqn] = {
                "fqn": fqn, "file": r[3], "start_line": r[4],
                "end_line": r[5], "signature": r[6], "body": r[7],
                "used_by": [],
            }
        edge = edges_by_id.get(r[1])
        if edge is None:
            continue
        used = {
            "target_path": edge["target_path"],
            "kind": edge["kind"],
            "line": edge["line"],
            "browse_url": edge["browse_url"],
        }
        if used not in by_fqn[fqn]["used_by"]:
            by_fqn[fqn]["used_by"].append(used)
    for h in by_fqn.values():
        h["used_by"].sort(key=lambda u: (u["line"], u["target_path"]))
    return [by_fqn[k] for k in sorted(by_fqn.keys())]


def _entry_point_filename(ep: dict[str, Any]) -> str:
    """Stable, navigable filename: ``{ClassSimple}.{method}.{shorthash}.md``.

    MapStruct generates method names as long as 100+ chars on big property
    graphs (``map_txInfoOriginator...CommonApiClearingSystemId``). Combined
    with deep ``services/{repo}/{pair}/entry-points/`` directories that
    drives the absolute path past Windows ``MAX_PATH`` (260 chars). We cap
    the visible prefix at 80 chars; the 12-char content-addressed suffix
    keeps uniqueness intact, and the human-readable name lives in the
    page's frontmatter and title.
    """
    class_simple = ep["class_fqn"].rsplit(".", 1)[-1]
    safe_method = ep["method_name"].replace("/", "_")
    short = ep["id"].rsplit("_", 1)[-1][:12]
    prefix = f"{class_simple}.{safe_method}"
    if len(prefix) > 80:
        prefix = prefix[:79] + "~"
    return f"{prefix}.{short}.md"


def _group_index(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for e in entries:
        key = (e["country"], e["clearing"], e["product"])
        groups.setdefault(key, []).append(e)
    out: list[dict[str, Any]] = []
    for (country, clearing, product) in sorted(groups.keys()):
        items = sorted(
            groups[(country, clearing, product)],
            key=lambda x: (x["class_short"], x["method_name"]),
        )
        out.append({
            "country": country, "clearing": clearing, "product": product,
            "entry_points": items,
        })
    return out


# ─────────────────────────────────────────────────────────────────────────────
# JSON-LD layer (per-service graph, used by REST + future graph view)
# ─────────────────────────────────────────────────────────────────────────────


def _render_jsonld(conn: sqlite3.Connection, out_dir: Path) -> int:
    count = 0
    services = conn.execute("SELECT DISTINCT repo_id FROM mapper").fetchall()
    for (svc,) in services:
        nodes: list[dict[str, Any]] = []
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
                   sf.id AS sf_id, tf.id AS tf_id, e.entry_point_id
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
                "entry_point": (f"entry_point:{row[9]}" if row[9] else None),
            })
        doc = {
            "@context": {"@vocab": "https://atlas.x/v1/"},
            "@graph": sorted(nodes, key=lambda d: d["@id"]),
        }
        out = out_dir / "services" / svc / "graph.jsonld"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(doc, sort_keys=True, indent=2, ensure_ascii=False) + "\n",
                       encoding="utf-8")
        count += 1
    return count


# ─────────────────────────────────────────────────────────────────────────────
# Internal
# ─────────────────────────────────────────────────────────────────────────────


def _jinja() -> Environment:
    return Environment(
        loader=BaseLoader(),
        undefined=StrictUndefined,
        autoescape=False,
        keep_trailing_newline=True,
        trim_blocks=True,
        lstrip_blocks=True,
    )
