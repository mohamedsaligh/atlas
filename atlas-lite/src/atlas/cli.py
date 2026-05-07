"""atlas CLI — extract / render / serve / validate-config / check."""

from __future__ import annotations

import os
from pathlib import Path

import typer
from rich.console import Console

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
def version() -> None:
    from . import ATLAS_VERSION
    console.print(f"atlas-lite {ATLAS_VERSION}")


if __name__ == "__main__":
    app()
