"""Changelog — turns the repo's commit history into a clean, searchable,
date-grouped feed for the admin Changelog page.

Ported from ElavoAI's `src/server/services/admin/changelog.ts`, keeping its
behaviour: conventional-commit classification, keyword search across
subject/body/scope/sha/files, per-day grouping in Central Time, and a
"not deployed yet" marker for commits that exist but are not live.

**Where the history comes from differs, and deliberately.** ElavoAI shells out
to `git log` because its server runs in the repo. This API runs in a container
with no `.git` and no git binary, so the history is *baked into the image* at
build time (`infrastructure/docker/build_stamp.py` → `/app/changelog.json`).
That is the stronger guarantee: the feed describes exactly the code that is
running. Commits pushed after the build are fetched separately from GitHub
(`version.incoming_commits`) and marked `deploy_pending`, which is precisely
ElavoAI's `deployPending` — a commit that exists but has not shipped here.

Everything below `load_baked_commits` is pure, so the classification, search,
deploy-mapping and grouping are tested without a repo, a container, or a DB.
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime
from typing import Any, Iterable
from zoneinfo import ZoneInfo

CHANGELOG_PATH = os.environ.get("CHANGELOG_PATH", "/app/changelog.json")

# Matches the rest of the platform's operator-facing surfaces.
TZ = ZoneInfo("America/Chicago")

KNOWN_TYPES = {
    "feat", "fix", "docs", "refactor", "perf",
    "test", "chore", "style", "build", "ci", "revert",
}

# Conventional-commit type → display metadata. Mirrored by TYPE_STYLE in the UI.
COMMIT_TYPE_META: dict[str, dict[str, str]] = {
    "feat": {"label": "Feature", "emoji": "✨"},
    "fix": {"label": "Fix", "emoji": "🐛"},
    "perf": {"label": "Perf", "emoji": "⚡"},
    "refactor": {"label": "Refactor", "emoji": "♻️"},
    "docs": {"label": "Docs", "emoji": "📝"},
    "test": {"label": "Tests", "emoji": "🧪"},
    "build": {"label": "Build", "emoji": "📦"},
    "ci": {"label": "CI", "emoji": "🔧"},
    "style": {"label": "Style", "emoji": "💅"},
    "chore": {"label": "Chore", "emoji": "🧹"},
    "revert": {"label": "Revert", "emoji": "⏪"},
    "other": {"label": "Other", "emoji": "•"},
}

# type(scope)!: summary  |  type!: summary  |  type: summary
_SUBJECT_RE = re.compile(r"^([a-zA-Z]+)(?:\(([^)]+)\))?(!)?:\s*(.*)$")


def load_baked_commits() -> list[dict[str, Any]]:
    """The history baked into this image. Empty when unstamped (a dev
    `uvicorn --reload` run), which the endpoint reports honestly."""
    try:
        with open(CHANGELOG_PATH) as f:
            data = json.load(f)
    except (OSError, ValueError):
        return []
    commits = data.get("commits") if isinstance(data, dict) else None
    return commits if isinstance(commits, list) else []


def classify_subject(subject: str) -> dict[str, Any]:
    """Split a conventional-commit subject into type / scope / summary."""
    m = _SUBJECT_RE.match(subject)
    if not m:
        return {"type": "other", "scope": None, "summary": subject, "breaking": False}
    raw_type = m.group(1).lower()
    return {
        "type": raw_type if raw_type in KNOWN_TYPES else "other",
        "scope": m.group(2).strip() if m.group(2) else None,
        "summary": (m.group(4) or "").strip() or subject,
        "breaking": m.group(3) == "!" or "BREAKING CHANGE" in subject,
    }


def matches_query(commit: dict[str, Any], query: str) -> bool:
    """Case-insensitive match across subject, body, scope, sha prefix, and files."""
    q = query.strip().lower()
    if not q:
        return True
    if q in (commit.get("subject") or "").lower():
        return True
    if q in (commit.get("body") or "").lower():
        return True
    scope = commit.get("scope")
    if scope and q in scope.lower():
        return True
    if (commit.get("short_sha") or "").lower().startswith(q):
        return True
    return any(q in (f or "").lower() for f in commit.get("files") or [])


def attach_deploys(
    commits: list[dict[str, Any]],
    running_sha: str | None,
    deploys: Iterable[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Classify commits and attach the deploy that shipped each one.

    `commits` is newest-first. `deploys` are recorded builds -- each a
    ``{"commit_sha", "deployed_at"}`` for a build that actually served traffic.

    A build at index ``s`` in this newest-first list contains every commit at
    index ``>= s``. So the deploy that *first* shipped commit ``i`` is the one
    with the largest index ``s <= i`` (the oldest build that already contained
    it). Commits newer than the running build have shipped nowhere yet and are
    flagged ``deploy_pending``.
    """
    index_of = {c["sha"]: i for i, c in enumerate(commits) if c.get("sha")}

    # Recorded builds we can actually locate in this history, as (index, time).
    known: list[tuple[int, str]] = sorted(
        (index_of[d["commit_sha"]], d["deployed_at"])
        for d in deploys
        if d.get("commit_sha") in index_of and d.get("deployed_at")
    )

    running_idx = index_of.get(running_sha) if running_sha else None

    out: list[dict[str, Any]] = []
    for i, c in enumerate(commits):
        parts = classify_subject(c.get("subject") or "")
        deployed_at = None
        # Largest s <= i  →  the oldest recorded build that contained this commit.
        for s, when in known:
            if s <= i:
                deployed_at = when
            else:
                break
        out.append({
            **c,
            **parts,
            "short_sha": (c.get("sha") or "")[:7],
            "deployed_at": deployed_at,
            # Newer than what is running = committed but not live here.
            "deploy_pending": running_idx is not None and i < running_idx,
        })
    return out


def group_by_day(commits: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Bucket commits into per-day groups (Central Time), preserving order."""
    groups: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for c in commits:
        raw = c.get("committed_at") or ""
        try:
            local = datetime.fromisoformat(raw).astimezone(TZ)
        except ValueError:
            local = None
        key = local.strftime("%Y-%m-%d") if local else "unknown"
        label = local.strftime("%A, %B %-d, %Y") if local else "Unknown date"
        if current is None or current["date"] != key:
            current = {"date": key, "label": label, "commits": []}
            groups.append(current)
        current["commits"].append(c)
    return groups


def summarize_shipped(commits: list[dict[str, Any]]) -> dict[str, Any]:
    """Bucket into user-facing Features and Fixes, collapsing everything else
    into a count -- the "what shipped" summary strip."""
    features: list[dict[str, Any]] = []
    fixes: list[dict[str, Any]] = []
    other = 0
    for c in commits:
        parts = classify_subject(c.get("subject") or "")
        item = {"summary": parts["summary"], "scope": parts["scope"],
                "short_sha": (c.get("sha") or "")[:7]}
        if parts["type"] == "feat":
            features.append(item)
        elif parts["type"] == "fix":
            fixes.append(item)
        else:
            other += 1
    return {"features": features, "fixes": fixes, "other_count": other}
