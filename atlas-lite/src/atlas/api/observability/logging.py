"""Structured JSON logging.

The formatter emits one JSON object per record so log aggregators
(Datadog, ELK, Splunk) ingest it without regex parsers. The X-Request-Id
contextvar (set by ``RequestIdMiddleware``) is included automatically
when present, giving every log line a way to be joined with its
upstream / downstream peers.
"""

from __future__ import annotations

import json
import logging
import sys
import time
from typing import Any

from ..middleware.request_id import current_request_id


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(record.created))
            + f".{int(record.msecs):03d}Z",
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        rid = current_request_id()
        if rid:
            payload["request_id"] = rid
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        for k, v in record.__dict__.items():
            if k.startswith("_") or k in _LOGRECORD_RESERVED:
                continue
            payload[k] = v
        return json.dumps(payload, default=str, sort_keys=True)


class ConsoleFormatter(logging.Formatter):
    """Terse human-readable formatter for dev use."""

    def format(self, record: logging.LogRecord) -> str:
        rid = current_request_id() or "-"
        return (
            f"{time.strftime('%H:%M:%S', time.gmtime(record.created))} "
            f"{record.levelname:<5} [{rid[:8]}] {record.name} {record.getMessage()}"
        )


def configure(*, level: str = "INFO", fmt: str = "json") -> None:
    """Install a single stream handler at the chosen level + format.

    Idempotent: subsequent calls replace the previous handler so unit
    tests can re-configure between runs without piling up duplicates.
    """
    root = logging.getLogger()
    for h in list(root.handlers):
        root.removeHandler(h)

    handler = logging.StreamHandler(sys.stdout)
    if fmt == "json":
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(ConsoleFormatter())
    root.addHandler(handler)
    root.setLevel(level.upper())
    # Keep uvicorn's noisy access logs in line with our format.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logging.getLogger(name).handlers = []
        logging.getLogger(name).propagate = True


_LOGRECORD_RESERVED: frozenset[str] = frozenset(
    vars(logging.LogRecord("", 0, "", 0, None, None, None)).keys()
) | {"message", "asctime"}
