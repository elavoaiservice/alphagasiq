"""Tenant-isolation retrofit (docs/alpha-intelligence.md section 11.1, Milestone
9): `ModelRoutingEngine.evaluate()` -- the pure ALLOW_EXTERNAL_LLM_PROCESSING gate."""

from __future__ import annotations

from enterprise_data_service.model_routing import ModelRoutingEngine
from schemas import EnterpriseDataClassification, ModelRoutingPolicy


def test_customer_restricted_defaults_to_blocked_absent_any_policy():
    engine = ModelRoutingEngine()
    decision = engine.evaluate(
        data_classification=EnterpriseDataClassification.CUSTOMER_RESTRICTED, policies=[], organization_id="org-a"
    )
    assert decision.allowed is False


def test_public_defaults_to_allowed_absent_any_policy():
    engine = ModelRoutingEngine()
    decision = engine.evaluate(
        data_classification=EnterpriseDataClassification.PUBLIC, policies=[], organization_id="org-a"
    )
    assert decision.allowed is True


def test_alphagasiq_proprietary_defaults_to_allowed():
    engine = ModelRoutingEngine()
    decision = engine.evaluate(
        data_classification=EnterpriseDataClassification.ALPHAGASIQ_PROPRIETARY, policies=[], organization_id=None
    )
    assert decision.allowed is True


def test_customer_position_data_defaults_to_blocked():
    engine = ModelRoutingEngine()
    decision = engine.evaluate(
        data_classification=EnterpriseDataClassification.CUSTOMER_POSITION_DATA, policies=[], organization_id="org-a"
    )
    assert decision.allowed is False


def test_organization_override_allows_what_the_default_would_block():
    engine = ModelRoutingEngine()
    policy = ModelRoutingPolicy(
        organization_id="org-a",
        data_classification=EnterpriseDataClassification.CUSTOMER_RESTRICTED,
        allow_external_llm_processing=True,
        allowed_provider="anthropic",
    )
    decision = engine.evaluate(
        data_classification=EnterpriseDataClassification.CUSTOMER_RESTRICTED,
        policies=[policy],
        organization_id="org-a",
    )
    assert decision.allowed is True
    assert decision.allowed_provider == "anthropic"


def test_platform_default_policy_applies_when_no_org_override_exists():
    engine = ModelRoutingEngine()
    platform_policy = ModelRoutingPolicy(
        organization_id=None,
        data_classification=EnterpriseDataClassification.CUSTOMER_CONFIDENTIAL,
        allow_external_llm_processing=True,
    )
    decision = engine.evaluate(
        data_classification=EnterpriseDataClassification.CUSTOMER_CONFIDENTIAL,
        policies=[platform_policy],
        organization_id="org-a",
    )
    assert decision.allowed is True


def test_organization_override_wins_over_platform_default():
    engine = ModelRoutingEngine()
    platform_policy = ModelRoutingPolicy(
        organization_id=None,
        data_classification=EnterpriseDataClassification.CUSTOMER_CONFIDENTIAL,
        allow_external_llm_processing=True,
    )
    org_policy = ModelRoutingPolicy(
        organization_id="org-a",
        data_classification=EnterpriseDataClassification.CUSTOMER_CONFIDENTIAL,
        allow_external_llm_processing=False,
    )
    decision = engine.evaluate(
        data_classification=EnterpriseDataClassification.CUSTOMER_CONFIDENTIAL,
        policies=[platform_policy, org_policy],
        organization_id="org-a",
    )
    assert decision.allowed is False


def test_another_organizations_override_does_not_leak_across():
    engine = ModelRoutingEngine()
    other_org_policy = ModelRoutingPolicy(
        organization_id="org-b",
        data_classification=EnterpriseDataClassification.CUSTOMER_RESTRICTED,
        allow_external_llm_processing=True,
    )
    decision = engine.evaluate(
        data_classification=EnterpriseDataClassification.CUSTOMER_RESTRICTED,
        policies=[other_org_policy],
        organization_id="org-a",
    )
    assert decision.allowed is False
