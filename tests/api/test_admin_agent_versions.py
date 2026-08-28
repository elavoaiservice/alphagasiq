"""Milestone 9: agent versioning + prompt editor + optimization workflow
(spec §§40-41, `docs/agent-governance.md` §§4-5)."""

from __future__ import annotations

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


def _admin_headers(client) -> dict:
    login = client.post(
        "/api/v1/auth/login", json={"email": "admin@alphagasiq.local", "password": "admin-dev-password"}
    )
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def _trader_headers(client) -> dict:
    login = client.post(
        "/api/v1/auth/login", json={"email": "trader@alphagasiq.local", "password": "trader-dev-password"}
    )
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def _extract_latest_token(client, email: str) -> str:
    import re

    from api_app import state as state_module

    sent = state_module._state.email_provider.sent
    message = next(m for m in reversed(sent) if m.to == email)
    return re.search(r"token=([A-Za-z0-9_-]+)", message.text_body).group(1)


def _create_user(client, *, email: str, role: str = "SUPER_ADMIN") -> dict:
    headers = _admin_headers(client)
    r = client.post(
        "/api/v1/admin/users",
        json={
            "first_name": "Pat",
            "last_name": "Nguyen",
            "business_email": email,
            "company_name": f"Org for {email}",
            "role": role,
        },
        headers=headers,
    )
    assert r.status_code == 201
    return r.json()


def _super_admin_headers(client, email: str) -> dict:
    """`admin.agent_optimization` is SUPER_ADMIN-only -- the dev-mode ADMIN fixture
    doesn't carry it, so this creates a real DB user with the SUPER_ADMIN role and
    logs them in via magic link."""
    _create_user(client, email=email, role="SUPER_ADMIN")
    token = _extract_latest_token(client, email)
    verify = client.get(f"/api/v1/auth/magic-link/verify?token={token}", follow_redirects=False)
    session_token = verify.headers["location"].split("access_token=", 1)[1]
    return {"Authorization": f"Bearer {session_token}"}


def test_boot_seeds_a_real_production_version_for_implemented_agents(client):
    r = client.get("/api/v1/admin/agents/SUPPLY/versions", headers=_admin_headers(client))
    assert r.status_code == 200
    versions = r.json()
    assert len(versions) == 1
    assert versions[0]["status"] == "PRODUCTION"
    assert versions[0]["model_provider"] is not None

    prod = client.get("/api/v1/admin/agents/SUPPLY/versions/production", headers=_admin_headers(client))
    assert prod.status_code == 200
    assert prod.json()["id"] == versions[0]["id"]


def test_list_versions_requires_permission(client):
    r = client.get("/api/v1/admin/agents/SUPPLY/versions", headers=_trader_headers(client))
    assert r.status_code == 403


def test_versions_for_unimplemented_or_risk_governor_agent_are_rejected(client):
    headers = _admin_headers(client)
    assert client.get("/api/v1/admin/agents/MARKET_DATA/versions", headers=headers).status_code == 400
    assert client.get("/api/v1/admin/agents/RISK_GOVERNOR/versions", headers=headers).status_code == 400


def test_create_draft_version(client):
    headers = _admin_headers(client)
    r = client.post(
        "/api/v1/admin/agents/SUPPLY/versions",
        json={"version": "0.2.0-draft1", "system_instructions": "Be more concise.", "notes": "Trying a tighter prompt"},
        headers=headers,
    )
    assert r.status_code == 201
    body = r.json()
    assert body["status"] == "DRAFT"
    assert body["system_instructions"] == "Be more concise."

    versions = client.get("/api/v1/admin/agents/SUPPLY/versions", headers=headers).json()
    assert len(versions) == 2  # the boot-seeded PRODUCTION version + this draft


def test_full_lifecycle_promote_and_rollback(client):
    headers = _admin_headers(client)
    created = client.post(
        "/api/v1/admin/agents/SUPPLY/versions", json={"version": "0.2.0-draft1"}, headers=headers
    ).json()
    version_id = created["id"]

    # Cannot skip straight to PRODUCTION.
    r = client.post(
        f"/api/v1/admin/agents/SUPPLY/versions/{version_id}/transition",
        json={"status": "PRODUCTION"},
        headers=headers,
    )
    assert r.status_code == 400

    r = client.post(
        f"/api/v1/admin/agents/SUPPLY/versions/{version_id}/transition",
        json={"status": "TESTING"},
        headers=headers,
    )
    assert r.status_code == 200
    assert r.json()["status"] == "TESTING"

    r = client.post(
        f"/api/v1/admin/agents/SUPPLY/versions/{version_id}/transition",
        json={"status": "APPROVED", "evaluation_results": {"accuracy": 0.9}},
        headers=headers,
    )
    assert r.status_code == 200
    assert r.json()["status"] == "APPROVED"

    r = client.post(
        f"/api/v1/admin/agents/SUPPLY/versions/{version_id}/transition",
        json={"status": "PRODUCTION"},
        headers=headers,
    )
    assert r.status_code == 200
    assert r.json()["status"] == "PRODUCTION"

    prod = client.get("/api/v1/admin/agents/SUPPLY/versions/production", headers=headers).json()
    assert prod["id"] == version_id

    r = client.post(
        f"/api/v1/admin/agents/SUPPLY/versions/{version_id}/transition",
        json={"status": "ROLLED_BACK"},
        headers=headers,
    )
    assert r.status_code == 200
    assert r.json()["status"] == "ROLLED_BACK"

    assert client.get("/api/v1/admin/agents/SUPPLY/versions/production", headers=headers).status_code == 404


