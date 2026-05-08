"""HTTP routers grouped per resource. Each module exposes a `router`."""

from __future__ import annotations

from . import coverage, entry_points, fields, health, impact, snapshot

__all__ = ["coverage", "entry_points", "fields", "health", "impact", "snapshot"]
