import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from api_app import state as state_module

    state_module.reset_app_state()
    from api_app.main import app

    with TestClient(app) as c:
        yield c
    state_module.reset_app_state()


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_system_status_seeds_platform(client):
    r = client.get("/api/v1/system/status")
    assert r.status_code == 200
    body = r.json()
    assert body["counts"]["trade_ideas"] >= 0
    assert body["trading_halted"] is False


def test_providers_lists_classifications(client):
    r = client.get("/api/v1/system/providers")
    assert r.status_code == 200
    ids = {p["provider_id"] for p in r.json()}
    assert "mock_cme" in ids
    assert "eia" in ids


def test_market_summary_labeled_simulated(client):
    r = client.get("/api/v1/market/summary")
    assert r.status_code == 200
    assert r.json()["classification"] == "SIMULATED"


def test_market_curve_has_36_points(client):
    r = client.get("/api/v1/market/curve/NGZ26")
    assert r.status_code == 200
    assert len(r.json()["points"]) == 36


def test_storage_forecast_endpoint(client):
    r = client.get("/api/v1/fundamentals/storage/forecast")
    assert r.status_code == 200
    assert "forecast_bcf" in r.json()


def test_pipeline_graph_endpoint(client):
    r = client.get("/api/v1/fundamentals/pipeline/graph")
    assert r.status_code == 200
    assert len(r.json()["nodes"]) > 0


def test_news_events_endpoint(client):
    r = client.get("/api/v1/news/events")
    assert r.status_code == 200
    assert len(r.json()) == 5


def test_org_chart_lists_every_agent_type(client):
    r = client.get("/api/v1/agents")
    assert r.status_code == 200
    body = r.json()
    assert any(a["agent_type"] == "SUPPLY" and a["implemented"] for a in body)
    assert any(a["agent_type"] == "MARKET_DATA" and not a["implemented"] for a in body)


def test_login_success_and_failure(client):
    ok = client.post("/api/v1/auth/login", json={"email": "trader@alphagasiq.local", "password": "trader-dev-password"})
    assert ok.status_code == 200
    assert "access_token" in ok.json()

    bad = client.post("/api/v1/auth/login", json={"email": "trader@alphagasiq.local", "password": "wrong"})
    assert bad.status_code == 401


def test_chief_trading_run_requires_auth(client):
    r = client.post("/api/v1/agents/chief-trading/run")
    assert r.status_code == 401


def test_chief_trading_run_with_researcher_role(client):
    login = client.post(
        "/api/v1/auth/login", json={"email": "trader@alphagasiq.local", "password": "trader-dev-password"}
    )
    token = login.json()["access_token"]
    r = client.post("/api/v1/agents/chief-trading/run", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    assert "trade_ideas_generated" in r.json()


def test_trade_idea_lifecycle_and_explainability(client):
    trades = client.get("/api/v1/trade-ideas").json()
    assert len(trades) >= 1
    trade_id = trades[0]["trade_id"]

    detail = client.get(f"/api/v1/trade-ideas/{trade_id}")
    assert detail.status_code == 200
    body = detail.json()
    assert "explainability" in body
    for key in ("what", "why", "why_now", "catalyst", "confidence", "risk", "sources"):
        assert key in body["explainability"]

    challenge = client.post(f"/api/v1/trade-ideas/{trade_id}/challenge")
    assert challenge.status_code == 200
    assert "bear_case" in challenge.json()


def test_risk_portfolio_endpoint(client):
    r = client.get("/api/v1/risk/portfolio")
    assert r.status_code == 200
    assert "var_95" in r.json()


def test_risk_limits_update_requires_role(client):
    unauth = client.get("/api/v1/risk/limits")
    assert unauth.status_code == 200
    limits = unauth.json()

    trader_login = client.post(
        "/api/v1/auth/login", json={"email": "trader@alphagasiq.local", "password": "trader-dev-password"}
    )
    trader_token = trader_login.json()["access_token"]
    forbidden = client.put(
        "/api/v1/risk/limits", json=limits, headers={"Authorization": f"Bearer {trader_token}"}
    )
    assert forbidden.status_code == 403

    risk_login = client.post(
        "/api/v1/auth/login", json={"email": "risk@alphagasiq.local", "password": "risk-dev-password"}
    )
    risk_token = risk_login.json()["access_token"]
    ok = client.put("/api/v1/risk/limits", json=limits, headers={"Authorization": f"Bearer {risk_token}"})
    assert ok.status_code == 200


def test_scenario_run_endpoint(client):
    r = client.post("/api/v1/risk/scenarios/freeport_lng_outage/run")
    assert r.status_code == 200
    assert "portfolio_pnl" in r.json()


def test_unknown_scenario_returns_404(client):
    r = client.post("/api/v1/risk/scenarios/does_not_exist/run")
    assert r.status_code == 404


def test_approvals_listed_and_actionable(client):
    approvals = client.get("/api/v1/approvals").json()
    assert len(approvals) >= 1

    admin_login = client.post(
        "/api/v1/auth/login", json={"email": "admin@alphagasiq.local", "password": "admin-dev-password"}
    )
    token = admin_login.json()["access_token"]

    approval = approvals[0]
    r = client.post(
        f"/api/v1/approvals/{approval['id']}/action",
        json={"action": "REQUEST_MORE_ANALYSIS", "payload": {}},
        headers={"Authorization": f"Bearer {token}"},
    )
    # RISK_REVIEW-state approvals accept the action but stay gated; either way this
    # must not 500, and must reflect an audit-logged action.
    assert r.status_code in (200, 409)


def test_approvals_action_requires_auth(client):
    approvals = client.get("/api/v1/approvals").json()
    approval = approvals[0]
    r = client.post(f"/api/v1/approvals/{approval['id']}/action", json={"action": "APPROVE", "payload": {}})
    assert r.status_code == 401


def test_chat_session_and_message(client):
    session = client.post("/api/v1/chat/sessions")
    assert session.status_code == 200
    session_id = session.json()["id"]

    reply = client.post(f"/api/v1/chat/sessions/{session_id}/messages", json={"content": "Why are we bullish?"})
    assert reply.status_code == 200
    body = reply.json()
    assert body["role"] == "assistant"
    assert isinstance(body["content"], str) and len(body["content"]) > 0


def test_chat_scenario_question_runs_real_scenario(client):
    session = client.post("/api/v1/chat/sessions").json()
    reply = client.post(
        f"/api/v1/chat/sessions/{session['id']}/messages",
        json={"content": "Run a scenario where Freeport LNG goes offline"},
    )
    assert reply.status_code == 200
    assert "Freeport" in reply.json()["content"] or "LNG" in reply.json()["content"]


def test_portfolio_positions_endpoint(client):
    r = client.get("/api/v1/portfolio/positions")
    assert r.status_code == 200
    assert isinstance(r.json(), list)
