"""Adapter for the git command-line interface."""

import subprocess
from pathlib import Path

from gh_lab.adapters import AdapterError

TIMEOUT_SECONDS = 15


def _run(*args: str) -> str:
    """Run a git command and return its stripped standard output."""
    try:
        completed = subprocess.run(
            ["git", *args],
            capture_output=True,
            text=True,
            timeout=TIMEOUT_SECONDS,
            check=False,
        )
    except FileNotFoundError as error:
        raise AdapterError("git is not installed or not on PATH") from error
    except subprocess.TimeoutExpired as error:
        raise AdapterError(f"git {args[0]} timed out") from error

    if completed.returncode != 0:
        detail = completed.stderr.strip() or f"exit status {completed.returncode}"
        raise AdapterError(f"git {args[0]} failed: {detail}")

    return completed.stdout.strip()


def repo_root() -> Path:
    """Return the root directory of the git repository containing the cwd.

    Raises:
        AdapterError: If the current directory is not inside a git repository.
    """
    return Path(_run("rev-parse", "--show-toplevel"))


def current_branch() -> str | None:
    """Return the name of the checked-out branch.

    Returns ``None`` when HEAD is detached, which is how GitHub Actions checks
    out a pull request. Callers should fall back to the workflow environment in
    that case.
    """
    return _run("branch", "--show-current") or None
