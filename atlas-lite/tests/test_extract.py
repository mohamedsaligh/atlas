"""End-to-end extractor test on tiny-mapstruct fixture."""

from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path

from atlas import config as _cfg
from atlas import db as _db
from atlas import extract as _extract
from atlas import render as _render


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


def test_entry_point_markdown_inlines_helper_bodies(tmp_path, monkeypatch):
    """BA-grade Markdown: per-entry-point .md inlines every helper body the
    resolver walked through, line-anchored to source. Multihop fixture
    exercises a 2-hop chain (qualifier → static_call) so both helper bodies
    must appear under the same entry-point page."""
    monkeypatch.setenv("HOME", str(tmp_path))
    multihop_cfg = REPO / "examples" / "atlas.multihop.yml"
    cfg = _cfg.load_config(multihop_cfg)
    cfg_dir = multihop_cfg.parent.resolve()

    db_path = tmp_path / "atlas.db"
    conn = _db.open_db(db_path)
    _db.reset(conn)

    bk = _extract._build_business_keys(cfg, cfg_dir)
    results = _extract.run_extract(cfg, cfg_dir, file_timeout_s=10.0)
    atlas_sha = _extract.compute_atlas_sha(cfg, cfg_dir, results)
    _extract.persist(conn, cfg, cfg_dir, results, bk, atlas_sha)

    site = tmp_path / "atlas-kb"
    counts = _render.render_site(conn, site)
    assert counts["entry_point_md"] >= 1
    assert counts["index_md"] == 1

    ep_dir = site / "services" / "payment-service" / "multihop_to_local" / "entry-points"
    md_files = list(ep_dir.glob("*.md"))
    assert len(md_files) == 1, f"expected one entry-point md, got {md_files!r}"
    body = md_files[0].read_text(encoding="utf-8")

    # Frontmatter — pivots downstream tooling.
    assert body.startswith("---\n")
    assert f"atlas_sha: {atlas_sha}" in body
    assert "entry_point_id:" in body
    assert "class_fqn: com.x.payment.mapper.common.MultihopMapperImpl" in body

    # Edge table — exactly one row, with the recovered N-deep source path.
    # Column header changed to "source / value" so a constant / construction
    # row can surface its literal expression instead of an opaque placeholder.
    assert "| source / value | → | target path |" in body
    assert "| → | `agentBic` |" in body
    assert "`txInfo.financialInstId.bic`" in body

    # Helper bodies — both hops inlined verbatim, line-anchored.
    assert "### `com.x.payment.qualifier.QualifierDefinitions.getAgentCpa`" in body
    assert "### `com.x.payment.util.MapperQualifierUtil.bicFromInst`" in body
    assert "MapperQualifierUtil.bicFromInst(txInfo.getFinancialInstId())" in body
    assert "return fi.getBic();" in body
    # Line anchors must be exact — these are the actual line ranges of the
    # two helpers in the fixture, and the BA-readable invariant is that the
    # rendered range matches the source-of-truth file.
    assert "QualifierDefinitions.java:L8-L13" in body
    assert "MapperQualifierUtil.java:L6-L8" in body

    # Top-level index lists the entry point.
    index = (site / "entry-points" / "index.md").read_text(encoding="utf-8")
    assert "MultihopMapperImpl" in index
    assert "toLocal" in index


def test_coverage_populated(tmp_path, monkeypatch):
    """Coverage % must populate at pair-level and per-entry-point. Multihop
    fixture: LocalDomain has 1 leaf (agentBic), the entry point emits 1
    edge writing it → 100.0% on both axes."""
    monkeypatch.setenv("HOME", str(tmp_path))
    multihop_cfg = REPO / "examples" / "atlas.multihop.yml"
    cfg = _cfg.load_config(multihop_cfg)
    cfg_dir = multihop_cfg.parent.resolve()
    db_path = tmp_path / "atlas.db"
    conn = _db.open_db(db_path)
    _db.reset(conn)
    bk = _extract._build_business_keys(cfg, cfg_dir)
    results = _extract.run_extract(cfg, cfg_dir, file_timeout_s=10.0)
    atlas_sha = _extract.compute_atlas_sha(cfg, cfg_dir, results)
    _extract.persist(conn, cfg, cfg_dir, results, bk, atlas_sha)

    pair_pct, target_count, unmatched_json = conn.execute(
        "SELECT coverage_percent, target_field_count, unmatched_json FROM coverage"
    ).fetchone()
    assert target_count == 1
    assert pair_pct == 100.0
    assert json.loads(unmatched_json) == []

    # Per-EP resolution % — fraction of this EP's own edges that landed
    # on a real source schema path. Multihop has 1 edge, fully resolved.
    ep_pcts = [r[0] for r in conn.execute(
        "SELECT resolution_percent FROM entry_point"
    ).fetchall()]
    assert ep_pcts == [100.0]


