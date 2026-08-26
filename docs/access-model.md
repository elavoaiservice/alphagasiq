# Access Model — Accounts, Authentication, RBAC & Entitlements

> Status: Milestone 1 slice. This document describes the target design end-to-end (per the
> platform's access-model specification) and is updated incrementally as each milestone lands.
> Sections marked **(not yet built)** describe target behavior that ships in a later milestone —
> they are documented now so the design is reviewable as a whole, not discovered piecemeal.

## 1. Core invariant: admin-provisioned only

AlphaGasIQ is a private, institutional platform. **There is no self-registration path of any
kind.**

- No `/signup`, `/register`, `/request-access`, or `/create-account` route exists anywhere in
  `apps/web`, and none may be added.
- No endpoint creates a `User` row from an unauthenticated request. The only way a `User` row is
  ever created is an authenticated administrator calling `POST /admin/users` **(not yet built —
  Milestone 2)**.
- Knowing or entering an email address is never sufficient, by itself, to create an account or
  gain access.
- The public `/contact` page and its `POST /contact` endpoint are a business-inquiry form only.
  `ContactInquiryRow` (`packages/db/db/models.py`) has no foreign key to and no code path toward
  `User`/`Organization`/`MagicLinkToken` — this is enforced structurally (those tables/relations
  don't exist on `ContactInquiryRow`), not just documented, and is covered by
  `tests/api/test_api.py::test_contact_form_never_creates_a_user_or_session`, which positively
  attempts a login with the submitted email afterward and asserts it's rejected.

## 2. Account lifecycle **(state machine defined; enforcement lands Milestone 2)**

```
Admin creates user (POST /admin/users)
        │
        ▼
     INVITED  ──(magic-link invitation accepted)──▶  ACTIVE
        │                                                │
        │ (invitation expires, never accepted)           │  ── admin action ──▶  SUSPENDED
        ▼                                                │  ── admin action ──▶  DISABLED
     EXPIRED                                              │  ── time-based ──▶  EXPIRED
                                                            │  ── failed logins ──▶  LOCKED
                                                            └── admin action ──▶  REVOKED
```

States: `INVITED`, `ACTIVE`, `SUSPENDED`, `DISABLED`, `EXPIRED`, `LOCKED`, `REVOKED`. Only
`ACTIVE` (and `INVITED`, for the purpose of completing an outstanding invitation) may
authenticate. Every other state fails closed.

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

## 5. RBAC and feature entitlements **(not yet built — Milestone 4)**

- `Role` / `Permission` / `RolePermission` tables, seeded with 8 fixed roles and their permission
  grants at schema-init time.
- `Feature` / `RoleFeatureEntitlement` / `OrganizationFeatureEntitlement` /
  `UserFeatureOverride`, with effective access computed as: globally enabled AND role grants it
  AND organization grants it AND NOT explicitly denied at the user level. For
  `security_sensitive` features, a user-level override may only ever narrow access, never grant
  access the role/org tier doesn't already allow — a deny always wins.
- Every enforcement point is server-side (new `require_permission(...)`/`require_feature(...)`
  FastAPI dependencies, alongside today's `require_role`). The frontend may hide UI based on the
  user's effective permission set (returned by `/auth/me`), but that is UX only — it grants
  nothing on its own.

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
