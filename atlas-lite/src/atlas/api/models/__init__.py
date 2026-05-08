"""Pydantic v2 response models for the Atlas read API.

Models are split per resource so OpenAPI groups them cleanly in the
generated docs. Every model is read-only and frozen at the boundary —
they describe a snapshot, not a mutable state.
"""

from __future__ import annotations

from .common import Page, ProblemDetail, Scope
from .coverage import CoverageRow
from .edge import EdgeRow, EdgeWithResolution, ResolutionStep
from .entry_point import EntryPointDetail, EntryPointSummary
from .field import FieldRow
from .helper import HelperBody
from .impact import ImpactRow
from .snapshot import HealthResponse, SnapshotInfo

__all__ = [
    "CoverageRow",
    "EdgeRow",
    "EdgeWithResolution",
    "EntryPointDetail",
    "EntryPointSummary",
    "FieldRow",
    "HealthResponse",
    "HelperBody",
    "ImpactRow",
    "Page",
    "ProblemDetail",
    "ResolutionStep",
    "Scope",
    "SnapshotInfo",
]