def test_pair_coverage_with_unmatched(tmp_path, monkeypatch):
    """Coverage subtraction — pair-level coverage_percent must drop and
    unmatched_json must surface every target leaf the mapper does not write.
    Uses the tiny-mapstruct fixture: LocalDomain has 4 leaves, the mapper
    writes 4 of them. Patch a 5th synthetic leaf into business_keys to
    exercise the subtraction path without mutating the fixture file."""
    monkeypatch.setenv("HOME", str(tmp_path))
    cfg = _cfg.load_config(CFG)
    cfg_dir = CFG.parent.resolve()
    db_path = tmp_path / "atlas.db"
    conn = _db.open_db(db_path)
    _db.reset(conn)

    bk = _extract._build_business_keys(cfg, cfg_dir)
    # Inject a synthetic unwritten leaf into the target schema's
    # business_keys map. The mapper writes 4 of 5 leaves → 80% coverage.
    target_file = next(
        ref.file for pair in cfg.pairs for ref in pair.effective_targets()
    )
    from atlas.schemas import FieldAttrs
    bk[target_file]["unwrittenField"] = FieldAttrs(type_hint="string")

    results = _extract.run_extract(cfg, cfg_dir, file_timeout_s=10.0)
    atlas_sha = _extract.compute_atlas_sha(cfg, cfg_dir, results)
    _extract.persist(conn, cfg, cfg_dir, results, bk, atlas_sha)

    pct, target_count, unmatched_json = conn.execute(
        "SELECT coverage_percent, target_field_count, unmatched_json FROM coverage"
    ).fetchone()
    assert target_count == 5
    assert pct == 80.0
    assert json.loads(unmatched_json) == ["unwrittenField"]


def test_impact_query_returns_affected_targets(tmp_path, monkeypatch):
    """Reverse-edge BFS: changing Mt103:txInfo.financialInstId.bic must
    surface every edge writing that source path. Uses the same SQL the CLI
    runs so the test pins the impact contract."""
    monkeypatch.setenv("HOME", str(tmp_path))
    multihop_cfg = REPO / "examples" / "atlas.multihop.yml"
    cfg = _cfg.load_config(multihop_cfg)
    cfg_dir = multihop_cfg.parent.resolve()
    db_path = tmp_path / "atlas.db"
    conn = _db.open_db(db_path)
    _db.reset(conn)
    bk = _extract._build_business_keys(cfg, cfg_dir)
    results = _extract.run_extract(cfg, cfg_dir, file_timeout_s=10.0)
    atlas_sha = _extract.compute_atlas_sha(cfg, cfg_dir, results)
    _extract.persist(conn, cfg, cfg_dir, results, bk, atlas_sha)

    # Exact path
    rows = conn.execute(
        """SELECT tf.path, e.kind FROM edge e
           JOIN field sf ON e.source_field_id = sf.id
           JOIN field tf ON e.target_field_id = tf.id
           WHERE sf.schema_id = ? AND (sf.path = ? OR sf.path LIKE ? || '.%')""",
        ("Mt103.json", "txInfo.financialInstId.bic", "txInfo.financialInstId.bic"),
    ).fetchall()
    assert any(r == ("agentBic", "qualifier") for r in rows)

    # Subtree: prefix should include descendants too. Asking for the parent
    # `txInfo.financialInstId` should still surface the edge writing agentBic.
    rows_prefix = conn.execute(
        """SELECT tf.path FROM edge e
           JOIN field sf ON e.source_field_id = sf.id
           JOIN field tf ON e.target_field_id = tf.id
           WHERE sf.schema_id = ? AND (sf.path = ? OR sf.path LIKE ? || '.%')""",
        ("Mt103.json", "txInfo.financialInstId", "txInfo.financialInstId"),
    ).fetchall()
    assert any(r[0] == "agentBic" for r in rows_prefix)

    # Unrelated path returns empty.
    rows_none = conn.execute(
        """SELECT tf.path FROM edge e
           JOIN field sf ON e.source_field_id = sf.id
           JOIN field tf ON e.target_field_id = tf.id
           WHERE sf.schema_id = ? AND (sf.path = ? OR sf.path LIKE ? || '.%')""",
        ("Mt103.json", "nonexistent.path", "nonexistent.path"),
    ).fetchall()
    assert rows_none == []


def test_render_is_deterministic(tmp_path, monkeypatch):
    """The Markdown render must be byte-identical across repeated runs over
    the same SQLite snapshot. Determinism is a load-bearing invariant —
    without it, atlas-kb churn pollutes diffs and breaks the drift gate."""
    monkeypatch.setenv("HOME", str(tmp_path))
    multihop_cfg = REPO / "examples" / "atlas.multihop.yml"
    cfg = _cfg.load_config(multihop_cfg)
    cfg_dir = multihop_cfg.parent.resolve()

    db_path = tmp_path / "atlas.db"
    conn = _db.open_db(db_path)
    _db.reset(conn)
    bk = _extract._build_business_keys(cfg, cfg_dir)
    results = _extract.run_extract(cfg, cfg_dir, file_timeout_s=10.0)
    atlas_sha = _extract.compute_atlas_sha(cfg, cfg_dir, results)
    _extract.persist(conn, cfg, cfg_dir, results, bk, atlas_sha)

    site_a = tmp_path / "atlas-kb-a"
    site_b = tmp_path / "atlas-kb-b"
    _render.render_site(conn, site_a)
    _render.render_site(conn, site_b)

    files_a = sorted(p.relative_to(site_a) for p in site_a.rglob("*") if p.is_file())
    files_b = sorted(p.relative_to(site_b) for p in site_b.rglob("*") if p.is_file())
    assert files_a == files_b, "render produced different file sets across runs"

    for rel in files_a:
        a = (site_a / rel).read_bytes()
        b = (site_b / rel).read_bytes()
        assert a == b, f"render diverged at {rel}"


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
