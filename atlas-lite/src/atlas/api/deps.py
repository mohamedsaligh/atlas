"""Dependency-injection helpers wired into FastAPI's `Depends` graph.

Centralising DI here keeps routers thin: they declare
``conn = Depends(get_db)`` and don't care how the SQLite connection is
opened, scoped, or torn down. Swapping the storage backend later
becomes a one-file change.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from pathlib import Path

from fastapi import Depends, Request

from .settings import Settings


def get_settings(request: Request) -> Settings:
    """Settings instance attached to the FastAPI app at startup."""
    settings: Settings = request.app.state.settings
    return settings


def get_db(
    settings: Settings = Depends(get_settings),
) -> Iterator[sqlite3.Connection]:
    """One read-only SQLite connection per request.

    Read-only mode is enforced via SQLite URI flags so a misbehaving
    handler cannot mutate the snapshot — the contract this API holds
    out to clients.
    """
    conn = _open_readonly(settings.resolved_db_path)
    try:
        yield conn
    finally:
        conn.close()


def _open_readonly(path: Path) -> sqlite3.Connection:
    if not path.is_file():
        raise FileNotFoundError(
            f"Atlas DB not found at {path!s}. Run `atlas extract -c atlas.yml --full` first."
        )
    uri = f"file:{path}?mode=ro"
    conn = sqlite3.connect(uri, uri=True, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only = ON")
    return conn
