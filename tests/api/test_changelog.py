"""The admin Changelog (`api_app/changelog.py` + `/admin/changelog`).

The pure functions are tested directly; the endpoint is tested with the baked
history pointed at a fixture file, so nothing here needs a git repo, a container
or the network.
"""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from api_app.changelog import (
    attach_deploys,
    classify_subject,
    group_by_day,
    load_baked_commits,
    matches_query,
    summarize_shipped,
)


# ── conventional-commit classification ────────────────────────────────────────

@pytest.mark.parametrize(
    "subject,expected_type,expected_scope,expected_summary",
    [
        ("feat(admin): Upgrade version panel", "feat", "admin", "Upgrade version panel"),
        ("fix: declare anthropic dependency", "fix", None, "declare anthropic dependency"),
        ("docs(readme): add a Stack section", "docs", "readme", "add a Stack section"),
        ("chore(deps): bump things", "chore", "deps", "bump things"),
        # An unrecognised type word falls back to `other`, but the scope/summary
        # split still applies (matching ElavoAI's classifySubject).
        ("wibble(x): something", "other", "x", "something"),
        # No conventional prefix at all.
        ("Merge branch 'main'", "other", None, "Merge branch 'main'"),
    ],
)
def test_classify_subject(subject, expected_type, expected_scope, expected_summary):
    got = classify_subject(subject)
    assert got["type"] == expected_type
    assert got["scope"] == expected_scope
    assert got["summary"] == expected_summary


def test_classify_subject_detects_breaking_change():
    assert classify_subject("feat(api)!: drop v1")["breaking"] is True
    assert classify_subject("feat(api): keep v1")["breaking"] is False


# ── search ────────────────────────────────────────────────────────────────────

def _commit(**kw):
    base = {"sha": "a" * 40, "short_sha": "aaaaaaa", "subject": "feat(x): thing",
            "body": "", "scope": "x", "files": [], "committed_at": "2026-09-09T12:00:00+00:00"}
    base.update(kw)
    return base


def test_matches_query_across_every_field():
    c = _commit(subject="feat(storage): forecast", body="uses EIA weekly data",
                scope="storage", files=["services/data/eia.py"])
    assert matches_query(c, "storage")          # scope + subject
    assert matches_query(c, "EIA")              # body, case-insensitive
    assert matches_query(c, "services/data")    # file path
    assert matches_query(c, "aaaaaa")           # sha prefix
    assert not matches_query(c, "nonexistent")


def test_empty_query_matches_everything():
    assert matches_query(_commit(), "")
    assert matches_query(_commit(), "   ")


# ── deploy mapping ────────────────────────────────────────────────────────────

def _history(*shas):
    """Newest-first commits with the given shas."""
    return [
        {"sha": s, "subject": f"feat: {s}", "body": "", "files": [],
         "committed_at": "2026-09-09T12:00:00+00:00"}
        for s in shas
    ]


def test_commits_newer_than_the_running_build_are_pending():
    commits = _history("new2", "new1", "running", "old1")
    out = attach_deploys(commits, "running", [])
    pending = {c["sha"]: c["deploy_pending"] for c in out}
    assert pending == {"new2": True, "new1": True, "running": False, "old1": False}


def test_deploy_time_comes_from_the_oldest_build_that_contained_the_commit():
    # History newest-first; two recorded builds.
    commits = _history("c4", "c3", "c2", "c1")
    deploys = [
        {"commit_sha": "c4", "deployed_at": "2026-09-09T15:00:00"},  # newer build
        {"commit_sha": "c2", "deployed_at": "2026-09-09T10:00:00"},  # older build
    ]
    out = {c["sha"]: c["deployed_at"] for c in attach_deploys(commits, "c4", deploys)}
    # c1 and c2 were already in the older build → its earlier time.
    assert out["c1"] == "2026-09-09T10:00:00"
    assert out["c2"] == "2026-09-09T10:00:00"
    # c3 and c4 only exist in the newer build.
    assert out["c3"] == "2026-09-09T15:00:00"
    assert out["c4"] == "2026-09-09T15:00:00"


