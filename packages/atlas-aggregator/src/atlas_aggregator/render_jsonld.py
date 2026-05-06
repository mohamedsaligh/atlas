"""Emit per-service graph.jsonld and a global atlas-global.jsonld."""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any

from .graph import Graph
from .io import write_atomic


CONTEXT = {
    "@vocab": "https://atlas.x/v1/",
    "git": "https://atlas.x/v1/git/",
    "Edge": "https://atlas.x/v1/Edge",
    "Field": "https://atlas.x/v1/Field",
    "Mapper": "https://atlas.x/v1/Mapper",
}


def render(graph: Graph, out_dir: Path) -> list[Path]:
    written: list[Path] = []
    by_service: dict[str, dict[str, Any]] = defaultdict(lambda: {"@context": CONTEXT, "@graph": []})

    for (schema_file, path), node in sorted(graph.fields.items()):
        entry = {
            "@id": f"field:{schema_file}#{path}",
            "@type": "Field",
            "schemaFile": schema_file,
            "path": path,
            "businessKey": node.business_key,
            "type": node.type_fqn,
        }
        for service in {m.repo_id for m in graph.mappers.values()}:
            by_service[service]["@graph"].append(entry)

    for mapper_id in sorted(graph.mappers):
        mapper = graph.mappers[mapper_id]
        by_service[mapper.repo_id]["@graph"].append({
            "@id": f"mapper:{mapper_id}",
            "@type": "Mapper",
            "service": mapper.repo_id,
            "pair": mapper.pair_id,
            "kind": mapper.mapper_kind,
        })
        for e in sorted(mapper.edges, key=lambda x: x.edgeId):
            by_service[mapper.repo_id]["@graph"].append({
                "@id": f"edge:{e.edgeId}",
                "@type": "Edge",
                "mapper": f"mapper:{mapper_id}",
                "source": f"field:{e.source.schemaFile}#{e.source.path}" if e.source else None,
                "target": f"field:{e.target.schemaFile}#{e.target.path}",
                "kind": e.kind,
                "expression": e.expression,
                "git": e.git.model_dump(exclude_none=True),
                "scope": e.scope or {},
                "confidence": e.confidence,
            })

    for service, doc in sorted(by_service.items()):
        # Sort @graph deterministically by @id.
        doc["@graph"] = sorted(doc["@graph"], key=lambda d: d.get("@id", ""))
        path = out_dir / "services" / service / "graph.jsonld"
        write_atomic(path, doc)
        written.append(path)

    # Global = union of all per-service graphs.
    global_graph: list[Any] = []
    for doc in by_service.values():
        global_graph.extend(doc["@graph"])
    seen: set[str] = set()
    deduped: list[Any] = []
    for entry in sorted(global_graph, key=lambda d: d.get("@id", "")):
        eid = entry.get("@id", "")
        if eid in seen:
            continue
        seen.add(eid)
        deduped.append(entry)
    global_doc = {"@context": CONTEXT, "@graph": deduped}
    global_path = out_dir / "atlas-global.jsonld"
    write_atomic(global_path, global_doc)
    written.append(global_path)
    return written
