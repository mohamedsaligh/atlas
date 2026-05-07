"""atlas-agg CLI."""

from __future__ import annotations

import json
from pathlib import Path

import typer
from rich.console import Console

from . import business_key, collect, coverage, graph, index_sqlite, io, render_jsonld, render_markdown
from .config import load_config

app = typer.Typer(no_args_is_help=True)
console = Console()


@app.command()
def version() -> None:
    """Print Atlas aggregator version."""
    console.print("atlas-aggregator 0.1.0")


@app.command()
def check(
    coverage_file: Path = typer.Option(..., "--coverage", exists=True, dir_okay=False),
    baseline: Path = typer.Option(..., "--baseline", dir_okay=False),
    max_added: int = typer.Option(
        0,
        "--max-added",
        help="Maximum allowed new unmatched fields beyond baseline. Default 0.",
    ),
) -> None:
    """Drift gate: compare coverage.json against a checked-in baseline.

    Exits non-zero when more than --max-added new unmatched fields appear.
    """
    cov = json.loads(coverage_file.read_text(encoding="utf-8"))
    cur = cov.get("unmatchedTargetFields", [])
    if baseline.exists():
        base = json.loads(baseline.read_text(encoding="utf-8")).get("unmatchedTargetFields", [])
    else:
        console.print(f"[yellow]no baseline at {baseline} — treating as empty[/]")
        base = []
    base_set = {(u["pairId"], u["targetPath"]) for u in base}
    cur_set = {(u["pairId"], u["targetPath"]) for u in cur}
    added = sorted(cur_set - base_set)
    removed = sorted(base_set - cur_set)

    if removed:
        console.print(f"[green]+{len(removed)} field(s) newly mapped[/]")
    if added:
        console.print(f"[red]drift: {len(added)} new unmatched field(s)[/]")
        for pair, path in added:
            console.print(f"  + {pair}: {path}")
    else:
        console.print("[green]no new unmatched fields[/]")

    if len(added) > max_added:
        console.print(f"[bold red]drift gate failed[/]: {len(added)} > max-added={max_added}")
        raise typer.Exit(code=1)
    console.print("[bold green]drift check passed[/]")


@app.command(name="accept-baseline")
def accept_baseline(
    coverage_file: Path = typer.Option(..., "--coverage", exists=True, dir_okay=False),
    baseline: Path = typer.Option(..., "--baseline", dir_okay=False),
) -> None:
    """Promote current coverage.json to be the new baseline (acknowledged drift)."""
    baseline.write_bytes(coverage_file.read_bytes())
    console.print(f"[bold green]baseline updated:[/] {baseline}")


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

    # 2. Enumerate schema fields per schema (gives us business keys + ignore flags + leaves).
    fields_per_schema: dict[str, dict[str, business_key.FieldAttrs]] = {}
    for m in manifests:
        for sref in (m.source, m.target):
            if sref.schemaFile in fields_per_schema:
                continue
            schema_path = (config_dir / sref.schemaFile).resolve()
            fields_per_schema[sref.schemaFile] = business_key.enumerate_fields(schema_path, sref.schemaKind)

    bk_per_schema: dict[str, dict[str, str]] = {
        s: {p: a.business_key for p, a in fmap.items() if a.business_key is not None}
        for s, fmap in fields_per_schema.items()
    }
    bk_count = sum(len(v) for v in bk_per_schema.values())
    console.print(
        f"[bold]business keys[/]: {bk_count} parsed across {len(fields_per_schema)} schema(s)"
    )

    # 3. Compute unmatched target fields per manifest + synthetic kind=unmapped edges.
    unmatched_records: list[coverage.Unmatched] = []
    augmented_manifests: list = []
    for m in manifests:
        target_fields = fields_per_schema.get(m.target.schemaFile, {})
        unmatched = coverage.compute_unmatched_per_manifest(m, target_fields)
        synthetic = coverage.synthetic_unmapped_edges(m, unmatched)
        unmatched_records.extend(unmatched)
        # Build a copy of the manifest with synthetic edges appended (in-memory only;
        # the on-disk Java manifest is unchanged).
        augmented_manifests.append(
            m.model_copy(update={"edges": list(m.edges) + synthetic})
        )
    console.print(
        f"[bold]unmatched[/]: {len(unmatched_records)} target field(s) declared-but-unwritten"
    )

    # 4. Build graph from augmented manifests.
    g = graph.build(augmented_manifests, bk_per_schema)
    console.print(
        f"[bold]graph[/]: {len(g.mappers)} mapper(s), {len(g.fields)} field(s), {len(g.edges)} edge(s)"
    )

    # 5. Render outputs.
    md = render_markdown.render(g, out)
    jl = render_jsonld.render(g, out)
    db_path = sqlite_db or (out / "index.db")
    index_sqlite.build(g, db_path)

    # 6. Write coverage.json — the canonical "what's missing" report.
    coverage_doc = {
        "atlas_version": "0.1.0",
        "unmatchedTargetFields": [
            {"pairId": u.pair_id, "schemaFile": u.schema_file, "targetPath": u.target_path}
            for u in unmatched_records
        ],
        "perPair": _per_pair_summary(augmented_manifests, fields_per_schema),
    }
    io.write_atomic(out / "coverage.json", coverage_doc)

    console.print(
        f"[bold green]ok[/] markdown={len(md)} jsonld={len(jl)} sqlite={db_path} "
        f"coverage={out / 'coverage.json'}"
    )


def _per_pair_summary(manifests: list, fields_per_schema: dict) -> list[dict]:
    out: list[dict] = []
    for m in manifests:
        target_fields = fields_per_schema.get(m.target.schemaFile, {})
        declared = len(target_fields)
        ignored = sum(1 for a in target_fields.values() if a.ignored)
        non_ignored = declared - ignored
        # Count writes to NON-synthetic edges only (exclude unmapped placeholders).
        written_paths = {e.target.path for e in m.edges if e.kind != "unmapped"}
        unmatched = sum(
            1
            for p, a in target_fields.items()
            if not a.ignored and p not in written_paths
        )
        coverage_pct = (
            round(100.0 * (non_ignored - unmatched) / non_ignored, 2) if non_ignored > 0 else 100.0
        )
        out.append({
            "pairId": m.pairId,
            "schemaFile": m.target.schemaFile,
            "declaredFields": declared,
            "ignoredFields": ignored,
            "writtenFields": non_ignored - unmatched,
            "unmatchedFields": unmatched,
            "coveragePercent": coverage_pct,
        })
    return out


if __name__ == "__main__":
    app()
