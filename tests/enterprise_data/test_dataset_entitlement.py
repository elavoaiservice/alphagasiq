"""`dataset_is_entitled` (docs/alpha-intelligence.md section 11.2, Milestone 10
follow-up): fine-grained per-dataset `EnterpriseDataEntitlement` enforcement."""

from __future__ import annotations

from enterprise_data_service import dataset_is_entitled
from schemas import EnterpriseDataEntitlement, EnterpriseEntitlementPrincipalType


_DATASET_ID = "00000000-0000-0000-0000-000000000001"


def _grant(principal_type: EnterpriseEntitlementPrincipalType, principal_id: str) -> EnterpriseDataEntitlement:
    return EnterpriseDataEntitlement(dataset_id=_DATASET_ID, principal_type=principal_type, principal_id=principal_id)


def test_no_entitlement_rows_defaults_to_visible():
    assert dataset_is_entitled(entitlements=[], user_id="u-1", roles=["TRADER"], workspace_ids=[]) is True


def test_matching_user_grant_is_entitled():
    grants = [_grant(EnterpriseEntitlementPrincipalType.USER, "u-1")]
    assert dataset_is_entitled(entitlements=grants, user_id="u-1", roles=[], workspace_ids=[]) is True


def test_non_matching_user_grant_is_not_entitled():
    grants = [_grant(EnterpriseEntitlementPrincipalType.USER, "u-other")]
    assert dataset_is_entitled(entitlements=grants, user_id="u-1", roles=[], workspace_ids=[]) is False


def test_matching_role_grant_is_entitled():
    grants = [_grant(EnterpriseEntitlementPrincipalType.ROLE, "TRADER")]
    assert dataset_is_entitled(entitlements=grants, user_id="u-1", roles=["TRADER", "VIEWER"], workspace_ids=[]) is True


def test_non_matching_role_grant_is_not_entitled():
    grants = [_grant(EnterpriseEntitlementPrincipalType.ROLE, "RISK_MANAGER")]
    assert dataset_is_entitled(entitlements=grants, user_id="u-1", roles=["TRADER"], workspace_ids=[]) is False


def test_matching_workspace_grant_is_entitled():
    grants = [_grant(EnterpriseEntitlementPrincipalType.WORKSPACE, "ws-1")]
    assert dataset_is_entitled(entitlements=grants, user_id="u-1", roles=[], workspace_ids=["ws-1", "ws-2"]) is True


def test_non_matching_workspace_grant_is_not_entitled():
    grants = [_grant(EnterpriseEntitlementPrincipalType.WORKSPACE, "ws-other")]
    assert dataset_is_entitled(entitlements=grants, user_id="u-1", roles=[], workspace_ids=["ws-1"]) is False


def test_agent_principal_grants_never_match_a_human_caller():
    """AGENT-type entitlements are for a future agent-classification integration --
    never evaluated against a human user, regardless of id overlap."""
    grants = [_grant(EnterpriseEntitlementPrincipalType.AGENT, "u-1")]
    assert dataset_is_entitled(entitlements=grants, user_id="u-1", roles=[], workspace_ids=[]) is False


def test_any_matching_grant_among_several_is_sufficient():
    grants = [
        _grant(EnterpriseEntitlementPrincipalType.USER, "u-other"),
        _grant(EnterpriseEntitlementPrincipalType.ROLE, "RISK_MANAGER"),
        _grant(EnterpriseEntitlementPrincipalType.WORKSPACE, "ws-1"),
    ]
    assert dataset_is_entitled(entitlements=grants, user_id="u-1", roles=["TRADER"], workspace_ids=["ws-1"]) is True


def test_no_matching_grant_among_several_is_not_entitled():
    grants = [
        _grant(EnterpriseEntitlementPrincipalType.USER, "u-other"),
        _grant(EnterpriseEntitlementPrincipalType.ROLE, "RISK_MANAGER"),
        _grant(EnterpriseEntitlementPrincipalType.WORKSPACE, "ws-other"),
    ]
    assert dataset_is_entitled(entitlements=grants, user_id="u-1", roles=["TRADER"], workspace_ids=["ws-1"]) is False
