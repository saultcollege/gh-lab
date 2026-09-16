"""Shell layer for the ``admin invites`` commands.

Owns the CLI-specific concerns: argument registration, terminal output, and the
exit code. What happened to each person is decided in the command layer; this
module decides only how it is labelled and laid out.

The audience is faculty running a course, not a student fixing their own
repository, so these commands act across many repositories and select their
subject with options rather than a positional argument.
"""

import argparse
import sys

from gh_lab.adapters import AdapterError
from gh_lab.commands.admin_invites.command import (
    Outcome,
    SendReport,
    run_send,
)
from gh_lab.course_config import ConfigError

PROGRAM = "gh lab admin invites"

# Labels for each outcome, padded so that the names line up beneath each other.
LABELS = {
    Outcome.INVITED: "invited       ",
    Outcome.ALREADY_MEMBER: "already member",
    Outcome.FAILED: "failed        ",
}

INDENT = "  "


def register(subparsers: argparse._SubParsersAction) -> None:
    """Register the ``invites`` group on the ``admin`` subparsers."""
    parser = subparsers.add_parser(
        "invites",
        help="Send and accept course invitations.",
        description=(
            "Manage the GitHub invitations a course depends on: invitations into "
            "the course organization, and invitations to student repositories."
        ),
    )

    verbs = parser.add_subparsers(
        dest="verb",
        metavar="<verb>",
        required=True,
    )

    _register_send(verbs)
    _register_accept(verbs)


def _register_send(verbs: argparse._SubParsersAction) -> None:
    parser = verbs.add_parser(
        "send",
        help="Invite a course's students and faculty to the course organization.",
        description=(
            "Invite everyone listed in a course configuration to the "
            "organization that owns it. Re-running is safe: someone who is "
            "already a member is reported as such rather than invited again."
        ),
    )

    parser.add_argument(
        "--config-file",
        required=True,
        metavar="REF",
        help=(
            "The course configuration to read, as owner/repo/path, "
            "owner/repo/path@ref, or a link to the file on GitHub. The "
            "organization invited to is the owner of that repository."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show who would be invited, and to where, without inviting anyone.",
    )

    parser.set_defaults(handler=handle_send)


def _register_accept(verbs: argparse._SubParsersAction) -> None:
    parser = verbs.add_parser(
        "accept",
        help="Review and accept pending repository invitations.",
        description=(
            "Review the repository invitations sent to you, then accept or "
            "decline them together."
        ),
    )

    parser.set_defaults(handler=handle_accept)


def render_roster(report: SendReport) -> str:
    """Describe who a dry run would have invited."""
    lines = [
        f"Would invite {_count(len(report.roster))} to {report.org}",
        f"from {report.source}",
    ]

    if report.roster:
        lines.append("")
        lines += [f"{INDENT}{person.display}" for person in report.roster]

    lines.append("")
    lines.append("Nothing was sent. Re-run without --dry-run to invite them.")

    return "\n".join(lines)


def render_results(report: SendReport) -> str:
    """Describe what happened to each person, and summarise it."""
    lines = [
        f"Inviting {_count(len(report.roster))} to {report.org}",
        f"from {report.source}",
    ]

    if report.results:
        lines.append("")

    for result in report.results:
        line = f"{INDENT}{LABELS[result.outcome]}  {result.person.display}"
        lines.append(f"{line} — {result.detail}" if result.detail else line)

    lines.append("")
    lines.append(_summary(report))

    return "\n".join(lines)


def _summary(report: SendReport) -> str:
    """One line counting each outcome, naming only the ones that occurred."""
    counts = [
        (len(report.invited), "invited"),
        (len(report.already_members), "already a member"),
        (len(report.failures), "failed"),
    ]

    stated = [f"{count} {label}" for count, label in counts if count]

    return ", ".join(stated) if stated else "Nobody to invite."


def _count(total: int) -> str:
    """``1 person`` or ``3 people``."""
    return "1 person" if total == 1 else f"{total} people"


def handle_send(args: argparse.Namespace) -> int:
    """Run ``admin invites send`` and return its exit code."""
    try:
        report = run_send(config_file=args.config_file, dry_run=args.dry_run)
    except (ConfigError, AdapterError) as error:
        print(f"{PROGRAM} send: {error}", file=sys.stderr)
        return 2

    if report.dry_run:
        print(render_roster(report))
        return 0

    print(render_results(report))

    return 0 if report.ok else 1


def handle_accept(args: argparse.Namespace) -> int:
    """Run ``admin invites accept`` and return its exit code.

    Registered ahead of its implementation so that the grammar is settled; the
    review flow arrives with the change that implements it.
    """
    print(f"{PROGRAM} accept: not implemented yet", file=sys.stderr)

    return 2
