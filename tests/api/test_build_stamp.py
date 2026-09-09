"""`infrastructure/docker/build_stamp.py` — the git → JSON stamping that feeds the
Upgrade page's "Current" version and the Changelog's baked history.

The parsing is what can silently corrupt the feed (a commit body containing the
delimiter, a quote, a newline), so it is tested against the real repo and against
hostile synthetic input.
"""
from __future__ import annotations

import importlib.util
import pathlib
import subprocess

import pytest

_PATH = pathlib.Path(__file__).resolve().parents[2] / "infrastructure" / "docker" / "build_stamp.py"
_spec = importlib.util.spec_from_file_location("build_stamp", _PATH)
build_stamp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(build_stamp)

FIELD_SEP = build_stamp.FIELD_SEP
RECORD_SEP = build_stamp.RECORD_SEP


def _record(sha, authored, committed, author, subject, body):
    return (
        f"{RECORD_SEP}{sha}{FIELD_SEP}{authored}{FIELD_SEP}{committed}"
        f"{FIELD_SEP}{author}{FIELD_SEP}{subject}{FIELD_SEP}{body}"
    )


def test_parse_log_reads_all_fields():
    raw = _record("a" * 40, "2026-09-09T10:00:00-05:00", "2026-09-09T11:00:00-05:00",
                  "David Turner", "feat(x): thing", "body line")
    got = build_stamp.parse_log(raw)
    assert len(got) == 1
    assert got[0]["sha"] == "a" * 40
    assert got[0]["author"] == "David Turner"
    assert got[0]["subject"] == "feat(x): thing"
    assert got[0]["body"] == "body line"


def test_parse_log_preserves_a_multiline_body():
    body = "line one\n\nline two\nCo-Authored-By: someone"
    raw = _record("b" * 40, "t1", "t2", "A", "fix: y", body)
    assert build_stamp.parse_log(raw)[0]["body"] == body


def test_parse_log_survives_quotes_and_backslashes_in_the_subject():
    """The reason the format is NUL-separated rather than JSON-templated in git."""
    subject = 'fix: handle a "quoted" path C:\\temp and a comma, too'
    raw = _record("c" * 40, "t1", "t2", "A", subject, "")
    assert build_stamp.parse_log(raw)[0]["subject"] == subject


def test_parse_log_skips_malformed_records_instead_of_failing_the_build():
    raw = _record("d" * 40, "t1", "t2", "A", "feat: ok", "") + f"{RECORD_SEP}truncated"
    got = build_stamp.parse_log(raw)
    assert len(got) == 1
    assert got[0]["subject"] == "feat: ok"


def test_parse_log_on_empty_input():
    assert build_stamp.parse_log("") == []


def test_parse_name_only_maps_shas_to_paths():
    raw = (
        f"{RECORD_SEP}{'a' * 40}\napps/api/x.py\nREADME.md\n"
        f"{RECORD_SEP}{'b' * 40}\nservices/data/y.py\n"
    )
    got = build_stamp.parse_name_only(raw)
    assert got["a" * 40] == ["apps/api/x.py", "README.md"]
    assert got["b" * 40] == ["services/data/y.py"]


def test_parse_name_only_handles_a_commit_that_touched_no_files():
    raw = f"{RECORD_SEP}{'a' * 40}\n"
    assert build_stamp.parse_name_only(raw) == {"a" * 40: []}


# ── against the real repository ───────────────────────────────────────────────

def _in_git_repo() -> bool:
    root = pathlib.Path(__file__).resolve().parents[2]
    try:
        subprocess.run(["git", "--git-dir", str(root / ".git"), "rev-parse", "HEAD"],
                       check=True, capture_output=True)
        return True
    except Exception:
        return False


@pytest.mark.skipif(not _in_git_repo(), reason="needs the real .git (absent in a source tarball)")
def test_collect_against_this_repo_produces_a_usable_stamp():
    root = pathlib.Path(__file__).resolve().parents[2]
    info, commits = build_stamp.collect(str(root / ".git"))

    assert info["commit"] and len(info["commit"]) == 40
    assert info["built_at"]
    assert commits, "the repo has commits, so the baked history must not be empty"
    # Newest-first, and HEAD is the first entry.
    assert commits[0]["sha"] == info["commit"]
    # Every record carries the fields the changelog reads.
    for c in commits[:10]:
        assert c["sha"] and c["subject"] is not None and c["committed_at"]
        assert isinstance(c["files"], list)
