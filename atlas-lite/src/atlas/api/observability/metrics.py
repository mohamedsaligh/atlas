"""Prometheus metrics.

Exposes:
* ``atlas_http_requests_total{method, route, status}`` — counter
* ``atlas_http_request_duration_seconds{method, route, status}`` — histogram

The middleware uses the *route template* (e.g.
``/api/v1/entry-points/{entry_point_id}``) rather than the raw URL to
keep cardinality bounded — high-cardinality labels are the standard
Prometheus footgun.
"""

from __future__ import annotations

import time

from fastapi import APIRouter, Response
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    Counter,
    Histogram,
    generate_latest,
)
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.routing import Match
from starlette.types import ASGIApp

REQ_COUNTER = Counter(
    "atlas_http_requests_total",
    "Total HTTP requests, labeled by method, route template, and status.",
    ("method", "route", "status"),
)
REQ_DURATION = Histogram(
    "atlas_http_request_duration_seconds",
    "HTTP request duration, labeled by method, route template, and status.",
    ("method", "route", "status"),
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0),
)


class MetricsMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):  # type: ignore[no-untyped-def]
        start = time.perf_counter()
        response = await call_next(request)
        elapsed = time.perf_counter() - start
        route = _route_template(request) or request.url.path
        labels = (request.method, route, str(response.status_code))
        REQ_COUNTER.labels(*labels).inc()
        REQ_DURATION.labels(*labels).observe(elapsed)
        return response


router = APIRouter(tags=["observability"])


@router.get(
    "/metrics",
    summary="Prometheus exposition (text/plain)",
    response_class=Response,
)
def metrics() -> Response:
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


def _route_template(request: Request) -> str | None:
    """Resolve the matching route template so labels stay low-cardinality."""
    for route in request.app.routes:
        match, _ = route.matches(request.scope)
        if match is Match.FULL:
            return getattr(route, "path", None)
    return None
