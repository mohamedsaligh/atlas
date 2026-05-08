"""Centralised exception handlers — RFC 7807 problem-detail bodies."""

from __future__ import annotations

import logging

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from .models import ProblemDetail

log = logging.getLogger("atlas.api")


def install(app: FastAPI) -> None:
    """Wire all exception handlers onto the app."""

    @app.exception_handler(HTTPException)
    async def _http_exc(request: Request, exc: HTTPException) -> JSONResponse:
        return _problem(
            status_code=exc.status_code,
            title=_default_title(exc.status_code),
            detail=str(exc.detail) if exc.detail else None,
            instance=str(request.url.path),
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_exc(
        request: Request,
        exc: RequestValidationError,
    ) -> JSONResponse:
        return _problem(
            status_code=422,
            title="Unprocessable Entity",
            detail=str(exc.errors()),
            instance=str(request.url.path),
        )

    @app.exception_handler(FileNotFoundError)
    async def _missing_db(
        request: Request,
        exc: FileNotFoundError,
    ) -> JSONResponse:
        return _problem(
            status_code=503,
            title="Service Unavailable",
            detail=str(exc),
            instance=str(request.url.path),
        )

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        log.exception("unhandled error on %s", request.url.path)
        return _problem(
            status_code=500,
            title="Internal Server Error",
            detail=type(exc).__name__,
            instance=str(request.url.path),
        )


def _problem(
    *,
    status_code: int,
    title: str,
    detail: str | None,
    instance: str,
) -> JSONResponse:
    payload = ProblemDetail(
        status=status_code,
        title=title,
        detail=detail,
        instance=instance,
    )
    return JSONResponse(
        status_code=status_code,
        content=payload.model_dump(),
        media_type="application/problem+json",
    )


def _default_title(code: int) -> str:
    return {
        400: "Bad Request",
        401: "Unauthorized",
        403: "Forbidden",
        404: "Not Found",
        409: "Conflict",
        422: "Unprocessable Entity",
        429: "Too Many Requests",
        500: "Internal Server Error",
        503: "Service Unavailable",
    }.get(code, "Error")
