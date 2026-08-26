"""Pure unit tests for the account-state machine (docs/access-model.md §2, spec §17).
No HTTP/DB involved -- `test_admin_users.py` covers the endpoint wiring on top of this.
"""

from __future__ import annotations

import pytest
from api_app.account_states import AccountStatus, InvalidAccountStateTransition, validate_transition


@pytest.mark.parametrize(
    "current,target",
    [
        (AccountStatus.INVITED, AccountStatus.EXPIRED),
        (AccountStatus.INVITED, AccountStatus.REVOKED),
        (AccountStatus.ACTIVE, AccountStatus.SUSPENDED),
        (AccountStatus.ACTIVE, AccountStatus.DISABLED),
        (AccountStatus.ACTIVE, AccountStatus.LOCKED),
        (AccountStatus.ACTIVE, AccountStatus.REVOKED),
        (AccountStatus.SUSPENDED, AccountStatus.ACTIVE),
        (AccountStatus.SUSPENDED, AccountStatus.REVOKED),
        (AccountStatus.DISABLED, AccountStatus.ACTIVE),
        (AccountStatus.LOCKED, AccountStatus.ACTIVE),
        (AccountStatus.EXPIRED, AccountStatus.ACTIVE),
    ],
)
def test_allowed_transitions_do_not_raise(current, target):
    validate_transition(current, target)  # must not raise


@pytest.mark.parametrize(
    "current,target",
    [
        (AccountStatus.INVITED, AccountStatus.ACTIVE),  # only via magic-link activation, not admin action
        (AccountStatus.REVOKED, AccountStatus.ACTIVE),  # REVOKED is terminal
        (AccountStatus.REVOKED, AccountStatus.SUSPENDED),
        (AccountStatus.ACTIVE, AccountStatus.INVITED),  # no transition ever goes back to INVITED
        (AccountStatus.SUSPENDED, AccountStatus.DISABLED),  # must go through ACTIVE first
    ],
)
def test_disallowed_transitions_raise(current, target):
    with pytest.raises(InvalidAccountStateTransition):
        validate_transition(current, target)


def test_revoked_has_no_outbound_transitions_at_all():
    for target in AccountStatus:
        if target is AccountStatus.REVOKED:
            continue
        with pytest.raises(InvalidAccountStateTransition):
            validate_transition(AccountStatus.REVOKED, target)
