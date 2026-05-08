"""Observability — request id propagation, metrics endpoint, JSON logs."""

from __future__ import annotations

import json

from atlas.api.observability.logging import ConsoleFormatter, JsonFormatter


def test_request_id_is_echoed_when_provided(client):
    r = client.get("/api/v1/health", headers={"X-Request-Id": "abc-123"})
    assert r.headers["X-Request-Id"] == "abc-123"


def test_request_id_is_generated_when_absent(client):
    r = client.get("/api/v1/health")
    rid = r.headers.get("X-Request-Id")
    assert rid and len(rid) >= 8


def test_metrics_endpoint_exposes_prom_text(client):
    # Prime the counters by issuing a handful of requests.
    client.get("/api/v1/health")
    client.get("/api/v1/coverage")
    r = client.get("/api/v1/metrics")
    assert r.status_code == 200
    assert "atlas_http_requests_total" in r.text
    assert "atlas_http_request_duration_seconds" in r.text
    # Cardinality control: the entry-point detail route must be a
    # template label, not a concrete id, otherwise scrape size explodes.
    client.get("/api/v1/entry-points/some-id")
    r = client.get("/api/v1/metrics")
    assert "/api/v1/entry-points/{entry_point_id}" in r.text


def test_json_formatter_emits_valid_json():
    import logging

    rec = logging.LogRecord(
        name="atlas.test",
        level=logging.INFO,
        pathname="x.py",
        lineno=1,
        msg="hello %s",
        args=("world",),
        exc_info=None,
    )
    out = JsonFormatter().format(rec)
    parsed = json.loads(out)
    assert parsed["level"] == "INFO"
    assert parsed["message"] == "hello world"
    assert parsed["logger"] == "atlas.test"
    assert "ts" in parsed


def test_console_formatter_is_terse():
    import logging

    rec = logging.LogRecord(
        name="atlas.test",
        level=logging.WARNING,
        pathname="x.py",
        lineno=1,
        msg="boom",
        args=(),
        exc_info=None,
    )
    out = ConsoleFormatter().format(rec)
    assert "WARN" in out
    assert "boom" in out
