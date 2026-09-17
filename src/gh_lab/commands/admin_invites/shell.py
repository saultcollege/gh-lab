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
from collections.abc import Sequence
from typing import TextIO

from gh_lab.adapters import AdapterError
from gh_lab.commands.admin_invites.command import (
    ActionResult,
    Choice,
    Outcome,
    RepositoryInvitation,
    Review,
    SendReport,
    Stage,
    apply_review,
    begin_review,
    cancel,
    choose,
    confirm,
    edit,
    list_pending,
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

# What each keystroke means while reviewing. Anything else, a bare Return
# included, leaves the current choice alone.
REVIEW_ANSWERS = {
    "a": Choice.ACCEPT,
    "accept": Choice.ACCEPT,
    "d": Choice.DECLINE,
    "decline": Choice.DECLINE,
    "s": Choice.SKIP,
    "skip": Choice.SKIP,
}

CHOICE_LABELS = {
    Choice.ACCEPT: "accept ",
    Choice.DECLINE: "decline",
    Choice.SKIP: "skip   ",
}

CONFIRM_PROMPT = "\n[y]es, do it  [e]dit  [n]o, cancel: "

NOTHING_PENDING = "No invitations are waiting for you."


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
            "decline them together. Nothing is accepted or declined until the "
            "whole list has been reviewed and the choices confirmed."
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
    """Run ``admin invites accept`` and return its exit code."""
    try:
        invitations = list_pending()
    except AdapterError as error:
        print(f"{PROGRAM} accept: {error}", file=sys.stderr)
        return 2

    if not invitations:
        print(NOTHING_PENDING)
        return 0

    if not _interactive(sys.stdin):
        # Flushed before the diagnostic below, because stdout is block-buffered
        # when it is not a terminal while stderr is not buffered at all. Without
        # this, redirecting both to one place prints the explanation before the
        # listing it refers to.
        print(render_pending(invitations), flush=True)
        print(
            f"{PROGRAM} accept: reviewing invitations needs a terminal. "
            "Nothing was changed.",
            file=sys.stderr,
        )
        return 2

    review = review_interactively(begin_review(invitations), sys.stdin, sys.stdout)

    if review.stage is not Stage.CONFIRMED:
        print("Cancelled. Nothing was changed.")
        return 0

    results = apply_review(review)
    print(render_actions(results, review))

    return 0 if all(result.ok for result in results) else 1


def _interactive(stream: TextIO) -> bool:
    """Whether there is a terminal to ask questions of.

    A review cannot be conducted down a pipe, and blocking on a prompt that
    nobody can answer is worse than saying so.
    """
    return bool(getattr(stream, "isatty", lambda: False)())


def review_interactively(review: Review, stdin: TextIO, stdout: TextIO) -> Review:
    """Ask about each invitation, then about the whole set.

    The decisions belong to the command layer; this only turns keystrokes into
    them and prints what the state machine is asking about.
    """
    while review.stage in (Stage.REVIEWING, Stage.CONFIRMING):
        if review.stage is Stage.REVIEWING:
            review = _review_one(review, stdin, stdout)
        else:
            review = _ask_to_confirm(review, stdin, stdout)

    return review


def _review_one(review: Review, stdin: TextIO, stdout: TextIO) -> Review:
    invitation = review.current

    if invitation is None:
        return review

    print(
        _describe(invitation, review.position + 1, len(review.invitations)),
        file=stdout,
    )

    # Pressing Return keeps whatever is already chosen. On the first pass that
    # is always skip, so the safe answer is still the one needing no thought;
    # on an edit pass it means returning to one entry cannot quietly undo the
    # rest. An unrecognised answer does the same, and the confirmation screen
    # is where a mistyped one is caught.
    default = review.choices[review.position]

    answer = _ask(_review_prompt(default), stdin, stdout)

    if answer in ("q", "quit"):
        return cancel(review)

    return choose(review, REVIEW_ANSWERS.get(answer, default))


def _review_prompt(default: Choice) -> str:
    return f"[a]ccept  [d]ecline  [s]kip  [q]uit (default: {default.value}): "


def _ask_to_confirm(review: Review, stdin: TextIO, stdout: TextIO) -> Review:
    print(render_choices(review), file=stdout)

    answer = _ask(CONFIRM_PROMPT, stdin, stdout)

    if answer in ("y", "yes"):
        return confirm(review)

    if answer in ("e", "edit"):
        return edit(review)

    return cancel(review)


def _ask(prompt: str, stdin: TextIO, stdout: TextIO) -> str:
    """Read one answer, treating an interrupted read as a cancellation."""
    print(prompt, end="", file=stdout, flush=True)

    try:
        answer = stdin.readline()
    except KeyboardInterrupt:
        return "q"

    if not answer:
        return "q"

    return answer.strip().casefold()


def _describe(invitation: RepositoryInvitation, index: int, total: int) -> str:
    lines = [f"\n{index} of {total}  {invitation.display}"]

    if invitation.inviter:
        lines.append(f"{INDENT}invited by @{invitation.inviter}")

    return "\n".join(lines)


def render_pending(invitations: Sequence[RepositoryInvitation]) -> str:
    """List what is pending, for when there is no terminal to review it in."""
    lines = [f"{_count_invitations(len(invitations))} waiting for you:", ""]
    lines += [f"{INDENT}{invitation.display}" for invitation in invitations]

    return "\n".join(lines)


def render_choices(review: Review) -> str:
    """Show every choice before anything is acted on."""
    lines = ["", "You chose:"]

    for invitation, choice in review.decided:
        lines.append(f"{INDENT}{CHOICE_LABELS[choice]}  {invitation.name}")

    if not review.decided:
        lines.append(f"{INDENT}nothing")

    if review.skipped:
        lines.append("")
        lines.append(f"{INDENT}{len(review.skipped)} skipped, and left pending.")

    return "\n".join(lines)


def render_actions(
    results: Sequence[ActionResult],
    review: Review,
) -> str:
    """Report what was done, once it has been."""
    lines = [""]

    for result in results:
        line = f"{INDENT}{CHOICE_LABELS[result.choice]}  {result.invitation.name}"
        lines.append(f"{line} — {result.error}" if result.error else line)

    counts = [
        (sum(1 for r in results if r.ok and r.choice is Choice.ACCEPT), "accepted"),
        (sum(1 for r in results if r.ok and r.choice is Choice.DECLINE), "declined"),
        (sum(1 for r in results if not r.ok), "failed"),
        (len(review.skipped), "left pending"),
    ]

    stated = [f"{count} {label}" for count, label in counts if count]

    lines.append("")
    lines.append(", ".join(stated) if stated else "Nothing to do.")

    return "\n".join(lines)


def _count_invitations(total: int) -> str:
    return "1 invitation is" if total == 1 else f"{total} invitations are"
