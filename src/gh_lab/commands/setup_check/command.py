"""Core logic for the ``setup-check`` command.

This layer is pure: it takes ordinary Python values and returns structured data,
with no argparse, terminal output, or exit codes.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class SetupCheckResult:
    """Outcome of a setup check.

    Attributes:
        ok: Whether the repository is configured correctly.
        messages: Human-readable findings to report to the user.
    """

    ok: bool
    messages: tuple[str, ...] = ()


def run(org: str, lab_name: str) -> SetupCheckResult:
    """Check whether a lab repository is configured correctly.

    Not implemented yet. Returns a placeholder result so that the CLI reports a
    clear message instead of failing with a traceback.

    Args:
        org: GitHub organization owning the lab repository.
        lab_name: Name of the lab to check.
    """
    return SetupCheckResult(
        ok=False,
        messages=(
            f"setup-check is not implemented yet (org={org!r}, lab-name={lab_name!r}).",
        ),
    )