def test_transition_unknown_version_is_404(client):
    r = client.post(
        "/api/v1/admin/agents/SUPPLY/versions/no-such-version/transition",
        json={"status": "TESTING"},
        headers=_admin_headers(client),
    )
    assert r.status_code == 404


def test_create_version_requires_permission(client):
    r = client.post(
        "/api/v1/admin/agents/SUPPLY/versions", json={"version": "0.2.0"}, headers=_trader_headers(client)
    )
    assert r.status_code == 403


def test_optimization_propose_requires_super_admin(client):
    r = client.post(
        "/api/v1/admin/agents/SUPPLY/optimization/propose",
        json={"version": "0.3.0", "problem_identification": "x", "proposed_change": "y"},
        headers=_admin_headers(client),
    )
    assert r.status_code == 403  # dev-mode ADMIN lacks admin.agent_optimization


def _promote_to_production(client, headers, agent_type: str, version_id: str) -> None:
    for target in ("TESTING", "APPROVED", "PRODUCTION"):
        r = client.post(
            f"/api/v1/admin/agents/{agent_type}/versions/{version_id}/transition",
            json={"status": target},
            headers=headers,
        )
        assert r.status_code == 200, r.text


def test_promoting_a_version_applies_system_instructions_to_the_live_agent(client):
    """#1: agent versioning -> live execution. Promoting a PRODUCTION version with
    `system_instructions` set must actually change what the live SupplyAgent sends as
    `system=` on its next LLM call, not just be recorded for history
    (docs/agent-governance.md §4)."""
    from api_app import state as state_module

    headers = _admin_headers(client)
    created = client.post(
        "/api/v1/admin/agents/SUPPLY/versions",
        json={"version": "0.2.0-live-test", "system_instructions": "Cite EIA figures explicitly."},
        headers=headers,
    ).json()
    _promote_to_production(client, headers, "SUPPLY", created["id"])

    live_agent = state_module._state.chief_trading_agent.supply_agent
    assert live_agent.system_instructions == "Cite EIA figures explicitly."


def test_rolling_back_resets_live_agent_system_instructions(client):
    """A ROLLED_BACK transition is terminal and never auto-restores a prior version
    (`_AGENT_VERSION_TRANSITIONS`), so once it fires the agent_type has no PRODUCTION
    row at all -- the live agent must fall back to no override rather than keeping a
    stale prompt."""
    from api_app import state as state_module

    headers = _admin_headers(client)
    created = client.post(
        "/api/v1/admin/agents/SUPPLY/versions",
        json={"version": "0.2.1-live-test", "system_instructions": "Temporary override."},
        headers=headers,
    ).json()
    version_id = created["id"]
    _promote_to_production(client, headers, "SUPPLY", version_id)

    live_agent = state_module._state.chief_trading_agent.supply_agent
    assert live_agent.system_instructions == "Temporary override."

    r = client.post(
        f"/api/v1/admin/agents/SUPPLY/versions/{version_id}/transition",
        json={"status": "ROLLED_BACK"},
        headers=headers,
    )
    assert r.status_code == 200
    assert live_agent.system_instructions is None


def test_promoting_a_version_with_approved_model_rebuilds_live_llm_provider(client):
    """A PRODUCTION version's `model_name` must rebuild the live agent's `llm`
    provider via `build_llm_provider()` so the agent actually talks to the newly
    approved model on its next call."""
    from api_app import state as state_module

    admin_headers = _admin_headers(client)
    super_headers = _super_admin_headers(client, "modeladmin@realcompany.com")

    model = client.post(
        "/api/v1/admin/models",
        json={"provider": "AnthropicLLMProvider", "model_name": "claude-opus-5-test"},
        headers=super_headers,
    ).json()
    approve = client.patch(
        f"/api/v1/admin/models/{model['id']}/status",
        json={"status": "APPROVED"},
        headers=super_headers,
    )
    assert approve.status_code == 200

    created = client.post(
        "/api/v1/admin/agents/SUPPLY/versions",
        json={"version": "0.2.2-live-test", "model_name": "claude-opus-5-test"},
        headers=admin_headers,
    ).json()
    _promote_to_production(client, admin_headers, "SUPPLY", created["id"])

    live_agent = state_module._state.chief_trading_agent.supply_agent
    assert live_agent.llm.model == "claude-opus-5-test"


def test_optimization_propose_creates_a_draft_with_performance_review(client):
    headers = _super_admin_headers(client, "optimizer@realcompany.com")
    r = client.post(
        "/api/v1/admin/agents/SUPPLY/optimization/propose",
        json={
            "version": "0.3.0",
            "problem_identification": "Confidence has been flat.",
            "proposed_change": "Tighten the summarization prompt.",
            "system_instructions": "Be more concise and cite the trend explicitly.",
        },
        headers=headers,
    )
    assert r.status_code == 201
    body = r.json()
    assert body["status"] == "DRAFT"
    assert "Problem identification" in body["notes"]
    assert "Performance review snapshot" in body["notes"]
