"""The account-state machine from docs/access-model.md §2 (spec §17).

Pure logic, no I/O — `routers/admin_users.py` is the only caller today, applying a
transition after loading/before saving a `User` row.
"""

from __future__ import annotations

from enum import Enum


class AccountStatus(str, Enum):
    INVITED = "INVITED"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    DISABLED = "DISABLED"
    EXPIRED = "EXPIRED"
    LOCKED = "LOCKED"
    REVOKED = "REVOKED"


# Per spec §17: "Only ACTIVE and eligible INVITED users may complete authentication
# flows" -- an INVITED user's only authenticable action is accepting their
# outstanding invitation link (Milestone 3), not an ordinary login.
AUTHENTICATABLE_STATUSES = frozenset({AccountStatus.ACTIVE, AccountStatus.INVITED})

# INVITED -> ACTIVE happens automatically when the invited user completes magic-link
# activation (Milestone 3), not through this admin-facing transition table -- so it is
# deliberately absent from INVITED's allowed targets here. REVOKED is terminal: access
# withdrawal is permanent by design, and a revoked user needs a brand-new account, not
# a resurrected one.
_ALLOWED_TRANSITIONS: dict[AccountStatus, frozenset[AccountStatus]] = {
    AccountStatus.INVITED: frozenset({AccountStatus.EXPIRED, AccountStatus.REVOKED}),
    AccountStatus.ACTIVE: frozenset(
        {AccountStatus.SUSPENDED, AccountStatus.DISABLED, AccountStatus.LOCKED, AccountStatus.REVOKED}
    ),
    AccountStatus.SUSPENDED: frozenset({AccountStatus.ACTIVE, AccountStatus.REVOKED}),
    AccountStatus.DISABLED: frozenset({AccountStatus.ACTIVE, AccountStatus.REVOKED}),
    AccountStatus.LOCKED: frozenset({AccountStatus.ACTIVE, AccountStatus.REVOKED}),
    AccountStatus.EXPIRED: frozenset({AccountStatus.ACTIVE, AccountStatus.REVOKED}),
    AccountStatus.REVOKED: frozenset(),
}


class InvalidAccountStateTransition(ValueError):
    def __init__(self, current: AccountStatus, target: AccountStatus) -> None:
        super().__init__(f"Cannot transition account from {current.value} to {target.value}")
        self.current = current
        self.target = target


def validate_transition(current: AccountStatus, target: AccountStatus) -> None:
    if target not in _ALLOWED_TRANSITIONS.get(current, frozenset()):
        raise InvalidAccountStateTransition(current, target)
