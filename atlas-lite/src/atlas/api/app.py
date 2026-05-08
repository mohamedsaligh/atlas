"""FastAPI application factory.

Use :func:`create_app` from :mod:`atlas.api` rather than constructing
the app directly — the factory wires settings, middlewares, routers,
error handlers, and observability in a deterministic order.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .. import ATLAS_VERSION
from . import errors as _errors
from .middleware.auth import AuthMiddleware, validate_settings as _validate_auth
from .middleware.request_id import RequestIdMiddleware
from .observability import logging as _obs_logging
from .observability import metrics as _obs_metrics
from .routers import coverage, entry_points, fields, health, impact, snapshot
from .settings import Settings


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build a fully-wired FastAPI app.

    Pass ``settings`` to override env-var-driven defaults (used by tests).
    Returned app is safe to mount under uvicorn or any ASGI server.
    """
    cfg = settings or Settings()
    _validate_auth(cfg)

    app = FastAPI(
        title="Atlas Read API",
        version=ATLAS_VERSION,
        description=(
            "Read-only HTTP API over the Atlas SQLite snapshot. "
            "Powers the impact analysis CLI, the BA-facing UI, "
            "and the force-graph view."
        ),
        openapi_url=f"{cfg.api_prefix}/openapi.json",
        docs_url=f"{cfg.api_prefix}/docs",
        redoc_url=f"{cfg.api_prefix}/redoc",
    )
    # Settings are attached eagerly (not via lifespan) so synchronous
    # test clients see them without the explicit `with TestClient(...)`
    # context manager. Production uvicorn invocations work either way.
    app.state.settings = cfg

    # Configure logging once per process. Tests opt out via env so they
    # don't pollute pytest's capture; production calls this on cold start.
    _obs_logging.configure(level=cfg.log_level, fmt=cfg.log_format)

    # Middleware order matters: outermost executes first on the way in
    # and last on the way out. Request id outermost so every other
    # layer (logs, auth, metrics) can read it. Metrics inside auth so
    # 401s are recorded. CORS is outermost-of-outermost — it must run
    # before auth to permit pre-flight OPTIONS without a token.
    if cfg.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=cfg.cors_origins,
            allow_credentials=True,
            allow_methods=["GET", "OPTIONS"],
            allow_headers=["*"],
        )
    app.add_middleware(RequestIdMiddleware)
    app.add_middleware(AuthMiddleware, settings=cfg)
    app.add_middleware(_obs_metrics.MetricsMiddleware)

    _errors.install(app)

    for r in (
        health.router,
        snapshot.router,
        coverage.router,
        entry_points.router,
        impact.router,
        fields.router,
    ):
        app.include_router(r, prefix=cfg.api_prefix)

    if cfg.metrics_enabled:
        # /metrics lives at the prefix so a single ingress can route
        # it alongside the API; Prometheus scrapers configure the path
        # to match. Public — no auth, no app-level rate limit.
        app.include_router(_obs_metrics.router, prefix=cfg.api_prefix)

    return app
