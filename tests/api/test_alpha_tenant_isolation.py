"""Milestone 9 (tenant isolation retrofit, docs/alpha-intelligence.md section 11.1):
proves the two cross-organization data-visibility gaps identified during that retrofit
are actually closed -- (a) list endpoints no longer skip organization filtering when
the caller's own organization can't be resolved (they now restrict to platform-wide
data instead), and (b) get-by-id endpoints now perform an organization check at all
(previously none). Uses `/alpha/signals` as the representative endpoint since every
other Alpha* list/get-by-id pair got the identical `resolve_organization_scope`/
`record_is_visible` treatment from the same helper functions."""

from __future__ import annotations

import asyncio

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


def _trader_headers(client) -> dict:
    login = client.post(
        "/api/v1/auth/login", json={"email": "trader@alphagasiq.local", "password": "trader-dev-password"}
    )
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def _seed_signals(state):
    from schemas import Signal, SignalType

    org_a = Signal(
        signal_type=SignalType.PRICE_MOVE,
        category="market",
        headline="org-a-only",
        description="d",
        materiality_score=80.0,
        confidence=0.8,
        organization_id="org-a",
    )
    org_b = Signal(
        signal_type=SignalType.PRICE_MOVE,
        category="market",
        headline="org-b-only",
        description="d",
        materiality_score=81.0,
        confidence=0.8,
        organization_id="org-b",
    )
    platform = Signal(
        signal_type=SignalType.PRICE_MOVE,
        category="market",
        headline="platform-wide",
        description="d",
        materiality_score=82.0,
        confidence=0.8,
        organization_id=None,
    )
    asyncio.run(state.repo.save_signal(org_a))
    asyncio.run(state.repo.save_signal(org_b))
    asyncio.run(state.repo.save_signal(platform))
    return org_a, org_b, platform


def _patch_scope(monkeypatch, *, organization_id, unrestricted):
    from api_app.routers import alpha as alpha_router

    async def fake_scope(_user, _state):
        return organization_id, unrestricted

    monkeypatch.setattr(alpha_router, "resolve_organization_scope", fake_scope)


def test_org_scoped_caller_cannot_list_another_orgs_signal(client, monkeypatch):
    from api_app import state as state_module

    org_a, org_b, platform = _seed_signals(state_module._state)
    _patch_scope(monkeypatch, organization_id="org-a", unrestricted=False)

    r = client.get("/api/v1/alpha/signals?min_materiality=0", headers=_trader_headers(client))
    assert r.status_code == 200
    ids = {item["id"] for item in r.json()}
    assert str(org_a.id) in ids
    assert str(platform.id) in ids
    assert str(org_b.id) not in ids


def test_caller_with_no_resolvable_org_sees_platform_wide_only(client, monkeypatch):
    """The core Milestone 9 fix: previously an unresolvable organization (`None`)
    caused the repository query to skip org filtering entirely, silently returning
    every organization's signals. Now it restricts to `organization_id IS NULL`."""
    from api_app import state as state_module

    org_a, org_b, platform = _seed_signals(state_module._state)
    _patch_scope(monkeypatch, organization_id=None, unrestricted=False)

    r = client.get("/api/v1/alpha/signals?min_materiality=0", headers=_trader_headers(client))
    assert r.status_code == 200
    ids = {item["id"] for item in r.json()}
    assert str(platform.id) in ids
    assert str(org_a.id) not in ids
    assert str(org_b.id) not in ids


def test_unrestricted_admin_sees_every_organizations_signal(client, monkeypatch):
    from api_app import state as state_module

    org_a, org_b, platform = _seed_signals(state_module._state)
    _patch_scope(monkeypatch, organization_id=None, unrestricted=True)

    r = client.get("/api/v1/alpha/signals?min_materiality=0", headers=_trader_headers(client))
    assert r.status_code == 200
    ids = {item["id"] for item in r.json()}
    assert {str(org_a.id), str(org_b.id), str(platform.id)} <= ids


def test_get_signal_by_id_404s_for_another_orgs_record(client, monkeypatch):
    """The second Milestone 9 fix: get-by-id endpoints previously performed no
    organization check at all, so any caller with `alpha_signals.view` could fetch
    any organization's specific signal by id."""
    from api_app import state as state_module

    org_a, org_b, _platform = _seed_signals(state_module._state)
    _patch_scope(monkeypatch, organization_id="org-a", unrestricted=False)

    r = client.get(f"/api/v1/alpha/signals/{org_b.id}", headers=_trader_headers(client))
    assert r.status_code == 404


def test_get_signal_by_id_succeeds_for_own_org_and_platform_wide(client, monkeypatch):
    from api_app import state as state_module

    org_a, _org_b, platform = _seed_signals(state_module._state)
    _patch_scope(monkeypatch, organization_id="org-a", unrestricted=False)

    r_own = client.get(f"/api/v1/alpha/signals/{org_a.id}", headers=_trader_headers(client))
    assert r_own.status_code == 200

    r_platform = client.get(f"/api/v1/alpha/signals/{platform.id}", headers=_trader_headers(client))
    assert r_platform.status_code == 200


def test_unrestricted_admin_can_get_another_orgs_signal_by_id(client, monkeypatch):
    from api_app import state as state_module

    _org_a, org_b, _platform = _seed_signals(state_module._state)
    _patch_scope(monkeypatch, organization_id=None, unrestricted=True)

    r = client.get(f"/api/v1/alpha/signals/{org_b.id}", headers=_trader_headers(client))
    assert r.status_code == 200
