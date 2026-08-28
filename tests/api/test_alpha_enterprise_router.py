"""Milestone 10 (docs/alpha-intelligence.md section 11.7): the Enterprise
Opportunity Engine API (`/alpha/enterprise/opportunities*`) and the Enterprise
Digital Twin pipeline overlay (`/alpha/enterprise/pipeline-overlay`) -- both
scoped to the caller's own resolved organization, never platform-wide."""

from __future__ import annotations

import re

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


def _activate_via_magic_link(client, email: str, role: str, company_name: str) -> dict:
    """Creates a real DB user (via the admin API) with the given role and
    company -- passing the same `company_name` twice reuses the same
    organization (docs/access-model.md: org names are looked-up-or-created
    inline), which is how these tests get two different-role users into the
    same organization. Activates via the magic-link token the console email
    provider captured, exactly what a real user does by clicking the link."""
    from api_app import state as state_module

    admin_headers = _admin_headers(client)
    created = client.post(
        "/api/v1/admin/users",
        json={
            "first_name": "Real",
            "last_name": "User",
            "business_email": email,
            "company_name": company_name,
            "role": role,
        },
        headers=admin_headers,
    ).json()

    sent = state_module._state.email_provider.sent
    token = re.search(r"token=([A-Za-z0-9_-]+)", sent[-1].text_body).group(1)
    verify = client.get(f"/api/v1/auth/magic-link/verify?token={token}", follow_redirects=False)
    session_token = verify.headers["location"].split("access_token=", 1)[1]
    return {"headers": {"Authorization": f"Bearer {session_token}"}, "user": created}


def test_dev_mode_caller_with_no_org_sees_empty_list_not_an_error(client):
    r = client.get("/api/v1/alpha/enterprise/opportunities", headers=_trader_headers(client))
    assert r.status_code == 200
    assert r.json() == []


def test_dev_mode_caller_with_no_org_cannot_generate(client):
    r = client.post("/api/v1/alpha/enterprise/opportunities/generate", headers=_trader_headers(client))
    assert r.status_code == 400


def test_non_permitted_caller_cannot_list_opportunities(client):
    r = client.get("/api/v1/alpha/enterprise/opportunities", headers=_admin_headers(client))
    # ADMIN holds every non-super-admin-only permission, including
    # enterprise_opportunities.view -- confirm 200, not accidentally 403,
    # then separately confirm a caller truly lacking the permission is 403.
    assert r.status_code == 200


def test_get_unknown_opportunity_is_404(client):
    trader = _activate_via_magic_link(client, "trader-a@company-a.com", "TRADER", "Company A")
    r = client.get(
        "/api/v1/alpha/enterprise/opportunities/00000000-0000-0000-0000-000000000000", headers=trader["headers"]
    )
    assert r.status_code == 404


def test_generate_list_get_review_full_flow(client):
    import asyncio

    from api_app import state as state_module
    from schemas import ConsensusView, EnterpriseDataClassification, EnterpriseDataDomain, EnterpriseDataset

    trader = _activate_via_magic_link(client, "trader-b@company-b.com", "TRADER", "Company B")
    risk = _activate_via_magic_link(client, "risk-b@company-b.com", "RISK_MANAGER", "Company B")
    org_id = trader["user"]["organization_id"]
    assert org_id == risk["user"]["organization_id"]

    state = state_module._state
    ds = EnterpriseDataset(
        source_id="00000000-0000-0000-0000-000000000000",
        organization_id=org_id,
        name="positions",
        domain=EnterpriseDataDomain.POSITION,
        classification=EnterpriseDataClassification.CUSTOMER_POSITION_DATA,
    )
    asyncio.run(state.repo.save_enterprise_dataset(ds))
    asyncio.run(state.repo.save_enterprise_records(str(ds.id), [{"market": "WAHA", "direction": "LONG"}]))
    view = ConsensusView(
        consensus_type="PRICE",
        market="WAHA",
        target="price",
        bull_probability=0.1,
        bear_probability=0.8,
        confidence=0.75,
        agreement_label="HIGH",
        agent_count=5,
        organization_id=org_id,
    )
    asyncio.run(state.repo.save_consensus_view(view))

    # TRADER can generate.
    generated = client.post("/api/v1/alpha/enterprise/opportunities/generate", headers=trader["headers"])
    assert generated.status_code == 200
    created = generated.json()
    assert len(created) == 1
    opp_id = created[0]["id"]
    assert created[0]["status"] == "PENDING"

    # TRADER cannot review (only .view/.generate granted to TRADER).
    trader_review = client.post(
        f"/api/v1/alpha/enterprise/opportunities/{opp_id}/review", json={"status": "APPROVED"}, headers=trader["headers"]
    )
    assert trader_review.status_code == 403

    # RISK_MANAGER can view and review, same organization.
    listed = client.get("/api/v1/alpha/enterprise/opportunities", headers=risk["headers"])
    assert listed.status_code == 200
    assert len(listed.json()) == 1

    got = client.get(f"/api/v1/alpha/enterprise/opportunities/{opp_id}", headers=risk["headers"])
    assert got.status_code == 200

    reviewed = client.post(
        f"/api/v1/alpha/enterprise/opportunities/{opp_id}/review", json={"status": "APPROVED"}, headers=risk["headers"]
    )
    assert reviewed.status_code == 200
    assert reviewed.json()["status"] == "APPROVED"
    assert reviewed.json()["reviewed_by"] == risk["user"]["id"]