def test_deploys_referencing_unknown_shas_are_ignored():
    """A deploy whose commit was rewritten or predates the baked window must not
    crash the feed or mis-assign a time."""
    commits = _history("c2", "c1")
    out = attach_deploys(commits, "c2", [{"commit_sha": "gone", "deployed_at": "2026-01-01T00:00:00"}])
    assert all(c["deployed_at"] is None for c in out)


def test_no_running_sha_means_nothing_is_marked_pending():
    out = attach_deploys(_history("c2", "c1"), None, [])
    assert all(c["deploy_pending"] is False for c in out)


# ── grouping ──────────────────────────────────────────────────────────────────

def test_group_by_day_buckets_consecutive_commits():
    commits = [
        {"sha": "a", "committed_at": "2026-09-09T18:00:00+00:00", "subject": "feat: a"},
        {"sha": "b", "committed_at": "2026-09-09T14:00:00+00:00", "subject": "feat: b"},
        {"sha": "c", "committed_at": "2026-09-08T14:00:00+00:00", "subject": "feat: c"},
    ]
    groups = group_by_day(commits)
    assert [g["date"] for g in groups] == ["2026-09-09", "2026-09-08"]
    assert len(groups[0]["commits"]) == 2
    assert "September" in groups[0]["label"]


def test_group_by_day_survives_an_unparseable_timestamp():
    groups = group_by_day([{"sha": "a", "committed_at": "not-a-date", "subject": "x"}])
    assert groups[0]["date"] == "unknown"


def test_group_by_day_uses_central_time_not_utc():
    """00:30 UTC is still the previous evening in Central Time — grouping by the
    raw UTC date would put it on the wrong day."""
    groups = group_by_day([{"sha": "a", "committed_at": "2026-09-10T00:30:00+00:00", "subject": "x"}])
    assert groups[0]["date"] == "2026-09-09"


# ── shipped summary ───────────────────────────────────────────────────────────

def test_summarize_shipped_splits_features_fixes_and_counts_the_rest():
    got = summarize_shipped([
        {"sha": "1" * 7, "subject": "feat(a): one"},
        {"sha": "2" * 7, "subject": "fix(b): two"},
        {"sha": "3" * 7, "subject": "docs: three"},
        {"sha": "4" * 7, "subject": "chore: four"},
    ])
    assert [f["summary"] for f in got["features"]] == ["one"]
    assert [f["summary"] for f in got["fixes"]] == ["two"]
    assert got["other_count"] == 2


# ── baked-history loading ─────────────────────────────────────────────────────

def test_load_baked_commits_missing_file_is_empty(monkeypatch, tmp_path):
    from api_app import changelog as cl

    monkeypatch.setattr(cl, "CHANGELOG_PATH", str(tmp_path / "nope.json"))
    assert cl.load_baked_commits() == []


def test_load_baked_commits_reads_the_stamped_file(monkeypatch, tmp_path):
    from api_app import changelog as cl

    f = tmp_path / "changelog.json"
    f.write_text(json.dumps({"commits": [{"sha": "x", "subject": "feat: hi"}]}))
    monkeypatch.setattr(cl, "CHANGELOG_PATH", str(f))
    assert len(cl.load_baked_commits()) == 1


# ── endpoint ──────────────────────────────────────────────────────────────────

@pytest.fixture
def client():
    from api_app import state as state_module

    state_module.reset_app_state()
    from api_app.main import app

    with TestClient(app) as c:
        yield c
    state_module.reset_app_state()


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    """The endpoint asks GitHub for not-yet-deployed commits; stub it out."""
    from api_app import version as v

    async def _remote(**_kw):
        return {"branch": "main", "commit": None}

    monkeypatch.setattr(v, "remote_info", _remote)
    v._remote_cache = None
    yield
    v._remote_cache = None


