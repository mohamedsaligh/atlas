"""atlas-agg CLI."""

from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console

from . import business_key, collect, graph, index_sqlite, render_jsonld, render_markdown
from .config import load_config

app = typer.Typer(no_args_is_help=True)
console = Console()


@app.command()
def version() -> None:
    """Print Atlas aggregator version."""
    console.print("atlas-aggregator 0.1.0")


@app.command()
def build(
    config: Path = typer.Option(..., "--config", "-c", exists=True, dir_okay=False),
    out: Path = typer.Option(..., "--out", "-o", file_okay=False),
    sqlite_db: Path | None = typer.Option(None, "--sqlite", file_okay=True, dir_okay=False),
) -> None:
    """Aggregate manifests into atlas-kb (Markdown + JSON-LD + SQLite)."""
    config_path = config.resolve()
    cfg = load_config(config_path)
    config_dir = config_path.parent

    # 1. Collect + validate manifests.
    manifests = collect.collect_manifests(cfg, config_dir)
    console.print(f"[bold]collect[/]: {len(manifests)} manifest(s)")
    if not manifests:
        console.print("[yellow]no manifests found — did you run mvn atlas:extract?[/]")
        raise typer.Exit(code=1)

    # 2. Parse business keys per schema.
    bk_per_schema: dict[str, dict[str, str]] = {}
    for m in manifests:
        for sref in (m.source, m.target):
            if sref.schemaFile in bk_per_schema:
                continue
            schema_path = (config_dir / sref.schemaFile).resolve()
            bk_per_schema[sref.schemaFile] = business_key.parse(schema_path, sref.schemaKind)
    bk_count = sum(len(v) for v in bk_per_schema.values())
    console.print(f"[bold]business keys[/]: {bk_count} parsed across {len(bk_per_schema)} schema(s)")

    # 3. Build graph.
    g = graph.build(manifests, bk_per_schema)
    console.print(
        f"[bold]graph[/]: {len(g.mappers)} mapper(s), {len(g.fields)} field(s), {len(g.edges)} edge(s)"
    )

    # 4. Render outputs.
    md = render_markdown.render(g, out)
    jl = render_jsonld.render(g, out)
    db_path = sqlite_db or (out / "index.db")
    index_sqlite.build(g, db_path)

    console.print(f"[bold green]ok[/] markdown={len(md)} jsonld={len(jl)} sqlite={db_path}")


if __name__ == "__main__":
    app()
