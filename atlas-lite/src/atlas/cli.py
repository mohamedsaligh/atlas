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
    file_timeout: float = typer.Option(
        60.0, "--file-timeout", help="Seconds before a file is marked unparseable"
    ),
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
        cfg,
        cfg_dir,
        pair_filter=pair,
        repo_filter=repo,
        file_timeout_s=file_timeout,
        verbose=verbose,
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
    where: list[str] = []
    args: list[str] = []
    if pair:
        where.append("pair_id = ?")
        args.append(pair)
    if repo:
        where.append("repo_id = ?")
        args.append(repo)
    sql = (
        "SELECT repo_id, pair_id, target_field_count, "
        "edges_emitted, coverage_percent, unmatched_json FROM coverage"
    )
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY coverage_percent IS NULL, coverage_percent ASC, repo_id, pair_id"
    rows = conn.execute(sql, args).fetchall()
    if json_out:
        out = [
            {
                "repo": r[0],
                "pair": r[1],
                "target_field_count": r[2],
                "edges": r[3],
                "coverage_percent": r[4],
                "unmatched": json.loads(r[5] or "[]"),
            }
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
    schema: str = typer.Option(
        ..., "--schema", help="Source schema id (basename, e.g. Mt103.json)"
    ),
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
                "class_fqn": r[3],
                "method_name": r[4],
                "entry_point_id": r[5],
                "kind": r[6],
                "line": r[7],
                "browse_url": r[8],
                "helper": r[9],
                "source_path": r[10],
                "target_path": r[11],
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
    for col in (
        "country",
        "clearing",
        "product",
        "entry_point",
        "source",
        "→",
        "target",
        "kind",
        "line",
    ):
        table.add_column(col)
    for r in rows:
        ep_short = (r[3].rsplit(".", 1)[-1] + "." + r[4]) if r[3] else "(unknown)"
        table.add_row(
            r[0] or "COMMON",
            r[1] or "COMMON",
            r[2] or "COMMON",
            ep_short,
            r[10],
            "→",
            f"{r[12]}:{r[11]}",
            r[6],
            f"L{r[7]}",
        )
    console.print(table)
    console.print(f"[dim]{len(rows)} affected edges[/]")


@app.command()
def baseline(
    config: Path = typer.Option(..., "--config", "-c", exists=True, dir_okay=False),
    out: Path = typer.Option(
        Path("coverage-baseline.json"), "--out", help="Where to write the baseline"
    ),
) -> None:
    """Snapshot the current coverage state to a baseline file consumed by
    ``atlas check``. The baseline is the contract CI gates against — commit
    it alongside atlas.yml and refresh deliberately when coverage genuinely
    moves."""
    cfg = _cfg.load_config(config)
    conn = _db.open_db(cfg.storage.db_path)
    rows = conn.execute(
        """SELECT repo_id, pair_id, target_field_count, coverage_percent, unmatched_json
           FROM coverage ORDER BY repo_id, pair_id"""
    ).fetchall()
    snap = conn.execute("SELECT atlas_sha FROM snapshot LIMIT 1").fetchone()
    payload: dict[str, object] = {
        "schema_version": 1,
        "atlas_sha": snap[0] if snap else None,
        "pairs": {
            f"{r[0]}:{r[1]}": {
                "target_field_count": r[2],
                "coverage_percent": r[3],
                "unmatched": json.loads(r[4] or "[]"),
            }
            for r in rows
        },
    }
    out.write_text(
        json.dumps(payload, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    console.print(f"[bold green]ok[/] baseline written to {out} ({len(payload['pairs'])} pair(s))")


@app.command()
def check(
    config: Path = typer.Option(..., "--config", "-c", exists=True, dir_okay=False),
    baseline_path: Path = typer.Option(..., "--baseline", exists=True, dir_okay=False),
    max_added: int = typer.Option(
        0,
        "--max-added",
        min=0,
        help="Allowable count of newly-unmatched target paths per pair before the gate fires",
    ),
    max_coverage_drop: float = typer.Option(
        0.0,
        "--max-coverage-drop",
        min=0.0,
        help="Allowable absolute coverage_percent drop (e.g. 0.5 → permit 99.5 → 99.0)",
    ),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """CI drift gate. Compare current pair-level coverage against a baseline.
    Exits non-zero when any pair's regression exceeds the configured caps."""
    cfg = _cfg.load_config(config)
    conn = _db.open_db(cfg.storage.db_path)
    baseline_doc = json.loads(baseline_path.read_text(encoding="utf-8"))
    sv = baseline_doc.get("schema_version")
    if sv != 1:
        console.print(f"[red]unsupported baseline schema_version: {sv!r}[/]")
        raise typer.Exit(code=2)
    base_pairs: dict[str, dict] = baseline_doc.get("pairs", {})

    rows = conn.execute(
        """SELECT repo_id, pair_id, target_field_count, coverage_percent, unmatched_json
           FROM coverage ORDER BY repo_id, pair_id"""
    ).fetchall()
    current: dict[str, dict] = {
        f"{r[0]}:{r[1]}": {
            "target_field_count": r[2],
            "coverage_percent": r[3],
            "unmatched": json.loads(r[4] or "[]"),
        }
        for r in rows
    }

    diff: list[dict] = []
    failed = False
    for key in sorted(set(current) | set(base_pairs)):
        cur = current.get(key) or {
            "target_field_count": 0,
            "coverage_percent": None,
            "unmatched": [],
        }
        base = base_pairs.get(key) or {
            "target_field_count": 0,
            "coverage_percent": None,
            "unmatched": [],
        }
        added = sorted(set(cur["unmatched"]) - set(base["unmatched"]))
        removed = sorted(set(base["unmatched"]) - set(cur["unmatched"]))
        cur_pct = cur["coverage_percent"] if cur["coverage_percent"] is not None else 0.0
        base_pct = base["coverage_percent"] if base["coverage_percent"] is not None else 0.0
        cov_drop = round(base_pct - cur_pct, 2)
        regression = (len(added) > max_added) or (cov_drop > max_coverage_drop)
        if regression:
            failed = True
        diff.append(
            {
                "pair": key,
                "coverage_percent": cur["coverage_percent"],
                "baseline_coverage_percent": base["coverage_percent"],
                "coverage_drop": cov_drop,
                "added_unmatched": added,
                "removed_unmatched": removed,
                "regression": regression,
            }
        )

    if json_out:
        console.print_json(
            data={
                "max_added": max_added,
                "max_coverage_drop": max_coverage_drop,
                "failed": failed,
                "diff": diff,
            }
        )
    else:
        table = Table(title="Drift gate", header_style="bold")
        table.add_column("pair")
        table.add_column("coverage %", justify="right")
        table.add_column("Δ %", justify="right")
        table.add_column("+ unmatched", justify="right")
        table.add_column("− unmatched", justify="right")
        table.add_column("regression?", justify="center")
        for d in diff:
            pct = "—" if d["coverage_percent"] is None else f"{d['coverage_percent']:.2f}"
            table.add_row(
                d["pair"],
                pct,
                f"{d['coverage_drop']:+.2f}",
                str(len(d["added_unmatched"])),
                str(len(d["removed_unmatched"])),
                ("[red]YES[/]" if d["regression"] else "[green]no[/]"),
            )
        console.print(table)
        for d in diff:
            if d["regression"]:
                console.print(
                    f"[red]regression[/] in {d['pair']}: "
                    f"+{len(d['added_unmatched'])} unmatched, "
                    f"Δ {d['coverage_drop']:+.2f}%"
                )
                if d["added_unmatched"]:
                    for path in d["added_unmatched"]:
                        console.print(f"  [red]+[/] {path}")
        stale = any(d["removed_unmatched"] for d in diff)
        if stale:
            console.print(
                "[yellow]baseline is stale[/]: at least one pair now covers fields "
                "the baseline still lists as unmatched. Re-run "
                "`atlas baseline` to refresh."
            )
        if failed:
            console.print("[bold red]drift gate failed[/]")
        else:
            console.print("[bold green]drift gate passed[/]")

    if failed:
        raise typer.Exit(code=1)


@app.command()
def serve(
    config: Path | None = typer.Option(
        None,
        "--config",
        "-c",
        help="Optional atlas.yml; if set, its storage.db_path seeds the API "
        "default. Otherwise ATLAS_DB_PATH (or its default) is used.",
    ),
    host: str = typer.Option("127.0.0.1", "--host"),
    port: int = typer.Option(8080, "--port"),
    reload: bool = typer.Option(False, "--reload", help="Dev hot-reload."),
    log_level: str = typer.Option("info", "--log-level"),
) -> None:
    """Run the read API. Reads the SQLite snapshot at startup and serves
    it via FastAPI / uvicorn at ``--host:--port``."""
    from .api.settings import Settings

    if config is not None:
        cfg = _cfg.load_config(config)
        os.environ.setdefault("ATLAS_DB_PATH", str(cfg.storage.db_path))
    settings = Settings()
    console.print(
        f"[bold green]atlas serve[/] db={settings.resolved_db_path} "
        f"prefix={settings.api_prefix} host={host}:{port}"
    )
    import uvicorn

    uvicorn.run(
        "atlas.api:create_app",
        host=host,
        port=port,
        reload=reload,
        log_level=log_level,
        factory=True,
    )


@app.command()
def version() -> None:
    from . import ATLAS_VERSION

    console.print(f"atlas-lite {ATLAS_VERSION}")


if __name__ == "__main__":
    app()
