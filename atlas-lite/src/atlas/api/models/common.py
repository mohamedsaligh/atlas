"""Shared response building blocks: pagination envelope, scope, errors."""

from __future__ import annotations

from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T")


class Scope(BaseModel):
    """Routing dimensions on a mapper / entry-point. None means "applies
    to all values of this dimension" (i.e., the COMMON layer)."""

    model_config = ConfigDict(frozen=True)

    common: bool = False
    country: str | None = None
    clearing: str | None = None
    product: str | None = None
    field_group: str | None = None


class Page(BaseModel, Generic[T]):
    """Standard pagination envelope. Stable shape across all list endpoints."""

    model_config = ConfigDict(frozen=True)

    items: list[T]
    page: int = Field(ge=1)
    size: int = Field(ge=1)
    total: int = Field(ge=0)


class ProblemDetail(BaseModel):
    """RFC 7807 error envelope. Returned on 4xx / 5xx."""

    model_config = ConfigDict(frozen=True)

    type: str = "about:blank"
    title: str
    status: int
    detail: str | None = None
    instance: str | None = None