def _headers(client, email, password):
    r = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def test_changelog_endpoint_returns_grouped_commits(client, monkeypatch, tmp_path):
    from api_app import changelog as cl

    f = tmp_path / "changelog.json"
    f.write_text(json.dumps({"commits": [
        {"sha": "a" * 40, "subject": "feat(admin): panel", "body": "detail",
         "files": ["apps/api/x.py"], "committed_at": "2026-09-09T18:00:00+00:00"},
        {"sha": "b" * 40, "subject": "fix(db): thing", "body": "",
         "files": [], "committed_at": "2026-09-08T18:00:00+00:00"},
    ]}))
    monkeypatch.setattr(cl, "CHANGELOG_PATH", str(f))

    r = client.get("/api/v1/admin/changelog", headers=_headers(client, "admin@alphagasiq.local", "admin-dev-password"))
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 2
    assert body["history_available"] is True
    assert len(body["groups"]) == 2
    assert body["groups"][0]["commits"][0]["type"] == "feat"
    assert body["groups"][0]["commits"][0]["scope"] == "admin"


def test_changelog_endpoint_filters_by_query(client, monkeypatch, tmp_path):
    from api_app import changelog as cl

    f = tmp_path / "changelog.json"
    f.write_text(json.dumps({"commits": [
        {"sha": "a" * 40, "subject": "feat(admin): panel", "body": "", "files": [],
         "committed_at": "2026-09-09T18:00:00+00:00"},
        {"sha": "b" * 40, "subject": "fix(db): storage thing", "body": "", "files": [],
         "committed_at": "2026-09-08T18:00:00+00:00"},
    ]}))
    monkeypatch.setattr(cl, "CHANGELOG_PATH", str(f))

    h = _headers(client, "admin@alphagasiq.local", "admin-dev-password")
    r = client.get("/api/v1/admin/changelog?q=storage", headers=h)
    assert r.json()["total"] == 1


def test_changelog_endpoint_requires_admin(client):
    r = client.get("/api/v1/admin/changelog",
                   headers=_headers(client, "trader@alphagasiq.local", "trader-dev-password"))
    assert r.status_code == 403


def test_changelog_endpoint_reports_missing_history_honestly(client, monkeypatch, tmp_path):
    from api_app import changelog as cl

    monkeypatch.setattr(cl, "CHANGELOG_PATH", str(tmp_path / "absent.json"))
    r = client.get("/api/v1/admin/changelog",
                   headers=_headers(client, "admin@alphagasiq.local", "admin-dev-password"))
    assert r.status_code == 200
    assert r.json()["history_available"] is False


def test_endpoint_deduplicates_overlap_between_github_and_baked_history(client, monkeypatch, tmp_path):
    """A mismatched build stamp can make the GitHub 'unreleased' range overlap the
    baked history. Listing a commit twice would also corrupt the deploy mapping,
    which keys off each sha's index in the combined list."""
    from api_app import changelog as cl
    from api_app.routers import admin_changelog as router_mod

    f = tmp_path / "changelog.json"
    f.write_text(json.dumps({"commits": [
        {"sha": "a" * 40, "subject": "feat: dup", "body": "", "files": [],
         "committed_at": "2026-09-09T18:00:00+00:00"},
        {"sha": "b" * 40, "subject": "fix: older", "body": "", "files": [],
         "committed_at": "2026-09-08T18:00:00+00:00"},
    ]}))
    monkeypatch.setattr(cl, "CHANGELOG_PATH", str(f))

    async def _overlapping(_running):
        # Same sha as the newest baked commit.
        return [{"sha": "a" * 40, "subject": "feat: dup", "body": "", "author": None,
                 "committed_at": "2026-09-09T18:00:00+00:00", "authored_at": "", "files": []}]

    monkeypatch.setattr(router_mod, "_unreleased_commits", _overlapping)

    body = client.get(
        "/api/v1/admin/changelog",
        headers=_headers(client, "admin@alphagasiq.local", "admin-dev-password"),
    ).json()

    shas = [c["sha"] for g in body["groups"] for c in g["commits"]]
    assert shas == ["a" * 40, "b" * 40]
    assert body["total"] == 2
