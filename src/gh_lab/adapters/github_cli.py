"""Adapter for the GitHub CLI (``gh``)."""

import json
import subprocess
from collections.abc import Sequence
from typing import Any

from gh_lab.adapters import AdapterError

TIMEOUT_SECONDS = 30

REPO_FIELDS = ("name", "owner", "isPrivate", "templateRepository")


def _run_json(args: Sequence[str]) -> Any:
    """Run a gh command expected to emit JSON and return the parsed result."""
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

    try:
        return json.loads(completed.stdout)
    except json.JSONDecodeError as error:
        raise AdapterError(
            "the GitHub CLI (gh) returned output that is not JSON"
        ) from error


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
    result = _run_json(["api", f"repos/{owner}/{repo}/collaborators?per_page=100"])

    if not isinstance(result, list):
        raise AdapterError("unexpected response when listing collaborators")

    return tuple(
        entry["login"]
        for entry in result
        if isinstance(entry, dict) and isinstance(entry.get("login"), str)
    )
