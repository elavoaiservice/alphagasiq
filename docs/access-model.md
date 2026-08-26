# Access Model — Accounts, Authentication, RBAC & Entitlements

> Status: Milestones 1-2. This document describes the target design end-to-end (per the
> platform's access-model specification) and is updated incrementally as each milestone lands.
> Sections marked **(not yet built)** describe target behavior that ships in a later milestone —
> they are documented now so the design is reviewable as a whole, not discovered piecemeal.

## 1. Core invariant: admin-provisioned only

AlphaGasIQ is a private, institutional platform. **There is no self-registration path of any
kind.**

- No `/signup`, `/register`, `/request-access`, or `/create-account` route exists anywhere in
  `apps/web`, and none may be added.
- No endpoint creates a `User` row from an unauthenticated request. The only way a `User` row is
  ever created is an authenticated administrator calling `POST /admin/users`
  (`apps/api/api_app/routers/admin_users.py`, gated by `require_role(Role.ADMIN)`).
- Knowing or entering an email address is never sufficient, by itself, to create an account or
  gain access.
- The public `/contact` page and its `POST /contact` endpoint are a business-inquiry form only.
  `ContactInquiryRow` (`packages/db/db/models.py`) has no foreign key to and no code path toward
  `User`/`Organization`/`MagicLinkToken` — this is enforced structurally (those tables/relations
  don't exist on `ContactInquiryRow`), not just documented, and is covered by
  `tests/api/test_api.py::test_contact_form_never_creates_a_user_or_session`, which positively
  attempts a login with the submitted email afterward and asserts it's rejected.

## 2. Account lifecycle

```
Admin creates user (POST /admin/users)
        │
        ▼
     INVITED  ──(magic-link invitation accepted, Milestone 3)──▶  ACTIVE
        │                                                            │
        │ ── admin: POST /admin/users/{id}/status ──▶ EXPIRED         │  ── admin ──▶ SUSPENDED
        │ ── admin: POST /admin/users/{id}/status ──▶ REVOKED (terminal)  ── admin ──▶ DISABLED
                                                                       │  ── (M3) failed logins ──▶ LOCKED
                                                                       └── admin ──▶ REVOKED (terminal)
```

States: `INVITED`, `ACTIVE`, `SUSPENDED`, `DISABLED`, `EXPIRED`, `LOCKED`, `REVOKED`. Only
`ACTIVE` (and `INVITED`, for the purpose of completing an outstanding invitation) may
authenticate. Every other state fails closed.

**Implemented now** (`apps/api/api_app/account_states.py`, exercised via
`POST /admin/users/{user_id}/status`): a fixed transition table enforces the legal moves —
`INVITED`→{`EXPIRED`,`REVOKED`}, `ACTIVE`→{`SUSPENDED`,`DISABLED`,`LOCKED`,`REVOKED`}, and
`SUSPENDED`/`DISABLED`/`LOCKED`/`EXPIRED`→{`ACTIVE`,`REVOKED`}. `REVOKED` is terminal — nothing
transitions out of it, by design (a revoked user needs a brand-new account, not a resurrected
one). `INVITED`→`ACTIVE` is deliberately **not** in this admin-facing table: it only ever happens
by completing the magic-link invitation (Milestone 3), never by admin fiat — an admin can revoke
an outstanding invitation but cannot manually activate one. See
`tests/api/test_account_states.py` for the full transition matrix under test.

## 2a. Admin-created users & organizations (Milestone 2)

`POST /admin/users` (`apps/api/api_app/routers/admin_users.py`) is the platform's only writer of
`User` rows. Request fields follow the access-model spec's required-field list (first/last name,
business email, company name, job title, phone, country, state/region, department, primary use
case, market experience, role); `company_name` drives the organization lookup-or-create-inline
behavior — an existing organization (matched by exact name) is reused, otherwise a new one is
created from `company_name`/`company_website`/`company_type`/`country`/`state_region`. Every
created user starts `INVITED` regardless of what's requested in the payload (there is no `status`
field on the request model at all) — the only way to reach `ACTIVE` is completing the magic-link
invitation once Milestone 3 wires it. Duplicate email (case-insensitive) is rejected with `409`;
an unrecognized `role` is rejected with `400`. `GET /admin/users`/`GET /admin/users/{id}` resolve
`organization_name`/`role_name` for display. `POST /admin/organizations`/`GET /admin/organizations`
manage organizations directly. See `docs/api-specification.md` for the full endpoint table and
`tests/api/test_admin_users.py` for the enforcement/state-machine/dedup tests.

## 3. Authentication: magic link, no passwords

- `POST /auth/magic-link/request {email}` — **implemented now** as an honest placeholder: it
  already returns the platform's final, non-enumerating response —
  `{"message": "If an authorized AlphaGasIQ account exists for this email, a secure sign-in link
  has been sent."}` — for every email, whether or not it matches a user, so the endpoint can never
  be used to enumerate accounts. Real lookup, `MagicLinkToken` issuance, and email dispatch land
  in Milestone 3 behind this same response contract (the response text does not change).
- `GET /auth/magic-link/verify?token=...` **(not yet built — Milestone 3)** — hashes the
  presented token, looks it up by hash only (the raw token is never stored), checks
  expiry/consumption/revocation/user-status, marks it consumed, creates a `Session` row, and
  redirects to `/platform#access_token=...` exactly like the existing OIDC callback does today
  (`apps/api/api_app/routers/auth.py`).
