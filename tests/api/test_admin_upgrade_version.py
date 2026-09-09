"""The admin Upgrade page's version panel (`api_app/version.py`).

Covers the distinction the module exists to make: what the running *image* was
built from vs. what the *host* has checked out vs. what is on the tracked
*branch*. Every GitHub call is stubbed -- these tests must never touch the
network.
"""

from __future__ import annotations

import json

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


@pytest.fixture(autouse=True)
def _clear_remote_cache():
    """`remote_info` caches for 60s process-wide; tests must not inherit it."""
    from api_app import version as version_module

    version_module._remote_cache = None
    yield
    version_module._remote_cache = None


def _headers(client, email: str, password: str) -> dict:
    login = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def _superadmin(client) -> dict:
    return _headers(client, "superadmin@alphagasiq.local", "superadmin-dev-password")


def _admin(client) -> dict:
    return _headers(client, "admin@alphagasiq.local", "admin-dev-password")


RUNNING = {"commit": "a" * 40, "commit_short": "aaaaaaa", "subject": "running commit", "branch": "main"}
REMOTE = {"commit": "b" * 40, "commit_short": "bbbbbbb", "subject": "newer commit", "branch": "main"}


def _stub(monkeypatch, *, running=None, checkout=None, remote=None, incoming=None):
    """version_status() resolves these through module globals at call time."""
    from api_app import version as v

    monkeypatch.setattr(v, "build_info", lambda: dict(running or {}))
    monkeypatch.setattr(v, "checkout_info", lambda: dict(checkout or {}))

    async def _remote(**_kwargs):
        return dict(remote or {})

    async def _incoming(_base, _head, **_kwargs):
        return list(incoming or [])

    monkeypatch.setattr(v, "remote_info", _remote)
    monkeypatch.setattr(v, "incoming_commits", _incoming)


# ── permissions ───────────────────────────────────────────────────────────────

def test_version_requires_super_admin(client, monkeypatch):
    _stub(monkeypatch, running=RUNNING, remote=REMOTE)
    assert client.get("/api/v1/admin/upgrade/version", headers=_admin(client)).status_code == 403


def test_version_allows_super_admin(client, monkeypatch):
    _stub(monkeypatch, running=RUNNING, remote=REMOTE)
    r = client.get("/api/v1/admin/upgrade/version", headers=_superadmin(client))
    assert r.status_code == 200
    assert r.json()["running"]["commit_short"] == "aaaaaaa"


# ── the three-way comparison ──────────────────────────────────────────────────

def test_up_to_date_reports_no_incoming(client, monkeypatch):
    _stub(monkeypatch, running=RUNNING, remote=dict(RUNNING), incoming=[{"sha": "zzzzzzz", "subject": "x"}])
    body = client.get("/api/v1/admin/upgrade/version", headers=_superadmin(client)).json()
    assert body["up_to_date"] is True
    # Same sha on both sides must short-circuit the compare call entirely.
    assert body["incoming"] == []
    assert body["incoming_count"] == 0


def test_behind_remote_lists_incoming_commits(client, monkeypatch):
    _stub(monkeypatch, running=RUNNING, remote=REMOTE,
          incoming=[{"sha": "bbbbbbb", "subject": "newer commit", "author": "Pat"}])
    body = client.get("/api/v1/admin/upgrade/version", headers=_superadmin(client)).json()
    assert body["up_to_date"] is False
    assert body["incoming_count"] == 1
    assert body["incoming"][0]["subject"] == "newer commit"


def test_pulled_but_not_rebuilt_sets_rebuild_required(client, monkeypatch):
    """The real incident: the host fast-forwarded, the image was never rebuilt,
    so the portal must not claim the new code is running."""
    _stub(monkeypatch, running=RUNNING, checkout=REMOTE, remote=REMOTE)
    body = client.get("/api/v1/admin/upgrade/version", headers=_superadmin(client)).json()
    assert body["rebuild_required"] is True
    assert body["running"]["commit_short"] == "aaaaaaa"


def test_checkout_matching_image_is_not_rebuild_required(client, monkeypatch):
    _stub(monkeypatch, running=RUNNING, checkout=dict(RUNNING), remote=REMOTE)
    body = client.get("/api/v1/admin/upgrade/version", headers=_superadmin(client)).json()
    assert body["rebuild_required"] is False


