"""Bearer-token authentication.

Three modes selected by ``Settings.auth_mode``:

* ``disabled`` — no auth (default; explicit so it's a deliberate choice).
* ``shared_secret`` — HS256 signed token, ``ATLAS_AUTH_SHARED_SECRET``.
  For dev environments and CI smoke tests.
* ``oidc`` — RS256/ES256 token signed by the IdP. Issuer and audience
  are checked against ``ATLAS_AUTH_OIDC_ISSUER`` /
  ``ATLAS_AUTH_OIDC_AUDIENCE``. The JWKS document is fetched lazily and
  cached for an hour.

On success ``request.state.principal`` carries the validated claims
dict. On failure the request is rejected with a 401 problem-detail
(handled by :mod:`atlas.api.errors`).
"""

from __future__ import annotations

import json
import time
import urllib.request
from dataclasses import dataclass
from typing import Any

from cachetools import TTLCache
from jose import jwt
from jose.exceptions import JWTError
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp

from ..models import ProblemDetail
from ..settings import Settings

# JWKS responses are stable for hours; cache by issuer URL.
_JWKS_CACHE: TTLCache[str, dict[str, Any]] = TTLCache(maxsize=8, ttl=3600)


@dataclass
class _Decision:
    ok: bool
    claims: dict[str, Any] | None = None
    detail: str | None = None


class AuthMiddleware(BaseHTTPMiddleware):
    """Validates the Authorization header and stashes claims on request."""

    PUBLIC_PATHS = ("/health", "/openapi.json", "/docs", "/redoc", "/metrics")

    def __init__(self, app: ASGIApp, settings: Settings) -> None:
        super().__init__(app)
        self.settings = settings

    async def dispatch(self, request: Request, call_next):  # type: ignore[no-untyped-def]
        if self.settings.auth_mode == "disabled":
            request.state.principal = None
            return await call_next(request)

        # Public paths that must remain reachable without a token —
        # liveness, schema docs, metrics. Anything else requires auth.
        path = request.url.path
        if any(path.endswith(p) or path == p for p in self.PUBLIC_PATHS):
            request.state.principal = None
            return await call_next(request)

        token = self._extract_token(request)
        if token is None:
            return _unauthorized("missing bearer token", path)

        decision = self._validate(token)
        if not decision.ok:
            return _unauthorized(decision.detail or "invalid token", path)

        request.state.principal = decision.claims
        return await call_next(request)

    @staticmethod
    def _extract_token(request: Request) -> str | None:
        auth = request.headers.get("Authorization", "")
        if not auth.lower().startswith("bearer "):
            return None
        return auth.split(" ", 1)[1].strip() or None

    def _validate(self, token: str) -> _Decision:
        s = self.settings
        try:
            if s.auth_mode == "shared_secret":
                claims = jwt.decode(
                    token,
                    key=s.auth_shared_secret or "",
                    algorithms=["HS256"],
                    audience=s.auth_oidc_audience,
                    options={"verify_aud": bool(s.auth_oidc_audience)},
                )
                return _Decision(ok=True, claims=claims)

            if s.auth_mode == "oidc":
                jwks = _load_jwks(s.auth_oidc_issuer or "")
                claims = jwt.decode(
                    token,
                    key=jwks,
                    algorithms=["RS256", "RS384", "RS512", "ES256", "ES384"],
                    audience=s.auth_oidc_audience,
                    issuer=s.auth_oidc_issuer,
                    options={"verify_aud": bool(s.auth_oidc_audience)},
                )
                return _Decision(ok=True, claims=claims)
        except JWTError as exc:
            return _Decision(ok=False, detail=f"jwt error: {exc}")

        return _Decision(ok=False, detail="unsupported auth mode")


def validate_settings(settings: Settings) -> None:
    """Fail fast at startup when the auth config is incoherent."""
    if settings.auth_mode not in ("disabled", "shared_secret", "oidc"):
        raise ValueError(
            f"unsupported auth_mode: {settings.auth_mode!r}. "
            "Expected one of: disabled, shared_secret, oidc."
        )
    if settings.auth_mode == "shared_secret" and not settings.auth_shared_secret:
        raise ValueError(
            "auth_mode=shared_secret requires ATLAS_AUTH_SHARED_SECRET."
        )
    if settings.auth_mode == "oidc" and not settings.auth_oidc_issuer:
        raise ValueError("auth_mode=oidc requires ATLAS_AUTH_OIDC_ISSUER.")


def _load_jwks(issuer: str) -> dict[str, Any]:
    if issuer in _JWKS_CACHE:
        return _JWKS_CACHE[issuer]
    discovery_url = issuer.rstrip("/") + "/.well-known/openid-configuration"
    config = _http_get_json(discovery_url)
    jwks_uri = config["jwks_uri"]
    jwks = _http_get_json(jwks_uri)
    _JWKS_CACHE[issuer] = jwks
    return jwks


def _http_get_json(url: str) -> dict[str, Any]:
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as resp:  # noqa: S310
        return json.loads(resp.read().decode("utf-8"))


def _unauthorized(detail: str, instance: str) -> JSONResponse:
    body = ProblemDetail(
        status=401, title="Unauthorized", detail=detail, instance=instance,
    )
    return JSONResponse(
        status_code=401,
        content=body.model_dump(),
        media_type="application/problem+json",
        headers={"WWW-Authenticate": "Bearer"},
    )


# Suppress unused-time-import on some interpreters.
_ = time
