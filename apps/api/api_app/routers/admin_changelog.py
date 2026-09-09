"""Admin Changelog API — every change shipped to the system, newest first.

Mirrors ElavoAI's `/api/admin/changelog`: a searchable, day-grouped commit feed
that tells an operator *what* changed and *when it went live*, rather than
making them read `git log`.

The history is baked into the image at build time and the deploy times come
from `deploy_log` (written on startup, once per build), so this endpoint needs
neither a git binary nor a checkout in the container. Commits pushed after this
build are fetched from GitHub and marked `deploy_pending`.

Gated by `admin.dashboard` -- any admin should be able to see what shipped, not
just a SUPER_ADMIN.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from ..auth import User
from ..changelog import (
    COMMIT_TYPE_META,
    attach_deploys,
    group_by_day,
    load_baked_commits,
    matches_query,
    summarize_shipped,
)
from ..entitlements import require_permission
from ..deps import AppStateDep
from ..version import build_info, remote_info, tracked_branch

router = APIRouter(prefix="/admin/changelog", tags=["admin-changelog"])

_RequireDashboard = Depends(require_permission("admin.dashboard"))

DEFAULT_LIMIT = 50
MAX_LIMIT = 200


async def _unreleased_commits(running_sha: str | None) -> list[dict]:
    """Commits on the tracked branch newer than this build — the ones an upgrade
    would bring in. Empty (never an error) when GitHub is unreachable."""
    if not running_sha:
        return []
    remote = await remote_info()
    head = remote.get("commit")
    if not head or head == running_sha:
        return []
    from ..version import incoming_commits

    raw = await incoming_commits(running_sha, head, limit=200)
    # Shape them like baked commits so one code path classifies both.
    return [
        {
            "sha": c.get("full_sha") or c.get("sha") or "",
            "subject": c.get("subject") or "",
            "body": "",
            "author": c.get("author"),
            "committed_at": c.get("committed_at") or "",
            "authored_at": c.get("committed_at") or "",
            "files": [],
        }
        for c in raw
    ]


@router.get("")
async def get_changelog(
    state: AppStateDep,
    q: str = Query("", description="Keyword filter over subject/body/scope/sha/files"),
    offset: int = Query(0, ge=0),
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    _admin: User = _RequireDashboard,
) -> dict:
    running = build_info()
    running_sha = running.get("commit")

    baked = load_baked_commits()
    # Newer-than-this-build commits go on top; the baked history is already
    # newest-first, so the concatenation stays correctly ordered.
    #
    # De-duplicate by sha, keeping the first (GitHub) copy. In a correctly stamped
    # image the two lists cannot overlap -- the baked history is generated from the
    # same HEAD as build-info.json, so GitHub's base..head range starts after it.
    # But a mismatched stamp (a hand-edited build-info, a partially-rebuilt image)
    # would otherwise list commits twice AND corrupt the deploy mapping, which keys
    # off each sha's index in this list.
    seen: set[str] = set()
    commits: list[dict] = []
    for c in await _unreleased_commits(running_sha) + baked:
        sha = c.get("sha")
        if not sha or sha in seen:
            continue
        seen.add(sha)
        commits.append(c)

    try:
        deploys = await state.repo.list_deploys()
    except Exception:  # a fresh DB with no deploy_log yet must not 500 the page
        deploys = []

    classified = attach_deploys(commits, running_sha, deploys)
    filtered = [c for c in classified if matches_query(c, q)] if q.strip() else classified

    page = filtered[offset : offset + limit]
    latest = deploys[0] if deploys else None

    return {
        "total": len(filtered),
        "offset": offset,
        "limit": limit,
        "has_more": offset + limit < len(filtered),
        "scanned": len(commits),
        # An unstamped image (dev `uvicorn --reload`) has no baked history at all;
        # say so rather than rendering an empty feed as though nothing shipped.
        "history_available": bool(baked),
        "running_sha": running_sha,
        "branch": tracked_branch(),
        "latest_deploy": latest,
        "type_meta": COMMIT_TYPE_META,
        "shipped": summarize_shipped(page),
        "groups": group_by_day(page),
    }
