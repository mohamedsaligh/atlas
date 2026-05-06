"""End-to-end smoke: aggregator on the fixture-generated manifest.

Skipped when manifests don't exist yet (CI runs `mvn atlas:extract` first).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from atlas_aggregator import business_key, collect, graph, render_markdown
from atlas_aggregator.config import load_config

REPO = Path(__file__).resolve().parents[3]
CONFIG = REPO / "atlas.yml"
FIXTURE_MANIFEST = (
    REPO
    / "examples/fixtures/payments/source/payment-service/target/atlas/manifests/mt103_to_local.manifest.json"
)


@pytest.mark.skipif(not FIXTURE_MANIFEST.is_file(), reason="run mvn atlas:extract first")
def test_aggregator_builds_kb_from_fixture(tmp_path: Path):
    cfg = load_config(CONFIG)
    config_dir = CONFIG.parent

    manifests = collect.collect_manifests(cfg, config_dir)
    assert len(manifests) == 1
    m = manifests[0]
    assert m.pairId == "mt103_to_local"
    assert len(m.edges) >= 10  # mapstruct + plain-java together

    bk = {
        ref.schemaFile: business_key.parse(config_dir / ref.schemaFile, ref.schemaKind)
        for ref in (m.source, m.target)
    }
    assert "DebtorIBAN" in bk[m.target.schemaFile].values()

    g = graph.build([m], bk)
    bk_values = {f.business_key for f in g.fields.values() if f.business_key}
    assert "DebtorIBAN" in bk_values
    assert any(
        g.fields[(e.target.schemaFile, e.target.path)].business_key == "DebtorIBAN"
        for e in g.edges
    )

    written = render_markdown.render(g, tmp_path)
    assert all(p.exists() for p in written)
    assert all("Field-level edges" in p.read_text() for p in written)
