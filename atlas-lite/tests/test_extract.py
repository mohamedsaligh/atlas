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
QUAL_CFG = REPO / "examples" / "atlas.qualifier.yml"


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


def test_qualifier_and_static_helper_following(tmp_path, monkeypatch):
    """The resolver chain must follow into qualifier method bodies and static
    helper bodies, producing edges with the underlying source path and a
    resolution trail."""
    monkeypatch.setenv("HOME", str(tmp_path))
    cfg = _cfg.load_config(QUAL_CFG)
    cfg_dir = QUAL_CFG.parent.resolve()
    bk = _extract._build_business_keys(cfg, cfg_dir)
    results = _extract.run_extract(cfg, cfg_dir, file_timeout_s=10.0)

    edges = [e for r in results.values() for e in r.edges]
    by_target = {e.target.path: e for e in edges}

    # Direct getter — no resolver trail.
    assert by_target["iban"].source is not None
    assert by_target["iban"].source.path == "field50K"
    assert by_target["iban"].kind == "rename"
    assert by_target["iban"].trail == ()

    # Qualifier following — trail records the helper FQN.
    e = by_target["txnRef"]
    assert e.source is not None
    assert e.source.path == "field20"
    assert e.kind == "qualifier"
    assert len(e.trail) >= 1
    assert e.trail[-1].kind == "qualifier"
    assert e.trail[-1].helper_fqn.endswith("QualifierDefinitions.referenceEndToEndIdentification")

    e = by_target["beneficiary"]
    assert e.source is not None
    assert e.source.path == "field59"
    assert e.kind == "qualifier"

    # Static helper following.
    e = by_target["purpose"]
    assert e.source is not None
    assert e.source.path == "field70"
    assert e.kind == "static_call"
    assert e.trail[-1].kind == "static_call"
    assert e.trail[-1].helper_fqn.endswith("PurposeUtil.extract")

    # Constant.
    assert by_target["channel"].source is None
    assert by_target["channel"].kind == "constant"
