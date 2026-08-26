# Access Model — Accounts, Authentication, RBAC & Entitlements

> Status: Milestones 1-4. This document describes the target design end-to-end (per the
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
invitation (Milestone 3, now real — see §3). Duplicate email (case-insensitive) is rejected with
`409`; an unrecognized `role` is rejected with `400`. `GET /admin/users`/`GET /admin/users/{id}`
resolve `organization_name`/`role_name` for display. `POST /admin/organizations`/
`GET /admin/organizations` manage organizations directly. `POST /admin/users/{id}/resend-
invitation` (spec §18) is only valid while `INVITED`. `GET /admin/users/{id}/sessions` /
`POST /admin/users/{id}/sessions/{id}/revoke` give an admin visibility into and control over a
user's active sessions (spec §20). See `docs/api-specification.md` for the full endpoint table
and `tests/api/test_admin_users.py`/`tests/api/test_magic_link_auth.py` for the enforcement/
state-machine/dedup/email/session tests.

## 3. Authentication: magic link, no passwords

**Implemented now** (Milestone 3):

- `POST /auth/magic-link/request {email}` (`apps/api/api_app/routers/auth.py`) always returns
  the same generic response — `{"detail": "If an authorized AlphaGasIQ account exists for this
  email, a secure sign-in link has been sent."}` — for every email, whether or not it matches a
  user, whether the account is eligible, and whether the request was rate-limited. Underneath
  that fixed response: an unknown email or an ineligible account status (anything but `ACTIVE`/
  `INVITED`) is a silent no-op; an `ACTIVE` user gets a login link (`magic_link.
  issue_and_send_login_link`); a still-`INVITED` user gets a fresh invitation link instead (spec
  §21 — this is exactly the "Resend Invitation" flow, just triggered from `/login` rather than
  the admin console). Rate-limited per email and per IP independently
  (`apps/api/api_app/rate_limit.py`'s in-memory sliding window, default 5 requests / 15 minutes
  per identifier — see `packages/config/config/settings.py`'s `magic_link_rate_limit_*` settings).
- `GET /auth/magic-link/verify?token=...` hashes the presented token (`apps/api/api_app/
  magic_link.py::hash_token`, sha256 — only the hash is ever persisted, in `MagicLinkTokenRow.
  token_hash`), looks it up by hash, and checks in order: exists, not consumed, not revoked, not
  expired, and the owning user is still in an authenticatable status. It then marks the token
  consumed (so it can never be replayed), promotes an `INVITED` user to `ACTIVE` (the *only* code
  path that does this — see §2), creates a `Session` row, and redirects to
  `/platform#access_token=...` exactly like the existing OIDC callback.
- The user never receives a plaintext password, temporary password, or raw authentication secret
  in any email — only a single-use magic-link URL with a 15-minute expiry
  (`magic_link_expire_minutes`). `apps/api/api_app/email_service.py`'s templates are checked by
  `tests/api/test_magic_link_auth.py::test_create_user_sends_invitation_email_with_magic_link_and_no_secret`,
  which literally asserts the words "password"/"secret" never appear in the rendered email body.
- `/login` (`apps/web/app/login/page.tsx`) is the primary entry point: an email field and a
  single "Send Secure Magic Link" button. It always shows the same generic success copy after
  submission, regardless of what was entered.
- `apps/api/api_app/oidc.py`'s Authorization Code + PKCE SSO flow is unaffected by any of this —
  it remains an additive, optional login path alongside magic link.

### Bootstrap credentials (a deliberate exception, not an oversight)

The existing dev-mode password grant (`POST /auth/login`, `_DEV_USERS` in `apps/api/api_app/
auth.py`) is **kept permanently**, not removed in this milestone as earlier drafts of this doc
assumed — but its role changes: it is now explicitly the platform's fixed break-glass/bootstrap
credential set, not a general password-login feature for real end users.

Real accounts (`UserRow`) never authenticate with a password — they always go through magic link
or OIDC SSO, satisfying the spec's "no plaintext passwords" requirement for actual users. But
`POST /admin/users` itself requires an authenticated administrator, and magic-link auth requires
a `UserRow` to already exist to send a link to — something has to authenticate the very first
operator before any `UserRow` exists to create more. `_DEV_USERS` is that something: a small,
fixed, non-self-service set of operator credentials, structurally disconnected from the `users`
table (it is never joined to `UserRow`, never created by any endpoint, and never reachable by an
arbitrary email the way the spec's "no self-registration" rule cares about). This is the same
pattern real IAM systems use (a cloud provider's root account, a seeded Django/Rails superuser) —
a deliberate, reviewed design decision, not a gap. Before any production deployment, these
credentials must be rotated out of source and replaced with real secrets management
(`packages/config`'s `jwt_secret` carries the identical caveat already).

## 4. Sessions

**Implemented now** (Milestone 3): `SessionRow` (`packages/db/db/models.py`) backs every
magic-link-issued JWT via a `sid` claim (`apps/api/api_app/auth.py::create_access_token`). A
dev-mode or OIDC-issued token carries no `sid` claim and is completely unaffected — it decodes
exactly as it always has, with no DB round trip (`decode_access_token` only touches `state.repo`
when `sid` is present). This is a deliberate refinement of the `sub=session_id` design floated in
earlier drafts of this doc: `sub` stays the real, stable `user_id` (so `created_by`,
`current_user_id`, and every other place this codebase treats `user_id` as a durable identity
keep working unchanged), and a *separate* `sid` claim carries the revocable session pointer. This
achieves the actual goal — server-side revocation — without corrupting `user_id`'s meaning
elsewhere in the codebase.

- `POST /auth/logout` revokes the caller's `Session` row (a no-op for a dev-mode/OIDC token,
  which has none).
- `GET /auth/sessions` lists the caller's own sessions (spec §20 "Device/session history").
- `GET /admin/users/{id}/sessions` / `POST /admin/users/{id}/sessions/{id}/revoke` give an
  administrator the same visibility and an explicit revoke action (spec §20 "Admin-initiated
  session revocation" / "view active sessions without exposing session secrets" — a `Session` row
  has no secret field to begin with, so nothing needs redacting).
- Idle/absolute timeout: a session's fixed `expires_at` (`magic_link_session_minutes`, default
  480) *is* the absolute timeout — an idle-specific (shorter, activity-resetting) timeout is not
  yet implemented separately; `last_seen_at`/`touch_session()` exist in the schema/repository to
  support adding one without a migration, once a milestone actually calls for it.
- Secure-cookie/HttpOnly/SameSite/CSRF: this platform's session token travels as a bearer token
  in the `Authorization` header (the same contract OIDC already established), not a cookie —
  there is no cookie-based CSRF surface to protect against under this transport. If a
  cookie-based session transport is ever added, it must ship with the CSRF protections spec §20
  calls for; nothing today needs them because nothing today sets an auth cookie.

## 4a. Role -> dev-mode `Role` bridge

A magic-link-authenticated user's session JWT still needs to carry *some* value every router's
`require_role` check understands (`apps/api/api_app/auth.py`'s 5-value `Role` enum) for the
handful of routers Milestone 4 didn't touch (trading/risk/approvals/agents — still gated by
`require_role`, unchanged since before this milestone). `auth.py::map_db_role_to_dev_roles`
bridges the 8 DB roles to that 5-value enum, mirroring the capability composition the
`_DEV_USERS` fixtures already use (e.g. a DB `TRADER` maps to `{TRADER, RESEARCHER, VIEWER}`, the
same set `trader@alphagasiq.local` carries):

| DB role | Mapped dev-mode roles |
|---|---|
| `SUPER_ADMIN` | `ADMIN`, `TRADER`, `RISK_MANAGER`, `RESEARCHER`, `VIEWER` |
| `ADMIN` | `ADMIN`, `TRADER`, `RISK_MANAGER`, `RESEARCHER`, `VIEWER` |
| `TRADER` | `TRADER`, `RESEARCHER`, `VIEWER` |
| `RISK_MANAGER` | `RISK_MANAGER`, `VIEWER` |
| `RESEARCHER` | `RESEARCHER`, `VIEWER` |
| `EXECUTIVE` | `VIEWER` |
| `VIEWER` | `VIEWER` |
| `API_USER` | `VIEWER` |

An unrecognized DB role name never raises — it falls back to `VIEWER`-only, mirroring
`oidc.py`'s existing "unrecognized claim -> VIEWER" posture. This same mapping is also the
foundation of Milestone 4's real permission resolution below: because every `Role` enum value is
string-identical to a real DB role name, `entitlements.py` can resolve permissions/features
directly from `user.roles` with no per-login-path special-casing at all.

## 5. RBAC and feature entitlements

`Role` / `Permission` / `RolePermission` tables (`packages/db/db/models.py`), seeded at every
boot by `SqlAppRepository.seed_rbac_defaults()` (idempotent). The 8 fixed roles: `SUPER_ADMIN`,
`ADMIN`, `TRADER`, `RISK_MANAGER`, `RESEARCHER`, `EXECUTIVE`, `VIEWER`, `API_USER`. The full
permission-key list:

`dashboard.view`, `market_data.view`, `weather.view`, `storage.view`, `pipeline.view`,
`lng.view`, `power.view`, `news.view`, `trading_recommendations.view`,
`trading_recommendations.challenge`, `chief_agent.chat`, `portfolio.view`, `portfolio.manage`,
`risk.view`, `risk.manage`, `paper_trading.view`, `paper_trading.execute`, `data_export`,
`api_access`, `admin.dashboard`, `admin.users.view`, `admin.users.create`, `admin.users.edit`,
`admin.users.suspend`, `admin.users.revoke`, `admin.users.permissions`, `admin.users.features`,
`admin.users.sessions`, `admin.organizations`, `admin.data_feeds`, `admin.system_settings`,
`admin.agent_management`, `admin.agent_optimization`, `admin.model_management`,
`admin.audit_logs`, `admin.feature_management`, `admin.risk_settings`.

Each role's default grants (`_ROLE_PERMISSIONS` in `packages/db/db/repository.py`): `SUPER_ADMIN`
gets every permission; `ADMIN` gets every permission except the four reserved for `SUPER_ADMIN`
alone (`admin.system_settings`, `admin.risk_settings`, `admin.agent_optimization`,
`admin.model_management`); the remaining roles get a role-appropriate subset of `*.view`/
`*.manage`/`*.execute` permissions.

**Enforcement is now real** (Milestone 4): `apps/api/api_app/entitlements.py`'s
`get_effective_permissions(user, state)` resolves a live permission set for *any* authenticated
`User` — dev-mode, OIDC, or magic-link alike — by unioning `state.repo.get_permission_keys_for_role(role.value)`
across every role the user carries (safe because of §4a's role/DB-name identity).
`require_permission(key)` and `require_any_permission(*keys)` are FastAPI dependencies built on
top of it; `ensure_permission(user, state, key)` is the same check for use mid-handler, when the
required permission depends on the request body (e.g. a status-change endpoint whose needed
permission varies by target status). Every `/admin/*` route (`admin_users.py`) is now gated by
the real permission the access-model spec assigns it (`admin.users.create`, `admin.organizations`,
`admin.users.suspend`/`admin.users.revoke`/`admin.users.edit` depending on the target status,
etc.) instead of the placeholder `require_role(Role.ADMIN)` check — verified not to regress
existing authorization outcomes for the `_DEV_USERS` fixtures (`ADMIN`'s DB-role permission set
still covers every admin action those tests exercise; `TRADER`/`RISK_MANAGER`/etc. still get 403).
`GET /auth/me/entitlements` exposes a user's effective permissions + feature map for the frontend
to consume (Milestone 5's job — nothing reads this endpoint's output to gate anything server-side
today; every real enforcement point calls `entitlements.py` directly).

### Feature entitlements

`Feature` / `RoleFeatureEntitlement` / `OrganizationFeatureEntitlement` / `UserFeatureOverride`
tables, seeded by `SqlAppRepository.seed_feature_defaults()` with the 18 features from spec §24
(Market Dashboard, Natural Gas Fundamentals, Weather/Storage/Pipeline/LNG/Power/News
Intelligence, AI Trade Recommendations, Chief Trading Agent Chat, Portfolio Analytics, Risk
Analytics, Natural Gas Digital Twin, Historical Research, Data Export, API Access, Paper Trading,
Experimental Features) and each role's default grants. `entitlements.py::get_effective_features`
computes, per feature:

```
effective = globally_enabled AND role_grants AND org_grants AND NOT user_denied
```

Role-level access is deny-by-default (a role only has a feature if an explicit
`RoleFeatureEntitlementRow` says so); organization-level is allow-by-default (an org row only
ever *restricts* below what the role already grants — a client's plan excluding "Experimental
Features" regardless of role, say). The `security_sensitive` flag (set on
`chief_trading_agent_chat`, `portfolio_analytics`, `risk_analytics`, `data_export`, `api_access`,
`paper_trading`, `experimental_features`) governs how a per-user override behaves: for a
non-sensitive feature, a `UserFeatureOverride` can freely grant or deny regardless of role/org;
for a `security_sensitive` one, an override can only narrow access — an `enabled=True` override
can never grant a sensitive feature that role/org don't already allow. This is spec §24's
"deny-overrides for security-sensitive features" implemented exactly.

`require_feature(key)` (a FastAPI dependency, same shape as `require_permission`) exists now but
isn't wired to any user-facing route yet — that's Milestone 5's job (dashboard/chat integration,
spec §25 "Only display functionality the authenticated user is entitled to access... both UI and
backend APIs must enforce entitlements").

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
