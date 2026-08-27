"""Tenant-isolation retrofit (docs/alpha-intelligence.md section 11.1, Milestone
9): `RetentionEngine` -- pure policy resolution + cutoff computation, no I/O."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from enterprise_data_service.retention import RetentionEngine
from schemas import EnterpriseDataClassification, RetentionPolicy


def test_no_policy_configured_means_no_retention_days():
    engine = RetentionEngine()
    days = engine.resolve_retention_days(
        data_classification=EnterpriseDataClassification.CUSTOMER_CONFIDENTIAL, policies=[], organization_id="org-a"
    )
    assert days is None


def test_organization_policy_resolves_its_retention_days():
    engine = RetentionEngine()
    policy = RetentionPolicy(
        organization_id="org-a", data_classification=EnterpriseDataClassification.CUSTOMER_CONFIDENTIAL, retention_days=30
    )
    days = engine.resolve_retention_days(
        data_classification=EnterpriseDataClassification.CUSTOMER_CONFIDENTIAL,
        policies=[policy],
        organization_id="org-a",
    )
    assert days == 30


def test_platform_default_used_absent_org_override():
    engine = RetentionEngine()
    policy = RetentionPolicy(
        organization_id=None, data_classification=EnterpriseDataClassification.CUSTOMER_RISK_DATA, retention_days=90
    )
    days = engine.resolve_retention_days(
        data_classification=EnterpriseDataClassification.CUSTOMER_RISK_DATA, policies=[policy], organization_id="org-a"
    )
    assert days == 90


def test_organization_override_wins_over_platform_default():
    engine = RetentionEngine()
    platform_policy = RetentionPolicy(
        organization_id=None, data_classification=EnterpriseDataClassification.CUSTOMER_RISK_DATA, retention_days=90
    )
    org_policy = RetentionPolicy(
        organization_id="org-a", data_classification=EnterpriseDataClassification.CUSTOMER_RISK_DATA, retention_days=7
    )
    days = engine.resolve_retention_days(
        data_classification=EnterpriseDataClassification.CUSTOMER_RISK_DATA,
        policies=[platform_policy, org_policy],
        organization_id="org-a",
    )
    assert days == 7


def test_another_organizations_policy_does_not_leak_across():
    engine = RetentionEngine()
    other_org_policy = RetentionPolicy(
        organization_id="org-b", data_classification=EnterpriseDataClassification.CUSTOMER_RISK_DATA, retention_days=7
    )
    days = engine.resolve_retention_days(
        data_classification=EnterpriseDataClassification.CUSTOMER_RISK_DATA,
        policies=[other_org_policy],
        organization_id="org-a",
    )
    assert days is None


def test_compute_cutoff_none_when_no_retention_configured():
    assert RetentionEngine.compute_cutoff(None, now=datetime.now(timezone.utc)) is None


def test_compute_cutoff_subtracts_retention_days():
    now = datetime(2026, 1, 31, tzinfo=timezone.utc)
    cutoff = RetentionEngine.compute_cutoff(30, now=now)
    assert cutoff == now - timedelta(days=30)