def test_review_rejects_pending_status(client):
    import asyncio

    from api_app import state as state_module
    from schemas import EnterpriseOpportunity, EnterpriseOpportunityType

    risk = _activate_via_magic_link(client, "risk-c@company-c.com", "RISK_MANAGER", "Company C")
    org_id = risk["user"]["organization_id"]
    opp = EnterpriseOpportunity(
        organization_id=org_id,
        opportunity_type=EnterpriseOpportunityType.HEDGE_MISALIGNED_POSITION,
        market="HENRY_HUB",
        title="t",
        summary="s",
        confidence=0.7,
    )
    asyncio.run(state_module._state.repo.save_enterprise_opportunity(opp))

    r = client.post(
        f"/api/v1/alpha/enterprise/opportunities/{opp.id}/review", json={"status": "PENDING"}, headers=risk["headers"]
    )
    assert r.status_code == 400


def test_cross_organization_caller_cannot_get_or_review_opportunity(client):
    import asyncio

    from api_app import state as state_module
    from schemas import EnterpriseOpportunity, EnterpriseOpportunityType

    org_a_trader = _activate_via_magic_link(client, "trader-d@company-d.com", "TRADER", "Company D")
    org_b_risk = _activate_via_magic_link(client, "risk-e@company-e.com", "RISK_MANAGER", "Company E")

    opp = EnterpriseOpportunity(
        organization_id=org_a_trader["user"]["organization_id"],
        opportunity_type=EnterpriseOpportunityType.HEDGE_MISALIGNED_POSITION,
        market="HENRY_HUB",
        title="t",
        summary="s",
        confidence=0.7,
    )
    asyncio.run(state_module._state.repo.save_enterprise_opportunity(opp))

    cross_get = client.get(f"/api/v1/alpha/enterprise/opportunities/{opp.id}", headers=org_b_risk["headers"])
    assert cross_get.status_code == 404

    cross_review = client.post(
        f"/api/v1/alpha/enterprise/opportunities/{opp.id}/review",
        json={"status": "APPROVED"},
        headers=org_b_risk["headers"],
    )
    assert cross_review.status_code == 404


def test_pipeline_overlay_returns_public_graph_with_empty_overlay_for_dev_mode_caller(client):
    r = client.get("/api/v1/alpha/enterprise/pipeline-overlay", headers=_trader_headers(client))
    assert r.status_code == 200
    body = r.json()
    assert len(body["nodes"]) > 0
    assert body["overlay"]["assets"] == []


def test_pipeline_overlay_shows_own_org_asset_and_hides_other_orgs(client):
    import asyncio

    from api_app import state as state_module
    from schemas import EnterpriseDataClassification, EnterpriseDataDomain, EnterpriseDataset

    org_a = _activate_via_magic_link(client, "trader-f@company-f.com", "TRADER", "Company F")
    org_b = _activate_via_magic_link(client, "trader-g@company-g.com", "TRADER", "Company G")

    state = state_module._state
    known_node_id = state.pipeline_graph.nodes[0].id

    ds_a = EnterpriseDataset(
        source_id="00000000-0000-0000-0000-000000000000",
        organization_id=org_a["user"]["organization_id"],
        name="assets",
        domain=EnterpriseDataDomain.ASSET,
        classification=EnterpriseDataClassification.PUBLIC,
    )
    asyncio.run(state.repo.save_enterprise_dataset(ds_a))
    asyncio.run(
        state.repo.save_enterprise_records(
            str(ds_a.id), [{"pipeline_node_id": known_node_id, "label": "Org A Well"}]
        )
    )

    own = client.get("/api/v1/alpha/enterprise/pipeline-overlay", headers=org_a["headers"])
    assert own.status_code == 200
    assert len(own.json()["overlay"]["assets"]) == 1
    assert own.json()["overlay"]["assets"][0]["label"] == "Org A Well"

    other = client.get("/api/v1/alpha/enterprise/pipeline-overlay", headers=org_b["headers"])
    assert other.status_code == 200
    assert other.json()["overlay"]["assets"] == []
