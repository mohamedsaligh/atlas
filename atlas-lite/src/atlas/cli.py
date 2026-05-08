"""atlas CLI — extract / render / coverage / impact / validate-config."""

from __future__ import annotations

import json
import os
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from . import config as _cfg
from . import db as _db
from . import extract as _extract
from . import render as _render

app = typer.Typer(no_args_is_help=True)
console = Console()


@app.command()
def init(
    config: Path = typer.Option(..., "--config", "-c", exists=True, dir_okay=False),
) -> None:
    """Create / verify the Atlas Lite database."""
    cfg = _cfg.load_config(config)
    conn = _db.open_db(cfg.storage.db_path)
    _db.init_schema(conn)
    console.print(f"[bold green]ok[/] db initialised at {cfg.storage.db_path}")


@app.command()
def extract(
    config: Path = typer.Option(..., "--config", "-c", exists=True, dir_okay=False),
    pair: str | None = typer.Option(None, "--pair", help="Restrict to one pair id"),
    repo: str | None = typer.Option(None, "--repo", help="Restrict to one repo id"),
    full: bool = typer.Option(False, "--full", help="Drop and recreate the DB"),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
    file_timeout: float = typer.Option(60.0, "--file-timeout", help="Seconds before a file is marked unparseable"),
) -> None:
    """Walk every (repo, pair) combination and persist edges into SQLite."""
    cfg = _cfg.load_config(config)
    cfg_dir = config.parent.resolve()

    conn = _db.open_db(cfg.storage.db_path)
    if full:
        _db.reset(conn)
    else:
        _db.init_schema(conn)

    business_keys = _extract._build_business_keys(cfg, cfg_dir)
    results = _extract.run_extract(
        cfg, cfg_dir,
        pair_filter=pair, repo_filter=repo,
        file_timeout_s=file_timeout, verbose=verbose,
    )
    atlas_sha = _extract.compute_atlas_sha(cfg, cfg_dir, results)
    _extract.persist(conn, cfg, cfg_dir, results, business_keys, atlas_sha)

    total_edges = sum(len(r.edges) for r in results.values())
    total_mappers = sum(len(r.mappers) for r in results.values())
    unparseable = sum(len(r.unparseable) for r in results.values())
    console.print(
        f"[bold green]ok[/] atlas_sha={atlas_sha[:12]} "
        f"mappers={total_mappers} edges={total_edges} unparseable={unparseable}"
    )
    if unparseable:
        console.print("[red]extract failed: unparseable files in scope[/]")
        raise typer.Exit(code=1)


@app.command()
def render(
    config: Path = typer.Option(..., "--config", "-c", exists=True, dir_okay=False),
    out: Path | None = typer.Option(None, "--out", help="Override site_path from atlas.yml"),
) -> None:
    """Render the SQLite snapshot to a Markdown + JSON-LD site."""
    cfg = _cfg.load_config(config)
    site = Path(os.path.expanduser(str(out or cfg.storage.site_path)))
    conn = _db.open_db(cfg.storage.db_path)
    counts = _render.render_site(conn, site)
    console.print(f"[bold green]ok[/] {counts} → {site}")


@app.command(name="validate-config")
def validate_config(
    config: Path = typer.Option(..., "--config", "-c", exists=True, dir_okay=False),
) -> None:
    """Load + JSON-schema-validate atlas.yml without running extraction."""
    _cfg.load_config(config)
    console.print(f"[bold green]ok[/] {config} valid")


