"""Field-row response model."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class FieldRow(BaseModel):
    """One leaf in a schema. ``business_key`` and ``type`` come from
    the schema's annotations when present."""

    model_config = ConfigDict(frozen=True)

    id: str
    schema_id: str
    path: str
    business_key: str | None = None
    type: str | None = None
