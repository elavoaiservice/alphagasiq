# Access Model — Accounts, Authentication, RBAC & Entitlements

> Status: Milestones 1-7. This document describes the target design end-to-end (per the
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
`User`. A magic-link user resolves permissions from their **real `UserRow.role_id`** — not from
`user.roles`. That distinction matters and was a real bug caught during Milestone 5 development:
`user.roles` for a magic-link session is `map_db_role_to_dev_roles(...)`'s *bridged-down* 5-value
set (§4a), built for `require_role` route gating — resolving permissions from it instead of the
real role would silently under-grant a `SUPER_ADMIN` (missing all four `SUPER_ADMIN`-only
permissions, since bridging maps them onto `ADMIN`-equivalent roles that don't carry those four)
and mis-grant `EXECUTIVE`/`API_USER` (bridged to bare `VIEWER`, discarding their real, broader
grants). Fixed by resolving from `state.repo.get_user_by_id(user.user_id)`'s `role_id` whenever a
real `UserRow` exists, falling back to unioning `user.roles`' DB-role grants only for dev-mode/
OIDC users who have no backing row at all — see
`tests/api/test_entitlements.py::test_magic_link_super_admin_gets_the_real_super_admin_only_permissions`
and its `EXECUTIVE` counterpart. `require_permission(key)` and `require_any_permission(*keys)` are FastAPI dependencies built on
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

## 6. Chief Trading Agent chat authorization

**Implemented now** (Milestone 5, spec §§25-29): `POST /chat/sessions/{id}/messages` requires the
`chief_agent.chat` permission (spec §26) — an unauthenticated or unentitled caller is rejected
before ever reaching `ChatAgent.ask()`. `POST /chat/sessions` itself stays open to anonymous
exploration (an empty conversation exposes nothing); the real gate is on sending a message.

Underneath that baseline gate, `ChatAgent.ask()` (`apps/api/api_app/chat_agent.py`) checks the
requesting user's effective permissions *before* invoking each tool — never after, and never
delegated to the LLM itself (the model cannot talk its way past a permission it doesn't have,
since it is never given the chance to). Each chat topic maps to the permission it needs
(`_TOOL_PERMISSIONS`, e.g. a portfolio/scenario question requires `portfolio.view`, matching spec
§28's own example "User without portfolio access: Cannot retrieve restricted portfolio data");
an ungranted permission short-circuits straight to a declined-access message without the real
tool ever touching `AppState`'s data, and without an LLM call being made at all. This is the
second, narrower authorization layer for roles that hold `chief_agent.chat` but not every
underlying data permission — defense in depth on top of the baseline gate, not a replacement for
it. See `tests/api/test_chat_agent.py` for unit coverage proving a declined topic never reaches
either `AppState` or the LLM.

Chat conversations are now durably persisted (spec §29): `ChatConversationRow`/`ChatMessageRow`
(`packages/db`) write through behind the existing in-memory `ChatSession`/`ChatMessage` response
contract (same pattern as `AppState`'s other durable objects) — user ID, organization ID,
timestamps, the message content, citations, freshness, which tool was used, which model produced
the reply, latency, and a permissions-context snapshot (roles + which permission was checked +
whether it was granted). No private chain-of-thought is ever persisted — there isn't one to begin
with, since the tool layer returns retrieved facts, not a reasoning transcript. `GET /chat/
conversations` / `GET /chat/conversations/{id}/messages` (gated by `admin.audit_logs`) give
administrators the visibility spec §29 calls for.

### Dashboard entitlement enforcement (spec §25)

`GET /auth/me/entitlements` (Milestone 4) is the read model; Milestone 5 wires real backend
enforcement for the two areas spec §25/§28 explicitly calls out by example: `GET /portfolio/*`
now requires the `portfolio_analytics` feature (`require_feature`), and `GET /risk/portfolio` now
requires `risk_analytics`. Both frontend consumers (`PositionsPanel.tsx`, `RiskSummaryCard.tsx`)
were updated to pass the session token — `RiskSummaryCard` in particular had to move from a
Server Component to a client component, since a Server Component has no access to the
browser-held session token `lib/auth-context.tsx` manages.

This is a deliberately scoped slice, not a full retrofit of every dashboard-adjacent endpoint
(market/fundamentals/news/quant/journal remain open, as they always have been in this codebase) —
extending `require_feature` to the rest of the dashboard's read endpoints is straightforward
follow-up work using the same mechanism, not a new one to build. A full admin-configurable
per-organization/per-user override UI for these entitlements is Milestone 6's job.

## 7. Administration

### Milestone 6: user/organization/feature management + system configuration

**Implemented now**: the admin console at `apps/web/app/platform/admin/*` (Overview, Users,
Organizations, Features, System Settings) — a client-side gate on the `ADMIN` dev-mode role
picks the console up or down for UX purposes only; every actual boundary is the API's own
`require_permission`/`require_any_permission` check, exactly as everywhere else in this document.

- `GET /admin/overview` (spec §31, `admin.dashboard`) reports active/invited/suspended user
  counts, active organizations, logins today, Chief Trading Agent query volume, paper-trading
  activity, and (as of Milestone 7) real data-feed health and staleness counts — computed from
  real data. Fields that depend on a subsystem not yet built (model health → Milestone 9/10; risk
  alerts and failed-authentication tracking → Milestone 10's audit log) are reported as `null`
  inside a `not_yet_available` list rather than fabricated.
- `PATCH /admin/users/{id}` (spec §32 "Edit user profile" / "Change organization" / "Change
  role" / "Set account expiration", `admin.users.edit`) is a partial update — only fields present
  in the request body change. `POST /admin/users/{id}/send-login-link` (`admin.users.edit`) is
  spec §32's "Send login Magic Link", distinct from "Resend Invitation" (only valid once a user
  is already `ACTIVE`, where resend-invitation only applies while still `INVITED`).
  `GET /admin/users/{id}/entitlements` (`admin.users.view`) is spec §32's "View feature usage" —
  an admin's view of another user's effective permissions/features, computed by the exact same
  `entitlements.py` functions `/auth/me/entitlements` uses on the caller's own identity.
- `PATCH /admin/organizations/{id}` (`admin.organizations`) covers spec §32 "Change data
  entitlements" and general organization-profile edits, again as a partial update.
- Feature management (spec §34): `GET/PUT /admin/features(/{key})` (global on/off switch,
  `admin.feature_management`), `GET/PUT /admin/roles/{role}/features(/{key})` (role-level grants,
  same permission), `PUT /admin/organizations/{id}/features/{key}` (org-level override, same
  permission), `PUT /admin/users/{id}/features/{key}` (per-user override — spec §32's "Enable/
  disable Chief Trading Agent / Portfolio Access / Risk Analytics / Paper Trading / API Access",
  gated by `admin.users.features`). The deny-override rule for `security_sensitive` features
  (§5 above) applies here exactly as it does to `/auth/me/entitlements` — an admin cannot use a
  per-user override to grant a sensitive feature the user's role/org don't already allow; only the
  role-level or org-level grant can do that.
- System configuration (spec §38): `SystemSettingRow`/`SystemSettingHistoryRow`
  (`packages/db`) back `GET/PUT /admin/settings(/{key})` and `GET /admin/settings/{key}/history`,
  gated by `admin.system_settings` — one of the four permissions reserved for `SUPER_ADMIN` alone
  (§5). Every write appends the setting's *previous* value/version to the history table before
  applying the new one, satisfying spec §38's "Versioned, Timestamped, Audited, Reversible where
  practical" — reversal today means an admin manually writing the desired historical value back;
  a one-click "restore to version N" action would be simple, uncontroversial follow-up work.

### Milestone 7: data-feed administration + health + dependency mapping (spec §§35-37)

**Implemented now**: `GET/PATCH /admin/data-feeds(/{provider_id})`,
`POST /admin/data-feeds/{provider_id}/test-connection`, `POST /admin/data-feeds/{provider_id}/refresh`,
`GET /admin/data-feeds/{provider_id}/events`, and `GET /admin/data-feeds/dependency-map`
(`apps/api/api_app/routers/admin_data_feeds.py`), all gated by `admin.data_feeds` (granted to
`ADMIN` and `SUPER_ADMIN`).

- `DataFeedConfigRow` (`packages/db`) holds the admin-editable knobs spec §36 calls for — enabled/
  paused, polling frequency, freshness threshold, priority, fallback provider, notes — seeded one
  row per currently-registered provider at boot (`AppState.seed()`), idempotently, so adding a new
  connector later never disturbs an admin's existing edits to the others. **It deliberately has no
  credential/secret field of any kind.** Every provider's API key is environment-provisioned via
  `packages/config/config/settings.py` and never touches the database or this admin surface at
  all — the strongest possible reading of this document's "credentials must never be redisplayed
  after entry," since there is no field here to redisplay in the first place.
- `GET /admin/data-feeds` merges that config with the *live* result of each provider's real
  `health_check()` (connection status, detail, last-checked time, freshness) and the static
  dependency map below, covering spec §35's field list. `data_quality_score` is reported as `null`
  — an honest stub, since no scoring model exists yet, rather than a fabricated number.
- `POST .../test-connection` and `POST .../refresh` call the provider's real `health_check()` /
  `fetch()` and record a `DataFeedEventRow` (`packages/db`) — the ingestion log spec §35 calls
  "Errors" and "Records Received." A provider exception is caught and recorded as an `error` event
  rather than raised as a 500: a feed failing is an expected, normal operating condition for a
  platform whose FERC/pipeline-bulletin-board/licensed-news/live-CME/live-ICE connectors are
  intentionally still `NotImplementedProvider` stubs (see `docs/data-sources.md`).
- `apps/api/api_app/data_feed_dependencies.py`'s static `_DEPENDENCIES` map answers spec §37's
  "which agents/business functions does this feed affect" and "show the full dependency chain" —
  built directly from `docs/agents.md` §2's real agent org chart, not fabricated. NOAA's chain is
  the spec's own worked example verbatim: `NOAA → Weather Agent → Demand Agent → Storage Agent →
  Forecasting Agent → Directional Strategy Agent → Chief Trading Agent → Trade Recommendation`.

### Milestones 8-10 (not yet built)

An AI Agent Control Center, agent versioning and a governed optimization workflow, model
management, risk settings, a real cross-cutting `AuditEvent` table, and system health/alerting —
all gated by RBAC, and all explicitly forbidden from reaching or modifying the Risk Governor's
rules (see `docs/risk-framework.md` — the Risk Governor has no admin- or agent-facing write path
today, and none will be added; agent "optimization" can only ever change an agent's own versioned
prompt/model/thresholds, never risk limits).
