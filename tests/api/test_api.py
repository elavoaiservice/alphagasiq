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
    body = r.json()
    assert len(body["nodes"]) > 20
    assert body["classification"] == "SIMULATED"
    node_types = {n["type"] for n in body["nodes"]}
    assert {"production_basin", "LNG_terminal", "hub", "storage_facility"}.issubset(node_types)


def test_pipeline_node_detail_endpoint(client):
    r = client.get("/api/v1/fundamentals/pipeline/nodes/henry_hub")
    assert r.status_code == 200
    body = r.json()
    assert body["node"]["id"] == "henry_hub"
    assert len(body["edges"]) > 0


def test_pipeline_node_detail_404_for_unknown_node(client):
    r = client.get("/api/v1/fundamentals/pipeline/nodes/does-not-exist")
    assert r.status_code == 404


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


def _admin_headers(client) -> dict:
    login = client.post(
        "/api/v1/auth/login", json={"email": "admin@alphagasiq.local", "password": "admin-dev-password"}
    )
    token = login.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_close_trade_requires_auth(client):
    trades = client.get("/api/v1/trade-ideas").json()
    trade_id = trades[0]["trade_id"]
    r = client.post(f"/api/v1/trade-ideas/{trade_id}/close", json={})
    assert r.status_code == 401


def test_close_trade_before_execution_is_conflict(client):
    headers = _admin_headers(client)
    trades = client.get("/api/v1/trade-ideas").json()
    trade_id = trades[0]["trade_id"]
    r = client.post(f"/api/v1/trade-ideas/{trade_id}/close", json={}, headers=headers)
    assert r.status_code == 409


def test_full_lifecycle_execute_then_close_then_post_trade_and_performance(client):
    headers = _admin_headers(client)

    trades = client.get("/api/v1/trade-ideas").json()
    trade_id = trades[0]["trade_id"]
    entry_price = trades[0]["entry"]

    approvals = client.get("/api/v1/approvals").json()
    approval = next(a for a in approvals if a["trade_id"] == trade_id)

    approve = client.post(
        f"/api/v1/approvals/{approval['id']}/action",
        json={"action": "APPROVE", "payload": {"quantity": 10}},
        headers=headers,
    )
    if approval["state"] == "RISK_REVIEW":
        assert approve.status_code == 409
        return  # Risk Governor blocked this seed's trade; nothing further to exercise.

    assert approve.status_code == 200
    assert approve.json()["state"] == "EXECUTED_SIMULATION"

    positions = client.get("/api/v1/portfolio/positions").json()
    position = next(p for p in positions if p["instrument"] == trades[0]["instrument"])
    assert position["quantity"] != 0
    # Entry price recorded on the trade idea should closely match the actual paper
    # fill price (small gap only from simulated slippage/spread) — regression guard
    # for the instrument/mark-price desync bug fixed alongside this feature.
    assert abs(position["avg_price"] - entry_price) < 0.05

    close = client.post(
        f"/api/v1/trade-ideas/{trade_id}/close", json={"exit_reason": "test_close"}, headers=headers
    )
    assert close.status_code == 200
    analysis = close.json()["post_trade_analysis"]
    assert analysis["quadrant"] in (
        "GOOD_DECISION_GOOD_OUTCOME",
        "GOOD_DECISION_BAD_OUTCOME",
        "BAD_DECISION_GOOD_OUTCOME",
        "BAD_DECISION_BAD_OUTCOME",
    )
    # The Quantitative Team's forecast for this instrument was attached at trade
    # creation (AppState.submit_trade_idea), so closing should score it too —
    # the quant/post-trade unification this feature exists to prove.
    assert analysis["quant_model_type"] == "LINEAR_REGRESSION"
    assert analysis["quant_predicted_return"] is not None
    assert analysis["quant_forecast_error"] is not None
    assert 0 <= analysis["quant_up_probability"] <= 1

    # Closing twice must fail cleanly, not silently double-count P&L.
    close_again = client.post(f"/api/v1/trade-ideas/{trade_id}/close", json={}, headers=headers)
    assert close_again.status_code == 409

    post_trade = client.get(f"/api/v1/post-trade/{trade_id}")
    assert post_trade.status_code == 200
    assert post_trade.json()["status"] == "CLOSED"

    performance = client.get("/api/v1/models/performance")
    assert performance.status_code == 200
    perf_body = performance.json()
    assert perf_body["closed_trade_count"] == 1
    assert perf_body["classification"] == "SIMULATED"

    quant = perf_body["quant"]
    assert set(quant["backtested"].keys()) == {
        "NAIVE_PERSISTENCE",
        "LINEAR_REGRESSION",
        "ARIMA",
        "VAR",
        "STATE_SPACE",
        "RANDOM_FOREST",
        "XGBOOST",
        "LIGHTGBM",
    }
    assert quant["live"]["n_forecasts_resolved"] == 1
    assert quant["live"]["directional_accuracy"] in (0.0, 1.0)
    assert "LINEAR_REGRESSION" in quant["live"]["by_model"]
    assert quant["live"]["by_model"]["LINEAR_REGRESSION"]["n"] == 1


