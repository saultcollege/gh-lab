"""Shell layer for the ``admin invites`` commands.

Owns the CLI-specific concerns: argument registration, terminal output, and the
exit code.

The audience is faculty running a course, not a student fixing their own
repository, so these commands act across many repositories and select their
subject with options rather than a positional argument.
"""

import argparse
import sys

PROGRAM = "gh lab admin invites"


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

    send = verbs.add_parser(
        "send",
        help="Invite a course's students and faculty to the course organization.",
        description=(
            "Invite everyone listed in a course configuration to the "
            "organization that owns it."
        ),
    )
    send.set_defaults(handler=handle_send)

    accept = verbs.add_parser(
        "accept",
        help="Review and accept pending repository invitations.",
        description=(
            "Review the repository invitations sent to you, then accept or "
            "decline them together."
        ),
    )
    accept.set_defaults(handler=handle_accept)


def _not_implemented(verb: str) -> int:
    """Report a verb that is registered but has no implementation yet.

    The grammar is settled ahead of the operations themselves, so the commands
    are visible in help before they do anything. Saying so plainly is better
    than a command that appears to succeed.
    """
    print(f"{PROGRAM} {verb}: not implemented yet", file=sys.stderr)

    return 2


def handle_send(args: argparse.Namespace) -> int:
    """Run ``admin invites send`` and return its exit code."""
    return _not_implemented("send")


def handle_accept(args: argparse.Namespace) -> int:
    """Run ``admin invites accept`` and return its exit code."""
    return _not_implemented("accept")
