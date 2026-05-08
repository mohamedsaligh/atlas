"""Black-box tests for the read API.

Each test runs through ``TestClient`` against a real SQLite snapshot
built from the multihop fixture, so it exercises the full DI graph,
routing, model serialization, and error handling — not mocks.
"""

from __future__ import annotations


def test_health_returns_snapshot_identity(client):
    r = client.get("/api/v1/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["atlas_sha"]
    assert body["extractor_version"]
    assert body["snapshot_built_at"]


def test_snapshot_endpoint(client):
    r = client.get("/api/v1/snapshot")
    assert r.status_code == 200
    body = r.json()
    assert body["edge_count"] == 1
    assert body["mapper_count"] == 1
    assert body["extractor_version"]


def test_coverage_list(client):
    r = client.get("/api/v1/coverage")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 1
    item = body["items"][0]
    assert item["repo_id"] == "payment-service"
    assert item["pair_id"] == "multihop_to_local"
    assert item["coverage_percent"] == 100.0
    assert item["unmatched"] == []


def test_entry_points_list_is_paginated(client):
    r = client.get("/api/v1/entry-points")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 1
    assert body["page"] == 1
    assert body["size"] == 50
    ep = body["items"][0]
    assert ep["class_fqn"].endswith("MultihopMapperImpl")
    assert ep["method_name"] == "toLocal"
    assert ep["resolution_percent"] == 100.0
    assert ep["edge_count"] == 1


def test_entry_point_detail_includes_helper_bodies(client):
    list_resp = client.get("/api/v1/entry-points").json()
    ep_id = list_resp["items"][0]["id"]
    r = client.get(f"/api/v1/entry-points/{ep_id}")
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == ep_id
    assert len(body["edges"]) == 1
    assert body["edges"][0]["target_path"] == "agentBic"
    assert body["edges"][0]["source_path"] == "txInfo.financialInstId.bic"
    fqns = {h["fqn"] for h in body["helpers"]}
    assert "com.x.payment.qualifier.QualifierDefinitions.getAgentCpa" in fqns
    assert "com.x.payment.util.MapperQualifierUtil.bicFromInst" in fqns
    # Helper body is verbatim, not summarised.
    bodies = "\n".join(h["body"] for h in body["helpers"])
    assert "MapperQualifierUtil.bicFromInst" in bodies
    assert "return fi.getBic();" in bodies


def test_entry_point_detail_404(client):
    r = client.get("/api/v1/entry-points/nonexistent")
    assert r.status_code == 404
    body = r.json()
    assert body["status"] == 404
    assert body["title"] == "Not Found"


def test_impact_endpoint(client):
    r = client.get(
        "/api/v1/impact",
        params={"schema": "Mt103.json", "path": "txInfo.financialInstId.bic"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 1
    item = body["items"][0]
    assert item["target_path"] == "agentBic"
    assert item["kind"] == "qualifier"


def test_impact_subtree_match(client):
    """Subtree query: a parent path includes descendants."""
    r = client.get(
        "/api/v1/impact",
        params={"schema": "Mt103.json", "path": "txInfo.financialInstId"},
    )
    assert r.status_code == 200
    assert r.json()["total"] == 1


def test_impact_unrelated_returns_empty(client):
    r = client.get(
        "/api/v1/impact",
        params={"schema": "Mt103.json", "path": "no.such.field"},
    )
    assert r.status_code == 200
    assert r.json()["total"] == 0
    assert r.json()["items"] == []


def test_field_find_404(client):
    r = client.get(
        "/api/v1/fields/find",
        params={"schema": "Mt103.json", "path": "no.such.field"},
    )
    assert r.status_code == 404
    body = r.json()
    assert body["status"] == 404


def test_field_find_edges_returns_partitioned_view(client):
    r = client.get(
        "/api/v1/fields/find/edges",
        params={"schema": "Mt103.json", "path": "txInfo.financialInstId.bic"},
    )
    assert r.status_code == 200
    body = r.json()
    assert "as_source" in body
    assert "as_target" in body
    assert len(body["as_source"]) == 1
    assert body["as_source"][0]["target_path"] == "agentBic"


def test_openapi_is_published(client):
    r = client.get("/api/v1/openapi.json")
    assert r.status_code == 200
    schema = r.json()
    assert schema["info"]["title"] == "Atlas Read API"
    assert "/api/v1/health" in schema["paths"]
    assert "/api/v1/entry-points" in schema["paths"]
    assert "/api/v1/impact" in schema["paths"]


def test_pagination_size_cap_is_enforced(client):
    r = client.get("/api/v1/entry-points", params={"size": 999999})
    assert r.status_code == 422
