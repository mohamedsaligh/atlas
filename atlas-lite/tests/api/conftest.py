"""Test fixtures for the API. Builds a real SQLite snapshot from the
multihop fixture, then hands tests a FastAPI app pointed at it."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from atlas import config as _cfg
from atlas import db as _db
from atlas import extract as _extract
from atlas.api import create_app
from atlas.api.settings import Settings

REPO = Path(__file__).resolve().parents[2]
MULTIHOP_CFG = REPO / "examples" / "atlas.multihop.yml"


@pytest.fixture()
def snapshot_db(tmp_path, monkeypatch) -> Path:
    """Run extract + persist on the multihop fixture, return DB path."""
    monkeypatch.setenv("HOME", str(tmp_path))
    cfg = _cfg.load_config(MULTIHOP_CFG)
    cfg_dir = MULTIHOP_CFG.parent.resolve()
    db_path = tmp_path / "atlas.db"
    conn = _db.open_db(db_path)
    _db.reset(conn)
    bk = _extract._build_business_keys(cfg, cfg_dir)
    results = _extract.run_extract(cfg, cfg_dir, file_timeout_s=10.0)
    atlas_sha = _extract.compute_atlas_sha(cfg, cfg_dir, results)
    _extract.persist(conn, cfg, cfg_dir, results, bk, atlas_sha)
    conn.close()
    return db_path


@pytest.fixture()
def client(snapshot_db: Path) -> TestClient:
    settings = Settings(db_path=snapshot_db)
    app = create_app(settings=settings)
    return TestClient(app)
