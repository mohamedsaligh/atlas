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
from .routers import coverage, entry_points, fields, health, impact, snapshot
from .settings import Settings


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build a fully-wired FastAPI app.

    Pass ``settings`` to override env-var-driven defaults (used by tests).
    Returned app is safe to mount under uvicorn or any ASGI server.
    """
    cfg = settings or Settings()

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

    if cfg.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=cfg.cors_origins,
            allow_credentials=True,
            allow_methods=["GET"],
            allow_headers=["*"],
        )

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

    return app
