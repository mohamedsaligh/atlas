"""End-to-end extractor test on tiny-mapstruct fixture."""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

from atlas import config as _cfg
from atlas import db as _db
from atlas import extract as _extract


REPO = Path(__file__).resolve().parents[1]
CFG = REPO / "examples" / "atlas.yml"


def test_tiny_mapstruct_extraction(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))  # isolate ~/.atlas
    cfg = _cfg.load_config(CFG)
    db_path = tmp_path / "atlas.db"
    monkeypatch.setattr(cfg, "__class__", cfg.__class__)
    conn = _db.open_db(db_path)
    _db.reset(conn)

    cfg_dir = CFG.parent.resolve()
    bk = _extract._build_business_keys(cfg, cfg_dir)
    results = _extract.run_extract(cfg, cfg_dir, file_timeout_s=10.0)
    atlas_sha = _extract.compute_atlas_sha(cfg, cfg_dir, results)
    _extract.persist(conn, cfg, cfg_dir, results, bk, atlas_sha)

    cur = conn.cursor()
    edges = cur.execute(
        "SELECT target_field_id, source_field_id, kind FROM edge ORDER BY id"
    ).fetchall()
    assert len(edges) == 4

    target_paths = {e[0].split("#")[1] for e in edges}
    assert "dbtrAcct.iban" in target_paths
    assert "cdtrAcct.iban" in target_paths
    assert "txnRef" in target_paths
    assert "channel" in target_paths

    # Helper recursion: dbtrAcct.iban must come from field50K, not just field50K-equivalent
    by_target = {e[0].split("#")[1]: e for e in edges}
    assert by_target["dbtrAcct.iban"][1].endswith("#field50K")
    assert by_target["cdtrAcct.iban"][1].endswith("#field59")

    # Constant edge has no source.
    assert by_target["channel"][1] is None
    assert by_target["channel"][2] == "constant"


def test_determinism(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    cfg = _cfg.load_config(CFG)
    cfg_dir = CFG.parent.resolve()
    r1 = _extract.run_extract(cfg, cfg_dir, file_timeout_s=10.0)
    r2 = _extract.run_extract(cfg, cfg_dir, file_timeout_s=10.0)
    assert _extract.compute_atlas_sha(cfg, cfg_dir, r1) == _extract.compute_atlas_sha(cfg, cfg_dir, r2)

    edges_1 = sorted(
        ((e.target.path, e.source.path if e.source else None, e.kind) for r in r1.values() for e in r.edges)
    )
    edges_2 = sorted(
        ((e.target.path, e.source.path if e.source else None, e.kind) for r in r2.values() for e in r.edges)
    )
    assert edges_1 == edges_2
