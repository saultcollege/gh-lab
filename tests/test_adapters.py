"""Tests for the external-tool adapters.

The adapters are deliberately thin, so these cover the failure translation that
lets the command layer degrade a check to "skipped" instead of failing.
"""

import json
import subprocess

import pytest

from gh_lab.adapters import AdapterError, git, github_cli


class FakeCompleted:
    def __init__(self, stdout="", stderr="", returncode=0):
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode


# --- git -------------------------------------------------------------------


def test_current_branch_returns_the_branch(monkeypatch):
    monkeypatch.setattr(
        subprocess, "run", lambda *a, **k: FakeCompleted(stdout="lab-1\n")
    )

    assert git.current_branch() == "lab-1"


def test_current_branch_is_none_when_head_is_detached(monkeypatch):
    """GitHub Actions checks out a pull request as a detached HEAD."""
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: FakeCompleted(stdout="\n"))

    assert git.current_branch() is None


def test_git_failure_becomes_an_adapter_error(monkeypatch):
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *a, **k: FakeCompleted(stderr="not a git repository", returncode=128),
    )

    with pytest.raises(AdapterError, match="not a git repository"):
        git.repo_root()


def test_missing_git_becomes_an_adapter_error(monkeypatch):
    def missing(*args, **kwargs):
        raise FileNotFoundError

    monkeypatch.setattr(subprocess, "run", missing)

    with pytest.raises(AdapterError, match="not installed"):
        git.current_branch()


# --- gh --------------------------------------------------------------------


def test_repo_view_parses_json(monkeypatch):
    payload = {"name": "csd110-lab-1", "isPrivate": True}
    monkeypatch.setattr(
        subprocess, "run", lambda *a, **k: FakeCompleted(stdout=json.dumps(payload))
    )

    assert github_cli.repo_view()["name"] == "csd110-lab-1"


def test_unauthenticated_gh_becomes_an_adapter_error(monkeypatch):
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *a, **k: FakeCompleted(stderr="gh auth login required", returncode=1),
    )

    with pytest.raises(AdapterError, match="auth login"):
        github_cli.repo_view()


def test_list_collaborators_returns_logins(monkeypatch):
    payload = [{"login": "student"}, {"login": "bobber24"}, {"not": "a login"}]
    monkeypatch.setattr(
        subprocess, "run", lambda *a, **k: FakeCompleted(stdout=json.dumps(payload))
    )

    assert github_cli.list_collaborators("student", "repo") == ("student", "bobber24")


# --- fetching a file from a repository -------------------------------------


def test_fetch_repo_file_returns_raw_contents(monkeypatch):
    monkeypatch.setattr(
        subprocess, "run", lambda *a, **k: FakeCompleted(stdout='{"faculty": []}')
    )

    assert github_cli.fetch_repo_file("org", "course-config", "26f.json") == (
        '{"faculty": []}'
    )


def test_fetch_repo_file_requests_raw_content_and_caches(monkeypatch):
    """The raw media type avoids a base64 envelope; the cache avoids a request."""
    seen = []

    def record(args, **kwargs):
        seen.append(args)
        return FakeCompleted(stdout="{}")

    monkeypatch.setattr(subprocess, "run", record)
    github_cli.fetch_repo_file("org", "course-config", "26f.json")

    (argv,) = seen
    assert "Accept: application/vnd.github.raw+json" in argv
    assert "--cache" in argv
    assert "repos/org/course-config/contents/26f.json" in argv


def test_fetch_repo_file_pins_a_ref_when_given(monkeypatch):
    seen = []
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda args, **k: (seen.append(args), FakeCompleted(stdout="{}"))[1],
    )

    github_cli.fetch_repo_file("org", "course-config", "26f.json", "spring")

    assert "repos/org/course-config/contents/26f.json?ref=spring" in seen[0]


def test_unreadable_file_becomes_an_adapter_error(monkeypatch):
    """GitHub answers 404 whether the repo is missing or merely invisible."""
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *a, **k: FakeCompleted(stderr="HTTP 404: Not Found", returncode=1),
    )

    with pytest.raises(AdapterError, match="404"):
        github_cli.fetch_repo_file("org", "course-config", "26f.json")


def test_collaborators_are_not_cached(monkeypatch):
    """A student who just sent an invitation must see fresh data."""
    seen = []
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda args, **k: (seen.append(args), FakeCompleted(stdout="[]"))[1],
    )

    github_cli.list_collaborators("student", "repo")

    assert "--cache" not in seen[0]