- The user never receives a plaintext password, temporary password, or raw authentication secret
  in any email — only a single-use magic-link URL with a short expiry (~15 minutes).
- `/login` (`apps/web/app/login/page.tsx`) is the primary entry point: an email field and a
  single "Send Secure Magic Link" button. It always shows the same generic success copy after
  submission, regardless of what was entered.
- The existing dev-mode password grant (`POST /auth/login`, `_DEV_USERS`) remains available
  through Milestone 2 only, so the platform stays usable while the real account/session system is
  built out. It is removed in Milestone 3 once magic-link auth is real, since a standing password
  grant would directly conflict with this platform's "no plaintext passwords" requirement.
- `apps/api/api_app/oidc.py`'s Authorization Code + PKCE SSO flow is unaffected by any of this —
  it remains an additive, optional login path alongside magic link.

## 4. Sessions **(not yet built — Milestone 3)**

Session JWTs will carry `sub=session_id` (not `sub=user_id`), backed by a `Session` table, so a
session can be revoked server-side (today's dev-mode/OIDC JWTs are intentionally stateless and
carry `sub=user_id`-equivalent claims directly — revocation isn't possible today, which is
acceptable for a stub auth mode but not for the production account system).

## 5. RBAC and feature entitlements

**Implemented now** (Milestone 2): `Role` / `Permission` / `RolePermission` tables
(`packages/db/db/models.py`), seeded at every boot by
`SqlAppRepository.seed_rbac_defaults()` (idempotent — safe to re-run). The 8 fixed roles:
`SUPER_ADMIN`, `ADMIN`, `TRADER`, `RISK_MANAGER`, `RESEARCHER`, `EXECUTIVE`, `VIEWER`,
`API_USER`. The full permission-key list (verbatim from the platform's access-model
specification):

`dashboard.view`, `market_data.view`, `weather.view`, `storage.view`, `pipeline.view`,
`lng.view`, `power.view`, `news.view`, `trading_recommendations.view`,
`trading_recommendations.challenge`, `chief_agent.chat`, `portfolio.view`, `portfolio.manage`,
`risk.view`, `risk.manage`, `paper_trading.view`, `paper_trading.execute`, `data_export`,
`api_access`, `admin.dashboard`, `admin.users.view`, `admin.users.create`, `admin.users.edit`,
`admin.users.suspend`, `admin.users.revoke`, `admin.users.permissions`, `admin.users.features`,
`admin.users.sessions`, `admin.organizations`, `admin.data_feeds`, `admin.system_settings`,
`admin.agent_management`, `admin.agent_optimization`, `admin.model_management`,
`admin.audit_logs`, `admin.feature_management`, `admin.risk_settings`.

Each role's default grants (`packages/db/db/repository.py`'s `_ROLE_PERMISSIONS`) are a
reviewable initial default: `SUPER_ADMIN` gets every permission; `ADMIN` gets every permission
except the four reserved for `SUPER_ADMIN` alone (`admin.system_settings`, `admin.risk_settings`,
`admin.agent_optimization`, `admin.model_management` — the system-level/risk/model/agent-
optimization controls this platform keeps behind its strictest boundary, see
`docs/risk-framework.md`); the remaining roles get a role-appropriate subset of `*.view`/
`*.manage`/`*.execute` permissions. This mapping is not yet read by any enforcement path — it
exists so `User.role_id` has real rows to reference, and so the eventual Milestone 4 cutover
edits an already-correct default rather than inventing one from scratch.

**Not yet built (Milestone 4)**:
- `Feature` / `RoleFeatureEntitlement` / `OrganizationFeatureEntitlement` /
  `UserFeatureOverride`, with effective access computed as: globally enabled AND role grants it
  AND organization grants it AND NOT explicitly denied at the user level. For
  `security_sensitive` features, a user-level override may only ever narrow access, never grant
  access the role/org tier doesn't already allow — a deny always wins.
- Every enforcement point is server-side (new `require_permission(...)`/`require_feature(...)`
  FastAPI dependencies, alongside today's `require_role`). Every `/admin/*` endpoint currently
  enforces `require_role(Role.ADMIN)` (`apps/api/api_app/auth.py`'s 5-value dev-mode `Role` enum)
  as an interim mechanism — not yet the DB-backed `admin.users.create`-style permission check the
  spec calls for, since there is no session/user-identity bridge yet between a dev-mode/OIDC JWT
  and a `UserRow` (that bridge is part of Milestone 3's session work). The frontend may hide UI
  based on the user's effective permission set (returned by `/auth/me`), but that is UX only — it
  grants nothing on its own.

## 6. Chief Trading Agent chat authorization **(not yet built — Milestone 5)**

`ChatAgent.ask()` will check the requesting user's effective permissions/entitlements *before*
invoking each tool (e.g. a portfolio question requires `portfolio.view`), never after and never
delegated to the LLM itself — the model cannot talk its way past a permission it doesn't have.

## 7. Administration **(not yet built — Milestones 6-10)**

An admin console (`apps/web/app/(admin)/...`) for user/organization/feature/data-feed/system
management, an AI Agent Control Center, agent versioning and a governed optimization workflow,
and model/risk-settings management, audit log, and system health — all gated by RBAC, all
writing to the append-only `AuditEvent` table, and all explicitly forbidden from reaching or
modifying the Risk Governor's rules (see `docs/risk-framework.md` — the Risk Governor has no
admin- or agent-facing write path today, and none will be added; agent "optimization" can only
ever change an agent's own versioned prompt/model/thresholds, never risk limits).
