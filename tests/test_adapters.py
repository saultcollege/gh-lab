"""Tests for the external-tool adapters.

The adapters are deliberately thin, so these cover the failure translation that
lets the command layer degrade a check to "skipped" instead of failing.
"""

import json
import subprocess
import urllib.error

import pytest

from gh_lab.adapters import AdapterError, git, github_cli, http


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


# --- http ------------------------------------------------------------------


def test_fetch_json_rejects_non_http_urls():
    """urlopen would otherwise read local files."""
    with pytest.raises(AdapterError, match="not an http"):
        http.fetch_json("file:///etc/passwd")


def test_fetch_json_reports_an_unreachable_url(monkeypatch):
    def unreachable(*args, **kwargs):
        raise urllib.error.URLError("name resolution failed")

    monkeypatch.setattr(http.urllib.request, "urlopen", unreachable)

    with pytest.raises(AdapterError, match="could not reach"):
        http.fetch_json("https://example.invalid/course-config.json")