@app.command()
def coverage(
    config: Path = typer.Option(..., "--config", "-c", exists=True, dir_okay=False),
    pair: str | None = typer.Option(None, "--pair"),
    repo: str | None = typer.Option(None, "--repo"),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """Print pair-level coverage percentages, sorted lowest first."""
    cfg = _cfg.load_config(config)
    conn = _db.open_db(cfg.storage.db_path)
    where = []
    args: list[str] = []
    if pair:
        where.append("pair_id = ?"); args.append(pair)
    if repo:
        where.append("repo_id = ?"); args.append(repo)
    sql = ("SELECT repo_id, pair_id, target_field_count, "
           "edges_emitted, coverage_percent, unmatched_json FROM coverage")
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY coverage_percent IS NULL, coverage_percent ASC, repo_id, pair_id"
    rows = conn.execute(sql, args).fetchall()
    if json_out:
        out = [
            {"repo": r[0], "pair": r[1], "target_field_count": r[2],
             "edges": r[3], "coverage_percent": r[4],
             "unmatched": json.loads(r[5] or "[]")}
            for r in rows
        ]
        console.print_json(data=out)
        return

    table = Table(title="Coverage", header_style="bold")
    table.add_column("repo")
    table.add_column("pair")
    table.add_column("target fields", justify="right")
    table.add_column("edges", justify="right")
    table.add_column("coverage %", justify="right")
    table.add_column("unmatched", justify="right")
    for r in rows:
        unmatched = json.loads(r[5] or "[]")
        pct_str = f"{r[4]:.2f}" if r[4] is not None else "—"
        table.add_row(r[0], r[1], str(r[2] or 0), str(r[3]), pct_str, str(len(unmatched)))
    console.print(table)


@app.command()
def impact(
    config: Path = typer.Option(..., "--config", "-c", exists=True, dir_okay=False),
    schema: str = typer.Option(..., "--schema", help="Source schema id (basename, e.g. Mt103.json)"),
    path: str = typer.Option(..., "--path", help="Field path to trace (exact or subtree root)"),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """Reverse-edge BFS: list every target field affected by changing the
    given source path. Direct hits only — multi-pair chaining via
    business_key is a Phase-2 follow-up."""
    cfg = _cfg.load_config(config)
    conn = _db.open_db(cfg.storage.db_path)
    rows = conn.execute(
        """SELECT ep.scope_country, ep.scope_clearing, ep.scope_product,
                  ep.class_fqn, ep.method_name, ep.id,
                  e.kind, e.line, e.browse_url, e.static_helper_fqn,
                  sf.path AS source_path, tf.path AS target_path,
                  ts.id AS target_schema_id, e.entry_point_id
           FROM edge e
           JOIN field sf ON e.source_field_id = sf.id
           JOIN field tf ON e.target_field_id = tf.id
           JOIN schema ts ON tf.schema_id = ts.id
           LEFT JOIN entry_point ep ON e.entry_point_id = ep.id
           WHERE sf.schema_id = ?
             AND (sf.path = ? OR sf.path LIKE ? || '.%')
           ORDER BY ep.scope_country, ep.scope_clearing, ep.scope_product,
                    ep.class_fqn, ep.method_name, e.line""",
        (schema, path, path),
    ).fetchall()
    if json_out:
        out = [
            {
                "country": r[0] or "COMMON",
                "clearing": r[1] or "COMMON",
                "product": r[2] or "COMMON",
                "class_fqn": r[3], "method_name": r[4],
                "entry_point_id": r[5],
                "kind": r[6], "line": r[7], "browse_url": r[8],
                "helper": r[9],
                "source_path": r[10], "target_path": r[11],
                "target_schema": r[12],
            }
            for r in rows
        ]
        console.print_json(data=out)
        return

    if not rows:
        console.print(f"[yellow]no impact[/] for {schema}:{path}")
        return

    table = Table(title=f"Impact of changing {schema}:{path}", header_style="bold")
    table.add_column("country"); table.add_column("clearing"); table.add_column("product")
    table.add_column("entry_point"); table.add_column("source"); table.add_column("→")
    table.add_column("target"); table.add_column("kind"); table.add_column("line")
    for r in rows:
        ep_short = (r[3].rsplit(".", 1)[-1] + "." + r[4]) if r[3] else "(unknown)"
        table.add_row(
            r[0] or "COMMON", r[1] or "COMMON", r[2] or "COMMON",
            ep_short, r[10], "→", f"{r[12]}:{r[11]}", r[6], f"L{r[7]}",
        )
    console.print(table)
    console.print(f"[dim]{len(rows)} affected edges[/]")


@app.command()
def version() -> None:
    from . import ATLAS_VERSION
    console.print(f"atlas-lite {ATLAS_VERSION}")


if __name__ == "__main__":
    app()