def test_model_performance_endpoint_empty_before_any_close(client):
    r = client.get("/api/v1/models/performance")
    assert r.status_code == 200
    body = r.json()
    assert body["closed_trade_count"] == 0
    assert body["win_rate"] is None
    # Backtested model performance is computed at startup (independent of any closed
    # trade); only the "live" side is legitimately empty before anything has closed.
    quant = body["quant"]
    assert set(quant["backtested"].keys()) == {
        "NAIVE_PERSISTENCE",
        "LINEAR_REGRESSION",
        "ARIMA",
        "VAR",
        "STATE_SPACE",
        "RANDOM_FOREST",
        "XGBOOST",
        "LIGHTGBM",
    }
    assert quant["live"]["n_forecasts_resolved"] == 0
    assert quant["live"]["directional_accuracy"] is None
    assert quant["live"]["by_model"] == {}


def test_post_trade_reports_open_before_close(client):
    trades = client.get("/api/v1/trade-ideas").json()
    trade_id = trades[0]["trade_id"]
    r = client.get(f"/api/v1/post-trade/{trade_id}")
    assert r.status_code == 200
    assert r.json()["status"] == "OPEN"


def test_quant_forecast_endpoint(client):
    r = client.get("/api/v1/quant/forecast")
    assert r.status_code == 200
    body = r.json()
    assert "price_forecast" in body
    assert body["classification"] == "SIMULATED"


def test_quant_regime_endpoint(client):
    r = client.get("/api/v1/quant/regime")
    assert r.status_code == 200
    body = r.json()
    assert "regime" in body
    assert body["classification"] == "SIMULATED"


def test_quant_relative_value_endpoint(client):
    r = client.get("/api/v1/quant/relative-value")
    assert r.status_code == 200
    body = r.json()
    assert "hh_ttf_netback" in body
    assert "calendar_spread" in body


def test_quant_backtest_endpoint(client):
    r = client.get("/api/v1/quant/backtest")
    assert r.status_code == 200
    body = r.json()
    assert set(body["results_by_model"].keys()) == {
        "NAIVE_PERSISTENCE",
        "LINEAR_REGRESSION",
        "ARIMA",
        "VAR",
        "STATE_SPACE",
        "RANDOM_FOREST",
        "XGBOOST",
        "LIGHTGBM",
    }


def test_quant_models_endpoint_lists_every_model_type_honestly(client):
    r = client.get("/api/v1/quant/models")
    assert r.status_code == 200
    statuses = {s["model_type"]: s["implemented"] for s in r.json()}
    assert statuses["NAIVE_PERSISTENCE"] is True
    assert statuses["LINEAR_REGRESSION"] is True
    assert statuses["ARIMA"] is True
    assert statuses["VAR"] is True
    assert statuses["STATE_SPACE"] is True
    assert statuses["RANDOM_FOREST"] is True
    assert statuses["XGBOOST"] is True
    assert statuses["LIGHTGBM"] is True
    assert statuses["TEMPORAL_FUSION_TRANSFORMER"] is False
    assert statuses["LSTM"] is False


def test_org_chart_includes_quantitative_team_as_implemented(client):
    r = client.get("/api/v1/agents")
    body = r.json()
    quant_types = {"FORECASTING", "REGIME_DETECTION", "RELATIVE_VALUE", "BACKTESTING"}
    implemented = {a["agent_type"] for a in body if a["agent_type"] in quant_types and a["implemented"]}
    assert implemented == quant_types
