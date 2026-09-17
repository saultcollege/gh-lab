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


# --- organization membership -----------------------------------------------


def test_set_org_membership_reports_a_new_invitation(monkeypatch):
    payload = {"state": "pending", "role": "member"}
    monkeypatch.setattr(
        subprocess, "run", lambda *a, **k: FakeCompleted(stdout=json.dumps(payload))
    )

    assert github_cli.set_org_membership("course-org", "student") == "pending"


def test_set_org_membership_reports_an_existing_member(monkeypatch):
    """Re-running an invite must be distinguishable from inviting afresh."""
    payload = {"state": "active", "role": "member"}
    monkeypatch.setattr(
        subprocess, "run", lambda *a, **k: FakeCompleted(stdout=json.dumps(payload))
    )

    assert github_cli.set_org_membership("course-org", "student") == "active"


def test_set_org_membership_sends_a_put_with_the_role(monkeypatch):
    """gh api switches to POST once a field is given, so PUT must be explicit."""
    seen = []

    def record(args, **kwargs):
        seen.append(args)
        return FakeCompleted(stdout='{"state": "pending"}')

    monkeypatch.setattr(subprocess, "run", record)
    github_cli.set_org_membership("course-org", "student")

    (argv,) = seen
    assert argv[:2] == ["gh", "api"]
    assert argv[argv.index("-X") + 1] == "PUT"
    assert argv[argv.index("-f") + 1] == "role=member"
    assert argv[-1] == "orgs/course-org/memberships/student"


def test_set_org_membership_can_invite_an_owner(monkeypatch):
    seen = []
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda args, **k: (
            seen.append(args),
            FakeCompleted(stdout='{"state": "pending"}'),
        )[1],
    )

    github_cli.set_org_membership("course-org", "prof", "admin")

    assert "role=admin" in seen[0]


def test_set_org_membership_is_not_cached(monkeypatch):
    """A write must never be served from gh's response cache."""
    seen = []
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda args, **k: (
            seen.append(args),
            FakeCompleted(stdout='{"state": "pending"}'),
        )[1],
    )

    github_cli.set_org_membership("course-org", "student")

    assert "--cache" not in seen[0]


def test_a_membership_failure_becomes_an_adapter_error(monkeypatch):
    """Inviting without being an organization owner is the expected mistake."""
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *a, **k: FakeCompleted(stderr="HTTP 403: Forbidden", returncode=1),
    )

    with pytest.raises(AdapterError, match="403"):
        github_cli.set_org_membership("course-org", "student")


def test_a_membership_response_without_a_state_is_rejected(monkeypatch):
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: FakeCompleted(stdout="{}"))

    with pytest.raises(AdapterError, match="membership state"):
        github_cli.set_org_membership("course-org", "student")


def test_a_membership_response_that_is_not_an_object_is_rejected(monkeypatch):
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: FakeCompleted(stdout="[]"))

    with pytest.raises(AdapterError, match="unexpected response"):
        github_cli.set_org_membership("course-org", "student")


# --- repository invitations ------------------------------------------------


def test_listing_invitations_flattens_the_pages(monkeypatch):
    """--slurp returns an array of pages, not an array of invitations."""
    pages = [[{"id": 1}, {"id": 2}], [{"id": 3}]]
    monkeypatch.setattr(
        subprocess, "run", lambda *a, **k: FakeCompleted(stdout=json.dumps(pages))
    )

    invitations = github_cli.list_repository_invitations()

    assert [entry["id"] for entry in invitations] == [1, 2, 3]


def test_listing_invitations_paginates_and_slurps(monkeypatch):
    """Without --slurp the pages are separate documents and will not parse."""
    seen = []
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda args, **k: (seen.append(args), FakeCompleted(stdout="[[]]"))[1],
    )

    github_cli.list_repository_invitations()

    (argv,) = seen
    assert "--paginate" in argv
    assert "--slurp" in argv
    assert argv[-1] == "user/repository_invitations"


def test_listing_invitations_is_not_cached(monkeypatch):
    """Someone reviewing invitations has usually just asked for one."""
    seen = []
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda args, **k: (seen.append(args), FakeCompleted(stdout="[[]]"))[1],
    )

    github_cli.list_repository_invitations()

    assert "--cache" not in seen[0]


def test_an_invitations_response_that_is_not_paged_is_rejected(monkeypatch):
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: FakeCompleted(stdout="{}"))

    with pytest.raises(AdapterError, match="unexpected response"):
        github_cli.list_repository_invitations()


def test_accepting_an_invitation_sends_a_patch(monkeypatch):
    seen = []
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda args, **k: (seen.append(args), FakeCompleted(stdout=""))[1],
    )

    github_cli.accept_repository_invitation(42)

    (argv,) = seen
    assert argv[argv.index("-X") + 1] == "PATCH"
    assert argv[-1] == "user/repository_invitations/42"


def test_declining_an_invitation_sends_a_delete(monkeypatch):
    seen = []
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda args, **k: (seen.append(args), FakeCompleted(stdout=""))[1],
    )

    github_cli.decline_repository_invitation(42)

    (argv,) = seen
    assert argv[argv.index("-X") + 1] == "DELETE"
    assert argv[-1] == "user/repository_invitations/42"


def test_an_empty_body_is_not_parsed_as_json(monkeypatch):
    """Both answer 204 with no body; parsing it would fail for no reason."""
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: FakeCompleted(stdout=""))

    assert github_cli.accept_repository_invitation(1) is None
    assert github_cli.decline_repository_invitation(1) is None


def test_a_failed_acceptance_becomes_an_adapter_error(monkeypatch):
    """An invitation someone already accepted or revoked is gone."""
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *a, **k: FakeCompleted(stderr="HTTP 404: Not Found", returncode=1),
    )

    with pytest.raises(AdapterError, match="404"):
        github_cli.accept_repository_invitation(42)
