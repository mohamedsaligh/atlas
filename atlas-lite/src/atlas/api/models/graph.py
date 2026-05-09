"""Force-graph response model.

Compact node-link shape consumed by the frontend's react-force-graph
view. Sized for direct JSON serialization at 5–20k nodes; the frontend
filters and lazy-expands beyond that.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict


NodeKind = Literal["entry_point", "field", "schema"]
LinkKind = Literal["reads", "writes", "spans"]


class GraphNode(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    label: str
    kind: NodeKind
    schema_id: str | None = None
    country: str | None = None
    clearing: str | None = None
    product: str | None = None
    edge_count: int | None = None
    resolution_percent: float | None = None


class GraphLink(BaseModel):
    model_config = ConfigDict(frozen=True)

    source: str
    target: str
    kind: LinkKind


class GraphResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    nodes: list[GraphNode]
    links: list[GraphLink]
    truncated: bool
    """True when the requested scope exceeded ``limit`` and the response
    was capped. Clients should display a "narrow your scope" hint."""
