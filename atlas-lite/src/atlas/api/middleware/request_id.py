"""X-Request-Id propagation. Honors an inbound id when present and
generates a UUID when not, then echoes it on the response so client and
server share a single trace handle. The id is also stashed in a
contextvar so structured logs surface it without router cooperation.
"""

from __future__ import annotations

import contextvars
import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp

REQUEST_ID_CTX: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "atlas_request_id",
    default=None,
)


class RequestIdMiddleware(BaseHTTPMiddleware):
    HEADER = "X-Request-Id"

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(self, request: Request, call_next):  # type: ignore[no-untyped-def]
        rid = request.headers.get(self.HEADER) or uuid.uuid4().hex
        token = REQUEST_ID_CTX.set(rid)
        request.state.request_id = rid
        try:
            response: Response = await call_next(request)
        finally:
            REQUEST_ID_CTX.reset(token)
        response.headers[self.HEADER] = rid
        return response


def current_request_id() -> str | None:
    return REQUEST_ID_CTX.get()
