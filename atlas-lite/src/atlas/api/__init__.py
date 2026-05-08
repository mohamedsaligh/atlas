"""Atlas read API — FastAPI substrate over the SQLite snapshot.

The API is intentionally read-only. Extraction is a separate pipeline
(`atlas extract` / `atlas render`) producing a SQLite file; the API
serves it. This boundary keeps the runtime stateless, lets every
deployment scale horizontally, and makes the API safe to expose to
read-only clients (UI, BI, oncall dashboards).

Public entry point: :func:`create_app`. Everything else is internal.
"""

from __future__ import annotations

from .app import create_app

__all__ = ["create_app"]
