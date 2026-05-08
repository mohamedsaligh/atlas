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


def test_multihop_qualifier_to_static_helper_to_param_chain(tmp_path, monkeypatch):
    """N-deep resolver chain: qualifier method delegates into a static helper,
    which dereferences a parameter that was passed as a getter chain on the
    caller's source. The resolver must thread the path prefix through every
    hop and recover the complete source path on the final edge.

    Pattern:
        target.setAgentBic(qualifiers.getAgentCpa(src.getTxInfo()))
        QualifierDefinitions.getAgentCpa(txInfo) {
            return MapperQualifierUtil.bicFromInst(txInfo.getFinancialInstId());
        }
        MapperQualifierUtil.bicFromInst(fi) { return fi.getBic(); }

    Expected: agentBic <- txInfo.financialInstId.bic on Mt103.json,
    with a 2-step trail: static_call (inner) then qualifier (outer).
    """
    monkeypatch.setenv("HOME", str(tmp_path))
    multihop_cfg = REPO / "examples" / "atlas.multihop.yml"
    cfg = _cfg.load_config(multihop_cfg)
    cfg_dir = multihop_cfg.parent.resolve()
    results = _extract.run_extract(cfg, cfg_dir, file_timeout_s=10.0)
    edges = [e for r in results.values() for e in r.edges]
    assert len(edges) == 1, f"expected exactly one multihop edge, got {edges!r}"

    e = edges[0]
    assert e.target.path == "agentBic"
    assert e.source is not None
    assert e.source.schema_id == "Mt103.json"
    assert e.source.path == "txInfo.financialInstId.bic"
    assert e.kind == "qualifier"

    # Trail records both hops in resolution order: inner static_call first,
    # outer qualifier last.
    trail_kinds = [step.kind for step in e.trail]
    assert "static_call" in trail_kinds
    assert "qualifier" in trail_kinds
    assert e.trail[-1].kind == "qualifier"
    assert e.trail[-1].helper_fqn.endswith(
        "QualifierDefinitions.getAgentCpa"
    )
    inner_static = next(s for s in e.trail if s.kind == "static_call")
    assert inner_static.helper_fqn.endswith("MapperQualifierUtil.bicFromInst")


def test_local_var_init_expression_chasing(tmp_path, monkeypatch):
    """Bare identifier RHS that names a method-local var must be chased into
    its initialiser to recover the source path."""
    monkeypatch.setenv("HOME", str(tmp_path))
    locals_cfg = REPO / "examples" / "atlas.locals.yml"
    cfg = _cfg.load_config(locals_cfg)
    cfg_dir = locals_cfg.parent.resolve()
    results = _extract.run_extract(cfg, cfg_dir, file_timeout_s=10.0)
    edges = [e for r in results.values() for e in r.edges]
    by_target = {e.target.path: e for e in edges}

    e = by_target["channelName"]
    assert e.source is not None
    assert e.source.path == "header.channelName"
    assert e.kind == "rename"

    e = by_target["channelFormat"]
    assert e.source is not None
    assert e.source.path == "header.channelFormat"
