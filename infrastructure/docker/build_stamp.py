"""Stamp a built image with the git history it came from.

Runs inside the throwaway `gitstamp` stage of `Dockerfile.api` (the only stage
that has `.git` and a git binary) and writes two files the runtime image reads:

- ``build-info.json`` — the single commit this image was built from
  (`api_app/version.py` → the Upgrade page's "Current").
- ``changelog.json``  — the commit history reachable from it
  (`api_app/changelog.py` → the admin Changelog page).

The history is baked rather than fetched so the Changelog reflects exactly what
is *in this build*. Commits pushed after the build are fetched separately from
GitHub and shown as not-yet-deployed, mirroring ElavoAI's `deployPending`.

Kept as a real file rather than an inline `RUN python3 -c` so it is readable and
unit-testable (`tests/api/test_build_stamp.py`).
"""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone

# ASCII unit/record separators: a commit body can contain anything except these.
FIELD_SEP = "\x1f"
RECORD_SEP = "\x1e"

# RECORD_SEP first so the body (trailing field) runs to the end of the record.
PRETTY_FORMAT = (
    f"{RECORD_SEP}%H{FIELD_SEP}%aI{FIELD_SEP}%cI{FIELD_SEP}%an{FIELD_SEP}%s{FIELD_SEP}%b"
)
# No body, so every trailing line from --name-only is unambiguously a file path.
FILES_FORMAT = f"{RECORD_SEP}%H"

MAX_COMMITS = 2000


def _git(git_dir: str, args: list[str]) -> str:
    return subprocess.run(
        ["git", "-c", "safe.directory=*", "--git-dir", git_dir, *args],
        check=True, capture_output=True, text=True,
    ).stdout


def parse_log(raw: str) -> list[dict]:
    """Parse PRETTY_FORMAT output into newest-first commit records."""
    out: list[dict] = []
    for chunk in raw.split(RECORD_SEP):
        if not chunk.strip():
            continue
        fields = chunk.split(FIELD_SEP)
        if len(fields) < 6:
            continue  # malformed — skip defensively rather than fail the build
        sha, authored_at, committed_at, author, subject, *body_parts = fields
        out.append({
            "sha": sha.strip(),
            "authored_at": authored_at.strip(),
            "committed_at": committed_at.strip(),
            "author": author.strip(),
            "subject": subject.strip(),
            "body": FIELD_SEP.join(body_parts).strip(),
            "files": [],
        })
    return out


def parse_name_only(raw: str) -> dict[str, list[str]]:
    """Parse FILES_FORMAT + --name-only output into {sha: [paths]}."""
    out: dict[str, list[str]] = {}
    for chunk in raw.split(RECORD_SEP):
        if not chunk.strip():
            continue
        lines = [ln.strip() for ln in chunk.split("\n") if ln.strip()]
        if not lines:
            continue
        out[lines[0]] = lines[1:]
    return out


def collect(git_dir: str) -> tuple[dict, list[dict]]:
    head = parse_log(_git(git_dir, ["log", "-1", f"--pretty=format:{PRETTY_FORMAT}"]))
    branch = _git(git_dir, ["rev-parse", "--abbrev-ref", "HEAD"]).strip()

    build_info = {
        "commit": head[0]["sha"] if head else None,
        "subject": head[0]["subject"] if head else None,
        "author": head[0]["author"] if head else None,
        "committed_at": head[0]["committed_at"] if head else None,
        # A detached HEAD has no branch name; say so rather than inventing one.
        "branch": None if branch == "HEAD" else branch,
        "built_at": datetime.now(timezone.utc).isoformat(),
    }

    commits = parse_log(_git(git_dir, [
        "log", f"--max-count={MAX_COMMITS}", "--no-merges", f"--pretty=format:{PRETTY_FORMAT}",
    ]))
    files_by_sha = parse_name_only(_git(git_dir, [
        "log", f"--max-count={MAX_COMMITS}", "--no-merges", "--name-only",
        f"--pretty=format:{FILES_FORMAT}",
    ]))
    for c in commits:
        c["files"] = files_by_sha.get(c["sha"], [])

    return build_info, commits


def main() -> int:
    git_dir = sys.argv[1] if len(sys.argv) > 1 else "/stamp/.git"
    out_dir = sys.argv[2] if len(sys.argv) > 2 else "/stamp"

    build_info, commits = collect(git_dir)
    with open(f"{out_dir}/build-info.json", "w") as f:
        json.dump(build_info, f)
    with open(f"{out_dir}/changelog.json", "w") as f:
        json.dump({"commits": commits, "generated_at": build_info["built_at"]}, f)

    print(f"build-info: {json.dumps(build_info)}")
    print(f"changelog: {len(commits)} commits baked")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
