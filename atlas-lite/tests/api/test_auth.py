"""Auth middleware tests across the three modes."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from jose import jwt

from atlas.api import create_app
from atlas.api.settings import Settings


def _client(snapshot_db: Path, **overrides) -> TestClient:
    settings = Settings(db_path=snapshot_db, **overrides)
    return TestClient(create_app(settings=settings))


def test_disabled_mode_lets_everything_through(snapshot_db):
    c = _client(snapshot_db, auth_mode="disabled")
    assert c.get("/api/v1/coverage").status_code == 200


def test_shared_secret_blocks_without_token(snapshot_db):
    c = _client(snapshot_db, auth_mode="shared_secret", auth_shared_secret="dev-only-secret")
    r = c.get("/api/v1/coverage")
    assert r.status_code == 401
    assert r.headers.get("WWW-Authenticate") == "Bearer"
    assert r.json()["title"] == "Unauthorized"


def test_shared_secret_admits_valid_token(snapshot_db):
    secret = "dev-only-secret"
    c = _client(snapshot_db, auth_mode="shared_secret", auth_shared_secret=secret)
    token = jwt.encode({"sub": "alice"}, secret, algorithm="HS256")
    r = c.get("/api/v1/coverage", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200


def test_shared_secret_rejects_wrong_signature(snapshot_db):
    c = _client(snapshot_db, auth_mode="shared_secret", auth_shared_secret="real-secret")
    bad = jwt.encode({"sub": "alice"}, "wrong-secret", algorithm="HS256")
    r = c.get("/api/v1/coverage", headers={"Authorization": f"Bearer {bad}"})
    assert r.status_code == 401


def test_health_remains_unauthenticated(snapshot_db):
    c = _client(snapshot_db, auth_mode="shared_secret", auth_shared_secret="dev-only-secret")
    assert c.get("/api/v1/health").status_code == 200
    assert c.get("/api/v1/openapi.json").status_code == 200


def test_invalid_auth_mode_raises_at_startup(snapshot_db):
    with pytest.raises(ValueError):
        _client(snapshot_db, auth_mode="bogus")


def test_shared_secret_mode_requires_secret(snapshot_db):
    with pytest.raises(ValueError):
        _client(snapshot_db, auth_mode="shared_secret", auth_shared_secret=None)
