"""Gap-closure item #2: observability -- structured JSON logging (always
active) and Sentry exception tracking (config-gated exactly like OIDC/SMTP/
Neo4j elsewhere in this codebase: unset `SENTRY_DSN`, every default dev/test
environment, means it is never initialized at all)."""

from __future__ import annotations

import json
import logging

from api_app.logging_config import JsonFormatter, configure_logging
from api_app.main import _init_sentry_if_configured
from config import Settings


def _make_record(**overrides) -> logging.LogRecord:
    defaults = dict(
        name="test.logger",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="hello %s",
        args=("world",),
        exc_info=None,
    )
    defaults.update(overrides)
    return logging.LogRecord(**defaults)


def test_json_formatter_renders_valid_json_with_required_fields():
    payload = json.loads(JsonFormatter().format(_make_record()))
    assert payload["level"] == "INFO"
    assert payload["logger"] == "test.logger"
    assert payload["message"] == "hello world"
    assert "timestamp" in payload


def test_json_formatter_includes_request_fields_when_present():
    record = _make_record(msg="request", args=())
    record.request_id = "abc-123"
    record.path = "/health"
    record.method = "GET"
    record.status_code = 200
    record.duration_ms = 1.23
    payload = json.loads(JsonFormatter().format(record))
    assert payload["request_id"] == "abc-123"
    assert payload["path"] == "/health"
    assert payload["method"] == "GET"
    assert payload["status_code"] == 200
    assert payload["duration_ms"] == 1.23


def test_json_formatter_omits_request_fields_when_absent():
    payload = json.loads(JsonFormatter().format(_make_record()))
    for key in ("request_id", "path", "method", "status_code", "duration_ms"):
        assert key not in payload


def test_configure_logging_is_idempotent():
    root = logging.getLogger()
    configure_logging(log_level="INFO")
    handler_count = len(root.handlers)
    configure_logging(log_level="INFO")
    assert len(root.handlers) == handler_count


def test_sentry_not_initialized_when_dsn_unset(monkeypatch):
    import sentry_sdk

    calls: list[dict] = []
    monkeypatch.setattr(sentry_sdk, "init", lambda **kwargs: calls.append(kwargs))
    _init_sentry_if_configured(Settings(sentry_dsn=None))
    assert calls == []


def test_sentry_initialized_when_dsn_set(monkeypatch):
    import sentry_sdk

    calls: list[dict] = []
    monkeypatch.setattr(sentry_sdk, "init", lambda **kwargs: calls.append(kwargs))
    _init_sentry_if_configured(
        Settings(sentry_dsn="https://public@o0.ingest.sentry.example.test/1", sentry_traces_sample_rate=0.25)
    )
    assert len(calls) == 1
    assert calls[0]["dsn"] == "https://public@o0.ingest.sentry.example.test/1"
    assert calls[0]["traces_sample_rate"] == 0.25
    assert len(calls[0]["integrations"]) == 2


def test_create_app_boots_and_logs_requests_when_sentry_unset():
    """The full test suite already proves `create_app()` behaves identically
    with `SENTRY_DSN` unset by continuing to boot and pass end-to-end; this
    additionally proves the request-logging middleware actually runs and
    stamps an `X-Request-ID` header on a real request/response round trip."""
    from fastapi.testclient import TestClient

    from api_app import state as state_module
    from api_app.main import app

    state_module.reset_app_state()
    with TestClient(app) as client:
        response = client.get("/health")
    assert response.status_code == 200
    assert "X-Request-ID" in response.headers
    state_module.reset_app_state()
