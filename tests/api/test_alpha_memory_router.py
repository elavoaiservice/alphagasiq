"""Milestone 5 (AlphaMemory): close_trade() -> MemoryRecord + LessonProposal, plus
GET /alpha/memory(/{id}), GET /alpha/memory/lessons(/{id}), POST /alpha/memory/lessons/{id}/review."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from .trade_test_helpers import create_deterministic_trade_idea, get_approval_for_trade


@pytest.fixture
def client():
    from api_app import state as state_module

    state_module.reset_app_state()
    from api_app.main import app

    with TestClient(app) as c:
        yield c
    state_module.reset_app_state()


def _admin_headers(client) -> dict:
    login = client.post(
        "/api/v1/auth/login", json={"email": "admin@alphagasiq.local", "password": "admin-dev-password"}
    )
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def _risk_headers(client) -> dict:
    login = client.post("/api/v1/auth/login", json={"email": "risk@alphagasiq.local", "password": "risk-dev-password"})
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def _close_a_trade(client, headers) -> str:
    trade = create_deterministic_trade_idea(client)
    approval = get_approval_for_trade(client, trade["trade_id"])
    client.post(
        f"/api/v1/approvals/{approval['id']}/action", json={"action": "APPROVE", "payload": {"quantity": 10}}, headers=headers
    )
    close = client.post(f"/api/v1/trade-ideas/{trade['trade_id']}/close", json={}, headers=headers)
    assert close.status_code == 200
    return trade["trade_id"]


def test_list_memory_requires_auth(client):
    r = client.get("/api/v1/alpha/memory")
    assert r.status_code == 401


def test_closing_a_trade_creates_a_memory_record_and_lesson_proposal(client):
    headers = _admin_headers(client)
    _close_a_trade(client, headers)

    memories = client.get("/api/v1/alpha/memory", headers=headers).json()
    assert len(memories) == 1
    memory = memories[0]
    assert memory["memory_type"] == "DECISION_MEMORY"
    assert memory["outcome_quadrant"] in (
        "GOOD_DECISION_GOOD_OUTCOME",
        "GOOD_DECISION_BAD_OUTCOME",
        "BAD_DECISION_GOOD_OUTCOME",
        "BAD_DECISION_BAD_OUTCOME",
    )

    detail = client.get(f"/api/v1/alpha/memory/{memory['id']}", headers=headers)
    assert detail.status_code == 200
    assert detail.json()["trade_id"] == memory["trade_id"]

    lessons = client.get("/api/v1/alpha/memory/lessons", headers=headers).json()
    assert len(lessons) == 1
    assert lessons[0]["memory_record_id"] == memory["id"]
    assert lessons[0]["status"] == "PENDING"


def test_get_unknown_memory_is_404(client):
    r = client.get(
        "/api/v1/alpha/memory/00000000-0000-0000-0000-000000000000", headers=_admin_headers(client)
    )
    assert r.status_code == 404


def test_get_unknown_lesson_is_404(client):
    r = client.get(
        "/api/v1/alpha/memory/lessons/00000000-0000-0000-0000-000000000000", headers=_admin_headers(client)
    )
    assert r.status_code == 404


def test_review_lesson_requires_alpha_memory_review_permission(client):
    admin_headers = _admin_headers(client)
    _close_a_trade(client, admin_headers)
    lesson_id = client.get("/api/v1/alpha/memory/lessons", headers=admin_headers).json()[0]["id"]

    r = client.post(
        f"/api/v1/alpha/memory/lessons/{lesson_id}/review", json={"status": "APPROVED"}
    )
    assert r.status_code == 401


def test_risk_manager_can_approve_a_lesson(client):
    admin_headers = _admin_headers(client)
    _close_a_trade(client, admin_headers)
    lesson_id = client.get("/api/v1/alpha/memory/lessons", headers=admin_headers).json()[0]["id"]

    risk_headers = _risk_headers(client)
    r = client.post(
        f"/api/v1/alpha/memory/lessons/{lesson_id}/review", json={"status": "APPROVED"}, headers=risk_headers
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "APPROVED"
    assert body["reviewed_by"] is not None
    assert body["reviewed_at"] is not None

    listed = client.get("/api/v1/alpha/memory/lessons?status=PENDING", headers=admin_headers).json()
    assert listed == []


def test_reviewing_back_to_pending_is_rejected(client):
    admin_headers = _admin_headers(client)
    _close_a_trade(client, admin_headers)
    lesson_id = client.get("/api/v1/alpha/memory/lessons", headers=admin_headers).json()[0]["id"]

    r = client.post(
        f"/api/v1/alpha/memory/lessons/{lesson_id}/review", json={"status": "PENDING"}, headers=admin_headers
    )
    assert r.status_code == 400


def test_reviewing_unknown_lesson_is_404(client):
    r = client.post(
        "/api/v1/alpha/memory/lessons/00000000-0000-0000-0000-000000000000/review",
        json={"status": "APPROVED"},
        headers=_admin_headers(client),
    )
    assert r.status_code == 404
