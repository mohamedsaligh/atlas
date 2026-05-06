"""In-memory graph composed from manifests."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Iterable

from .models import Edge, Manifest


@dataclass(frozen=True)
class FieldNode:
    schemaFile: str
    path: str
    business_key: str | None
    type_fqn: str | None


@dataclass
class MapperNode:
    mapper_id: str
    mapper_kind: str
    project_id: str
    repo_id: str
    pair_id: str
    edges: list[Edge] = field(default_factory=list)


@dataclass
class Graph:
    fields: dict[tuple[str, str], FieldNode] = field(default_factory=dict)
    mappers: dict[str, MapperNode] = field(default_factory=dict)
    edges: list[Edge] = field(default_factory=list)
    edges_by_business_key: dict[str, list[Edge]] = field(default_factory=lambda: defaultdict(list))


def build(manifests: Iterable[Manifest], business_keys_by_schema: dict[str, dict[str, str]]) -> Graph:
    g = Graph()

    def upsert_field(schema_file: str, path: str, type_fqn: str | None) -> FieldNode:
        key = (schema_file, path)
        if key not in g.fields:
            bk_map = business_keys_by_schema.get(schema_file, {})
            g.fields[key] = FieldNode(
                schemaFile=schema_file,
                path=path,
                business_key=bk_map.get(path),
                type_fqn=type_fqn,
            )
        return g.fields[key]

    for m in manifests:
        for e in m.edges:
            mapper = g.mappers.get(e.mapperId)
            if mapper is None:
                mapper = MapperNode(
                    mapper_id=e.mapperId,
                    mapper_kind=e.mapperKind,
                    project_id=m.projectId,
                    repo_id=m.repoId,
                    pair_id=m.pairId,
                )
                g.mappers[e.mapperId] = mapper
            mapper.edges.append(e)

            if e.source is not None:
                upsert_field(e.source.schemaFile, e.source.path, e.source.type)
            upsert_field(e.target.schemaFile, e.target.path, e.target.type)

            g.edges.append(e)

            target_bk = g.fields[(e.target.schemaFile, e.target.path)].business_key
            if target_bk:
                g.edges_by_business_key[target_bk].append(e)
            if e.source is not None:
                source_bk = g.fields[(e.source.schemaFile, e.source.path)].business_key
                if source_bk and source_bk != target_bk:
                    g.edges_by_business_key[source_bk].append(e)

    return g
