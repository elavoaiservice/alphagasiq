"""Structured JSON logging (gap-closure follow-up): a shared configuration for
both the API process (`main.py`) and the worker process (`worker.py`), replacing
the bare `logging.basicConfig(level=logging.INFO)` `worker.py` used before. Every
log record renders as one JSON object per line (timestamp, level, logger name,
message, plus whatever request-scoped fields a caller attaches via `extra=`) --
the shape a real log aggregator (CloudWatch, Datadog, Loki, ...) expects to
parse, rather than free-text lines only a human reading a terminal can.

Deliberately no external dependency (`python-json-logger`, `structlog`, ...) for
what's a small, fixed set of fields -- consistent with this codebase's general
preference for a minimal purpose-built implementation over pulling in a library
for something this contained.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from typing import Any, Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

_REQUEST_FIELDS = ("request_id", "path", "method", "status_code", "duration_ms")
_request_logger = logging.getLogger("alphagasiq.request")


class JsonFormatter(logging.Formatter):
    """Renders one JSON object per log line."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        for key in _REQUEST_FIELDS:
            value = getattr(record, key, None)
            if value is not None:
                payload[key] = value
        return json.dumps(payload)


def configure_logging(*, log_level: str = "INFO") -> None:
    """Idempotent: safe to call from both `main.py`'s `create_app()` and
    `worker.py`'s module scope without accumulating duplicate handlers across
    repeated calls (e.g. `create_app()` invoked more than once in a test
    session, or `AppState.reset_app_state()`)."""
    root = logging.getLogger()
    root.setLevel(log_level)
    if any(isinstance(h.formatter, JsonFormatter) for h in root.handlers):
        return
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root.handlers = [handler]


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Logs one JSON line per request (method, path, status, latency, a
    generated request id echoed back as `X-Request-ID`) via `JsonFormatter`
    above. Registered on the outer `FastAPI` app in `main.py`, so it sees
    every request including ones routed to the `/api/v1`-mounted sub-app."""

    async def dispatch(self, request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        request_id = str(uuid.uuid4())
        started = time.monotonic()
        response = await call_next(request)
        duration_ms = round((time.monotonic() - started) * 1000, 2)
        _request_logger.info(
            "request",
            extra={
                "request_id": request_id,
                "path": request.url.path,
                "method": request.method,
                "status_code": response.status_code,
                "duration_ms": duration_ms,
            },
        )
        response.headers["X-Request-ID"] = request_id
        return response
