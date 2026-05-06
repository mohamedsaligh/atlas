"""Coverage analysis: compute unmatched target fields and synthetic
`kind=unmapped` edges that surface them in the KB.

A field is "unmatched" iff:
  - it appears in the target schema (enumerate_fields),
  - it is NOT marked `x-atlas-ignore: true`,
  - no edge writes to its dotted path.

Synthetic edges are emitted with:
  - kind="unmapped"
  - source=null
  - target=<schema field>
  - mapperId="schema:<schemaFile>"
  - mapperKind="schema"
  - confidence="high"  (the schema declares it; we know it's unwritten)
  - git anchored to the schema file (line=1, sha=0).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from .business_key import FieldAttrs, enumerate_fields
from .models import Edge, FieldRef, GitRef, Manifest


@dataclass(frozen=True)
class Unmatched:
    pair_id: str
    schema_file: str
    target_path: str


def compute_unmatched_per_manifest(
    manifest: Manifest, target_fields: dict[str, FieldAttrs]
) -> list[Unmatched]:
    """For one manifest, return its unmatched (declared-but-unwritten, non-ignored) target paths."""
    written: set[str] = set()
    for e in manifest.edges:
        written.add(e.target.path)
    unmatched: list[Unmatched] = []
    for path, attrs in sorted(target_fields.items()):
        if attrs.ignored:
            continue
        if path in written:
            continue
        unmatched.append(
            Unmatched(pair_id=manifest.pairId, schema_file=manifest.target.schemaFile, target_path=path)
        )
    return unmatched


def synthetic_unmapped_edges(manifest: Manifest, unmatched: list[Unmatched]) -> list[Edge]:
    """One synthetic Edge per Unmatched, attached to the manifest's repo+pair."""
    out: list[Edge] = []
    for u in unmatched:
        if u.pair_id != manifest.pairId:
            continue
        edge_id = _synthetic_edge_id(manifest.repoId, manifest.pairId, u.target_path)
        out.append(
            Edge(
                edgeId=edge_id,
                mapperId=f"schema:{u.schema_file}",
                mapperKind="schema",
                kind="unmapped",
                source=None,
                target=FieldRef(type="", path=u.target_path, schemaFile=u.schema_file),
                expression=None,
                staticHelperFqn=None,
                cardinality=None,
                branchCondition=None,
                formatSpec=None,
                scope=None,
                git=GitRef(repo="", sha="0" * 40, file=u.schema_file, line=1),
                testIds=[],
                confidence="high",
            )
        )
    return out


def _synthetic_edge_id(repo_id: str, pair_id: str, target_path: str) -> str:
    payload = f"unmapped\n{target_path}".encode("utf-8")
    h = hashlib.sha1(payload).hexdigest()[:8]
    return f"{repo_id}.{pair_id}.e_{h}"
