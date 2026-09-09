"""Build/version provenance for the admin Upgrade page.

Three distinct facts, kept deliberately separate because conflating them is what
caused a real deploy incident (a `git pull` landed new commits, the image was
never rebuilt, and the portal had no way to show that the running code was old):

- **Running** (`build_info()`) — the commit the *image* was built from, stamped
  into `/app/build-info.json` at Docker build time by `Dockerfile.api`. This is
  the only honest answer to "what code is actually executing right now".
- **Checkout** (`checkout_info()`) — the commit the *host working tree* is on,
  read from the `/deploy/checkout-info.json` the upgrade agent writes, if any.
  When this is ahead of `running`, the host pulled but did not rebuild.
- **Remote** (`remote_info()`) — the newest commit on the tracked branch on
  GitHub, i.e. what an upgrade would pull.

Every lookup degrades to `None`/`error` rather than raising: the Upgrade page
must still render when the build was never stamped (a plain `uvicorn --reload`
dev run) or GitHub is unreachable.
"""
from __future__ import annotations

import json
import os
import time
from typing import Any

import httpx

from config import get_settings

_BUILD_INFO_PATH = os.environ.get("BUILD_INFO_PATH", "/app/build-info.json")
# Written by the host upgrade agent into the same shared volume the trigger file
# uses, so "what the host has checked out" survives without giving the API
# container the repo or a git binary.
_CHECKOUT_INFO_PATH = "/deploy/checkout-info.json"

_GITHUB_API = "https://api.github.com"
_TIMEOUT = 6.0
_CACHE_TTL_SECONDS = 60.0

_remote_cache: tuple[float, dict[str, Any]] | None = None


def _read_json(path: str) -> dict[str, Any]:
    try:
        with open(path) as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _short(sha: str | None) -> str | None:
    return sha[:7] if sha else None


def build_info() -> dict[str, Any]:
    """The commit this running image was built from. Empty dict when unstamped."""
    info = _read_json(_BUILD_INFO_PATH)
    if info.get("commit"):
        info.setdefault("commit_short", _short(info["commit"]))
    return info


def checkout_info() -> dict[str, Any]:
    """The commit the host working tree is on, if the upgrade agent reports it."""
    info = _read_json(_CHECKOUT_INFO_PATH)
    if info.get("commit"):
        info.setdefault("commit_short", _short(info["commit"]))
    return info


def tracked_branch() -> str:
    """Branch an upgrade would pull. Explicit setting first, else the branch this
    image was built from, else `main`."""
    settings = get_settings()
    return settings.upgrade_branch or build_info().get("branch") or "main"


def _github_headers() -> dict[str, str]:
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "AlphaGasIQ"}
    token = get_settings().github_token
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


async def remote_info(*, use_cache: bool = True) -> dict[str, Any]:
    """Newest commit on the tracked branch. Cached 60s so polling the Upgrade page
    every 2.5s does not burn GitHub's 60-req/hour unauthenticated budget."""
    global _remote_cache
    now = time.monotonic()
    if use_cache and _remote_cache and now - _remote_cache[0] < _CACHE_TTL_SECONDS:
        return _remote_cache[1]

    settings = get_settings()
    branch = tracked_branch()
    out: dict[str, Any] = {"repo": settings.upgrade_repo, "branch": branch}
    url = f"{_GITHUB_API}/repos/{settings.upgrade_repo}/commits/{branch}"
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as http:
            r = await http.get(url, headers=_github_headers())
        if r.status_code == 200:
            body = r.json()
            commit = body.get("commit") or {}
            out["commit"] = body.get("sha")
            out["commit_short"] = _short(body.get("sha"))
            out["subject"] = (commit.get("message") or "").split("\n")[0]
            out["committed_at"] = (commit.get("committer") or {}).get("date")
        elif r.status_code == 404:
            # Also what a private repo returns to an unauthenticated caller —
            # say so rather than claiming the branch does not exist.
            out["error"] = (
                f"GitHub returned 404 for {settings.upgrade_repo}@{branch} "
                "(wrong repo/branch, or a private repo with no GITHUB_TOKEN set)."
            )
        else:
            out["error"] = f"GitHub returned {r.status_code}."
    except httpx.HTTPError as e:
        out["error"] = f"Could not reach GitHub: {type(e).__name__}"

    _remote_cache = (now, out)
    return out


async def incoming_commits(base_sha: str, head_sha: str, *, limit: int = 25) -> list[dict[str, Any]]:
    """Commits in `base..head`, newest first — what an upgrade would bring in.
    Returns [] on any failure; the caller shows counts from the shas instead."""
    if not base_sha or not head_sha or base_sha == head_sha:
        return []
    settings = get_settings()
    url = f"{_GITHUB_API}/repos/{settings.upgrade_repo}/compare/{base_sha}...{head_sha}"
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as http:
            r = await http.get(url, headers=_github_headers())
        if r.status_code != 200:
            return []
        commits = r.json().get("commits") or []
    except (httpx.HTTPError, ValueError):
        return []
    out = [
        {
            "sha": _short(c.get("sha")),
            "subject": ((c.get("commit") or {}).get("message") or "").split("\n")[0],
            "author": ((c.get("commit") or {}).get("author") or {}).get("name"),
            "committed_at": ((c.get("commit") or {}).get("author") or {}).get("date"),
        }
        for c in commits
    ]
    out.reverse()  # GitHub returns oldest-first
    return out[:limit]


async def version_status() -> dict[str, Any]:
    """Everything the Upgrade page's version panel renders."""
    running = build_info()
    checkout = checkout_info()
    remote = await remote_info()

    running_sha = running.get("commit")
    remote_sha = remote.get("commit")
    checkout_sha = checkout.get("commit")

    up_to_date = bool(running_sha and remote_sha and running_sha == remote_sha)
    incoming = (
        await incoming_commits(running_sha, remote_sha)
        if running_sha and remote_sha and not up_to_date
        else []
    )

    # The exact failure that shipped a stale image: host pulled, image not rebuilt.
    rebuild_required = bool(checkout_sha and running_sha and checkout_sha != running_sha)

    return {
        "repo": get_settings().upgrade_repo,
        "branch": tracked_branch(),
        "environment": get_settings().environment,
        "running": running,
        "checkout": checkout,
        "remote": remote,
        "up_to_date": up_to_date,
        "rebuild_required": rebuild_required,
        "incoming": incoming,
        "incoming_count": len(incoming),
    }