# ── honest degradation ────────────────────────────────────────────────────────

def test_unstamped_image_reports_unknown_not_an_error(client, monkeypatch):
    """A plain `uvicorn --reload` dev run has no build-info.json."""
    _stub(monkeypatch, running={}, remote=REMOTE)
    r = client.get("/api/v1/admin/upgrade/version", headers=_superadmin(client))
    assert r.status_code == 200
    body = r.json()
    assert body["running"] == {}
    assert body["up_to_date"] is False
    assert body["incoming"] == []  # nothing to compare against


def test_github_unreachable_still_renders(client, monkeypatch):
    _stub(monkeypatch, running=RUNNING, remote={"branch": "main", "error": "Could not reach GitHub: ConnectError"})
    r = client.get("/api/v1/admin/upgrade/version", headers=_superadmin(client))
    assert r.status_code == 200
    body = r.json()
    assert body["remote"]["error"].startswith("Could not reach GitHub")
    assert body["up_to_date"] is False


# ── build-info / branch resolution (no HTTP involved) ─────────────────────────

def test_build_info_reads_the_stamp_written_by_the_dockerfile(monkeypatch, tmp_path):
    from api_app import version as v

    stamp = tmp_path / "build-info.json"
    stamp.write_text(json.dumps({"commit": "c" * 40, "subject": 'a "quoted" subject', "branch": "main"}))
    monkeypatch.setattr(v, "_BUILD_INFO_PATH", str(stamp))

    info = v.build_info()
    assert info["commit_short"] == "ccccccc"
    assert info["subject"] == 'a "quoted" subject'


def test_build_info_missing_file_is_empty_not_raising(monkeypatch, tmp_path):
    from api_app import version as v

    monkeypatch.setattr(v, "_BUILD_INFO_PATH", str(tmp_path / "nope.json"))
    assert v.build_info() == {}


def test_tracked_branch_prefers_explicit_setting(monkeypatch):
    from api_app import version as v

    monkeypatch.setenv("UPGRADE_BRANCH", "release/2026-09")
    from config import get_settings

    get_settings.cache_clear()
    try:
        assert v.tracked_branch() == "release/2026-09"
    finally:
        monkeypatch.delenv("UPGRADE_BRANCH", raising=False)
        get_settings.cache_clear()


def test_tracked_branch_falls_back_to_the_branch_the_image_was_built_from(monkeypatch):
    from api_app import version as v
    from config import get_settings

    get_settings.cache_clear()
    monkeypatch.setattr(v, "build_info", lambda: {"branch": "feat/something"})
    assert v.tracked_branch() == "feat/something"


def test_tracked_branch_defaults_to_main(monkeypatch):
    from api_app import version as v
    from config import get_settings

    get_settings.cache_clear()
    monkeypatch.setattr(v, "build_info", lambda: {})
    assert v.tracked_branch() == "main"


@pytest.mark.asyncio
async def test_incoming_commits_short_circuits_on_equal_shas():
    """Must not issue an HTTP request at all when there is nothing to compare."""
    from api_app import version as v

    assert await v.incoming_commits("a" * 40, "a" * 40) == []
    assert await v.incoming_commits("", "b" * 40) == []


@pytest.mark.asyncio
async def test_incoming_commits_is_memoized_per_sha_pair(monkeypatch):
    """The Upgrade page polls every few seconds; without memoization each poll
    issued a fresh GitHub `compare`, exhausting the 60/hour anonymous budget."""
    from api_app import version as v

    v._compare_cache.clear()
    calls = {"n": 0}

    class _Resp:
        status_code = 200

        @staticmethod
        def json():
            return {"commits": [{"sha": "d" * 40, "commit": {"message": "feat: x", "author": {"name": "A"}}}]}

    class _Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, *a, **kw):
            calls["n"] += 1
            return _Resp()

    monkeypatch.setattr(v.httpx, "AsyncClient", lambda **kw: _Client())

    first = await v.incoming_commits("a" * 40, "b" * 40)
    second = await v.incoming_commits("a" * 40, "b" * 40)

    assert first == second
    assert calls["n"] == 1, "second call must be served from the memo, not GitHub"

    # A different pair is a genuine cache miss.
    await v.incoming_commits("a" * 40, "c" * 40)
    assert calls["n"] == 2
    v._compare_cache.clear()
