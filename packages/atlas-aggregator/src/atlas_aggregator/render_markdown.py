"""Render one Markdown file per mapper, deterministic byte output."""

from __future__ import annotations

from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from .graph import Graph
from .io import write_text_atomic


def render(graph: Graph, out_dir: Path) -> list[Path]:
    template_dir = Path(__file__).parent / "templates"
    env = Environment(
        loader=FileSystemLoader(str(template_dir)),
        undefined=StrictUndefined,
        autoescape=False,
        keep_trailing_newline=True,
    )
    template = env.get_template("mapper.md.j2")

    written: list[Path] = []
    for mapper_id in sorted(graph.mappers):
        mapper = graph.mappers[mapper_id]
        edges_sorted = sorted(
            mapper.edges,
            key=lambda e: (e.git.file, e.git.line, e.target.path, e.source.path if e.source else ""),
        )
        body = template.render(mapper=mapper, edges_sorted=edges_sorted)
        # Filename = simple class name + #method (sanitized).
        last = mapper_id.split(".")[-1].replace("#", "_").replace("::", "_")
        rel = out_dir / "services" / mapper.repo_id / mapper.pair_id / "mappers" / f"{last}.md"
        write_text_atomic(rel, body)
        written.append(rel)
    return written
