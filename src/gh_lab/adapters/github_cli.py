"""Adapter for the GitHub CLI (``gh``)."""

import json
import subprocess
from collections.abc import Mapping, Sequence
from typing import Any

from gh_lab.adapters import AdapterError

TIMEOUT_SECONDS = 30

REPO_FIELDS = ("name", "owner", "isPrivate", "templateRepository")

# Course configuration changes rarely, and this is fetched on every invocation.
FILE_CACHE_DURATION = "1h"

REPOSITORY_INVITATIONS = "user/repository_invitations"


def _run_text(args: Sequence[str]) -> str:
    """Run a gh command and return its standard output."""
    try:
        completed = subprocess.run(
            ["gh", *args],
            capture_output=True,
            text=True,
            timeout=TIMEOUT_SECONDS,
            check=False,
        )
    except FileNotFoundError as error:
        raise AdapterError(
            "the GitHub CLI (gh) is not installed or not on PATH"
        ) from error
    except subprocess.TimeoutExpired as error:
        raise AdapterError("the GitHub CLI (gh) timed out") from error

    if completed.returncode != 0:
        # gh writes multi-line guidance; collapse it so it reads as one sentence
        # when quoted back to the user.
        detail = (
            " ".join(completed.stderr.split()) or f"exit status {completed.returncode}"
        )
        raise AdapterError(detail)

    return completed.stdout


def _run_json(args: Sequence[str]) -> Any:
    """Run a gh command expected to emit JSON and return the parsed result."""
    try:
        return json.loads(_run_text(args))
    except json.JSONDecodeError as error:
        raise AdapterError(
            "the GitHub CLI (gh) returned output that is not JSON"
        ) from error


def _api_args(
    endpoint: str,
    *,
    method: str | None = None,
    fields: Mapping[str, str] | None = None,
) -> list[str]:
    """Build the argument list for a ``gh api`` call.

    ``gh api`` switches to POST as soon as a field is given, so a request that
    is not a POST has to name its method even when it sends a body. Passing it
    explicitly rather than relying on that default keeps each call site honest
    about what it is doing.

    Fields are sent with ``-f``, which types them as strings. Nothing here needs
    a number, a boolean, or a nested object; ``--input`` would be the way to
    send one.
    """
    args = ["api"]

    if method:
        args += ["-X", method]

    for name, value in (fields or {}).items():
        args += ["-f", f"{name}={value}"]

    args.append(endpoint)

    return args


def repo_view() -> dict[str, Any]:
    """Return metadata about the repository in the current directory.

    A single call supplies the repository name, owner, visibility, and the
    template it was generated from.
    """
    result = _run_json(["repo", "view", "--json", ",".join(REPO_FIELDS)])

    if not isinstance(result, dict):
        raise AdapterError("unexpected response from gh repo view")

    return result


def list_collaborators(owner: str, repo: str) -> tuple[str, ...]:
    """Return the login names of the repository's collaborators.

    Requires write, maintain, or admin access to the repository. A student has
    that on their own repository; the token available inside GitHub Actions
    generally does not.
    """
    # A lab repository has a handful of collaborators at most, so a single page
    # is sufficient and avoids the subtleties of how gh merges paginated output.
    #
    # Deliberately not cached: a student who has just invited their instructor
    # must see the result of that on the next run.
    result = _run_json(["api", f"repos/{owner}/{repo}/collaborators?per_page=100"])

    if not isinstance(result, list):
        raise AdapterError("unexpected response when listing collaborators")

    return tuple(
        entry["login"]
        for entry in result
        if isinstance(entry, dict) and isinstance(entry.get("login"), str)
    )


def fetch_repo_file(owner: str, repo: str, path: str, ref: str | None = None) -> str:
    """Return the contents of a file in a repository.

    Reads through ``gh``, so it uses whatever authentication the environment
    already provides and works for private repositories the user can see.

    The raw media type returns the file itself rather than a JSON envelope with
    base64 content. The response is cached briefly because course configuration
    changes rarely and this runs on every invocation.
    """
    endpoint = f"repos/{owner}/{repo}/contents/{path}"
    if ref:
        endpoint = f"{endpoint}?ref={ref}"

    return _run_text(
        [
            "api",
            "-H",
            "Accept: application/vnd.github.raw+json",
            "--cache",
            FILE_CACHE_DURATION,
            endpoint,
        ]
    )


def set_org_membership(org: str, username: str, role: str = "member") -> str:
    """Invite a user to an organization, or update the role they hold in it.

    Returns the resulting membership state: ``pending`` while an invitation is
    outstanding, or ``active`` once the user has accepted one. A caller can use
    that to tell a new invitation from someone who was already a member.

    This is a PUT, so sending it twice is not an error the way creating an
    invitation twice would be; it states the membership that should hold rather
    than asking for a new invitation. Only an owner of the organization may call
    it.
    """
    result = _run_json(
        _api_args(
            f"orgs/{org}/memberships/{username}",
            method="PUT",
            fields={"role": role},
        )
    )

    if not isinstance(result, dict):
        raise AdapterError(f"unexpected response when inviting {username} to {org}")

    state = result.get("state")

    if not isinstance(state, str):
        raise AdapterError(f"gh did not report a membership state for {username}")

    return state


def list_repository_invitations() -> tuple[dict[str, Any], ...]:
    """Return the repository invitations pending for the authenticated user.

    Paginated, because an instructor is invited once per student repository and
    a class of any size exceeds the default page of 30. Pagination is the reason
    for ``--slurp``: ``--paginate`` alone emits one JSON array per page, which is
    several JSON documents concatenated rather than one, and cannot be parsed.
    ``--slurp`` wraps the pages in an outer array instead.

    Deliberately not cached: someone reviewing invitations has usually just
    asked a student to send one.
    """
    pages = _run_json(["api", "--paginate", "--slurp", REPOSITORY_INVITATIONS])

    if not isinstance(pages, list):
        raise AdapterError("unexpected response when listing repository invitations")

    invitations: list[dict[str, Any]] = []

    for page in pages:
        if not isinstance(page, list):
            raise AdapterError(
                "unexpected response when listing repository invitations"
            )

        invitations.extend(entry for entry in page if isinstance(entry, dict))

    return tuple(invitations)


def accept_repository_invitation(invitation_id: int) -> None:
    """Accept one repository invitation.

    Answers 204 with no body, so there is nothing to return and nothing to
    parse; a failure arrives as an :class:`AdapterError` like any other.
    """
    _run_text(_api_args(f"{REPOSITORY_INVITATIONS}/{invitation_id}", method="PATCH"))


def decline_repository_invitation(invitation_id: int) -> None:
    """Decline one repository invitation.

    Declining is not undoable through this API: the invitation is gone and the
    student would have to send another.
    """
    _run_text(_api_args(f"{REPOSITORY_INVITATIONS}/{invitation_id}", method="DELETE"))
