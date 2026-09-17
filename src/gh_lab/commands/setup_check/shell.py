"""Shell layer for the ``setup-check`` command.

Owns the CLI-specific concerns: argument registration, terminal output, and the
exit code. The wording of each check lives in the command layer; this module
decides only how it is laid out and coloured.

The audience is a student who is, by definition, looking at this because
something is already wrong, so failures are formatted to be actionable without
further help.
"""

import argparse
import dataclasses
import json
import os
import re
import sys
import textwrap
from collections.abc import Mapping
from typing import TextIO

from gh_lab.colour import (
    BOLD,
    CYAN,
    DIM,
    GREEN,
    RED,
    YELLOW,
    Painter,
    use_colour,
)
from gh_lab.commands.setup_check.command import (
    Advice,
    Check,
    SetupCheckReport,
    Status,
    run,
)
from gh_lab.course_config import ConfigError

LAB_PATTERN = re.compile(r"^[A-Za-z0-9._-]+$")

WRAP_WIDTH = 76
INDENT = "     "

# Symbols, with plain replacements for terminals that cannot encode them.
SYMBOLS = {Status.PASS: "✓", Status.FAIL: "✗", Status.SKIPPED: "–"}
ASCII_SYMBOLS = {Status.PASS: "[OK]", Status.FAIL: "[X]", Status.SKIPPED: "[-]"}

STATUS_COLOURS = {Status.PASS: GREEN, Status.FAIL: RED, Status.SKIPPED: YELLOW}


def register(subparsers: argparse._SubParsersAction) -> None:
    """Register the ``setup-check`` subcommand on ``subparsers``."""
    parser = subparsers.add_parser(
        "setup-check",
        help="Check that your lab repository is set up correctly.",
        description=(
            "Check that your lab repository is set up correctly, and explain how "
            "to fix anything that is not."
        ),
    )

    parser.add_argument(
        "lab",
        nargs="?",
        metavar="LAB",
        help=(
            "Which lab to check, for example 1. Only needed when one repository "
            "holds several labs; otherwise it is read from .lab/config.json."
        ),
    )
    parser.add_argument(
        "--format",
        choices=("text", "json"),
        default="text",
        help="Output format (default: text).",
    )
    parser.add_argument(
        "--color",
        choices=("auto", "always", "never"),
        default="auto",
        help="When to colourise output (default: auto).",
    )

    parser.set_defaults(handler=handle)


def symbols_for(stream: TextIO) -> dict[Status, str]:
    """Return check symbols the stream can actually encode."""
    encoding = getattr(stream, "encoding", None) or "ascii"

    try:
        "".join(SYMBOLS.values()).encode(encoding)
    except (LookupError, UnicodeEncodeError):
        return ASCII_SYMBOLS

    return SYMBOLS


def _wrap(text: str) -> list[str]:
    """Wrap prose to the indented body width."""
    return textwrap.wrap(text, width=WRAP_WIDTH - len(INDENT)) or [""]


def render_check(
    check: Check,
    paint: Painter,
    symbols: Mapping[Status, str],
    *,
    repeat_reason: bool = True,
) -> str:
    """Render one check as human-readable text.

    Args:
        repeat_reason: Whether to print a skipped check's reason. Set to False
            when an identical reason has already been shown, so that one outage
            does not print the same sentence under every check it affected.
    """
    colour = STATUS_COLOURS[check.status]
    symbol = paint(symbols[check.status], colour)

    if check.status is Status.PASS:
        title = paint(check.title, BOLD)
        suffix = paint(f"  {check.detail}", DIM) if check.detail else ""
        return f"  {symbol}  {title}{suffix}"

    if check.status is Status.SKIPPED:
        title = paint(check.title, BOLD)
        lines = [f"  {symbol}  {title}  {paint('not checked', DIM)}"]
        if check.detail and repeat_reason:
            lines += [INDENT + paint(line, DIM) for line in _wrap(check.detail)]
        return "\n".join(lines)

    lines = [f"  {symbol}  {paint(check.title, BOLD, colour)}"]

    for block in (check.detail, check.explanation):
        if block:
            lines.append("")
            lines += [INDENT + line for line in _wrap(block)]

    if check.commands:
        lines.append("")
        label = (
            "To fix this, run:"
            if len(check.commands) == 1
            else "To fix this, run these commands:"
        )
        lines.append(INDENT + label)
        lines.append("")
        # Never wrapped, so they stay copy-pasteable.
        lines += [INDENT + "    " + paint(command, CYAN) for command in check.commands]

    if check.note:
        lines.append("")
        lines += [INDENT + paint(line, DIM) for line in _wrap(check.note)]

    return "\n".join(lines)


@dataclasses.dataclass(frozen=True)
class AdviceText:
    """What to print about the checks that could not run.

    Attributes:
        body: The explanation, wrapped when rendered. ``{token}`` is replaced
            with whichever variable is supplying gh's token.
        lines: Verbatim lines to copy — commands, or a snippet of YAML. Never
            wrapped, and never formatted, so a ``${{ }}`` survives intact.
        note: A caveat worth reading before acting on ``lines``.
    """

    body: str
    lines: tuple[str, ...] = ()
    note: str = ""


# One entry per Advice except NONE, which prints nothing. Keeping the wording
# here and the choice in the command layer means either can change alone.
ADVICE: dict[Advice, AdviceText] = {
    Advice.INSTALL_GH: AdviceText(
        body=(
            "Look for 'not checked' above. Those checks ask GitHub through the "
            "GitHub CLI (gh), which is not installed or not on PATH here. "
            "Install it from https://cli.github.com, then run this again."
        ),
    ),
    Advice.SIGN_IN: AdviceText(
        body=(
            "Look for 'not checked' above. Nothing could be read from GitHub, "
            "and this environment provides no token, so the GitHub CLI is most "
            "likely not signed in. To sign in, run:"
        ),
        lines=("gh auth login",),
        note=(
            "If that says you are already signed in, the reason printed under "
            "each check above is the real problem — most often no network "
            "connection."
        ),
    ),
    Advice.ENV_TOKEN_REJECTED: AdviceText(
        body=(
            "Look for 'not checked' above. Nothing could be read from GitHub, "
            "even though this environment supplies a token in {token} and the "
            "GitHub CLI is already using it. Signing in again is not the fix: "
            "the GitHub CLI refuses to store new credentials while {token} is "
            "set. Check your network connection, and show your instructor "
            "what the checks above say if it keeps happening."
        ),
        lines=("gh auth status",),
        note=(
            "That prints which token the GitHub CLI is using and what it is "
            "allowed to do."
        ),
    ),
    Advice.COURSE_CONFIG_UNREADABLE: AdviceText(
        body=(
            "Look for 'not checked' above. You are signed in — the other "
            "checks reached GitHub — but your course's configuration could not "
            "be used, so signing in again would change nothing. The reason "
            "under that check says what went wrong."
        ),
        note=(
            "If you have been invited to the course organization and have not "
            "accepted yet, accept it at https://github.com/settings/organizations "
            "and run this check again."
        ),
    ),
    Advice.CODESPACE_TOKEN_SCOPE: AdviceText(
        body=(
            "Look for 'not checked' above. You are signed in — the other "
            "checks reached GitHub — but a Codespace is given a token that can "
            "only see the repository it belongs to, so it cannot read your "
            "course's configuration in another organization. Everything else "
            "was checked, and this is nothing you have done wrong: tell your "
            "instructor, because a course whose faculty list is public does "
            "not have this problem. To run that last check now, sign in as "
            "yourself — clearing {token} first, because the GitHub CLI will "
            "not store new credentials while it is set:"
        ),
        lines=("unset GH_TOKEN GITHUB_TOKEN", "gh auth login"),
        note=(
            "Those two lines sign the GitHub CLI in as you for this terminal "
            "only; a new terminal will use the Codespace token again. Running "
            "this check from a clone on your own machine works too."
        ),
    ),
    Advice.ACTIONS_TOKEN: AdviceText(
        # Inside a workflow there is nobody to sign in; the token is passed
        # through the environment instead.
        body=(
            "Look for 'not checked' above. Checks that ask GitHub need a "
            "token, which a workflow provides like this:"
        ),
        lines=("env:", "  GH_TOKEN: ${{ github.token }}"),
    ),
    Advice.SEE_REASONS: AdviceText(
        body=(
            "Look for 'not checked' above — each one says why it could not "
            "run. None of them needs you to sign in again."
        ),
    ),
}


def render_advice(
    advice: AdviceText,
    token_variable: str | None,
    paint: Painter,
) -> list[str]:
    """Render the closing advice as report sections."""
    # Only a token-specific message interpolates, and one is only ever chosen
    # when a variable was found; name the usual one if that ever changes.
    token = token_variable or "GITHUB_TOKEN"

    sections = textwrap.wrap(advice.body.format(token=token), width=WRAP_WIDTH)

    if advice.lines:
        sections.append("")
        # Never wrapped, so they stay copy-pasteable.
        sections += ["    " + paint(line, CYAN) for line in advice.lines]

    if advice.note:
        sections.append("")
        sections += [
            paint(line, DIM)
            for line in textwrap.wrap(advice.note.format(token=token), width=WRAP_WIDTH)
        ]

    return sections


def render_report(
    report: SetupCheckReport,
    paint: Painter,
    symbols: Mapping[Status, str],
) -> str:
    """Render the whole report as human-readable text."""
    heading = "Checking your lab setup"
    if report.lab:
        heading = f"Checking your setup for lab {report.lab}"

    sections = [paint(f"{heading}...", BOLD), ""]

    seen_reasons: set[str] = set()
    for check in report.checks:
        first_time = check.detail not in seen_reasons
        if check.status is Status.SKIPPED:
            seen_reasons.add(check.detail)

        sections.append(render_check(check, paint, symbols, repeat_reason=first_time))
        if check.status is Status.FAIL:
            sections.append("")

    sections.append("")

    failures = len(report.failures)
    skipped = len(report.skipped)

    if failures:
        noun = "problem" if failures == 1 else "problems"
        sections.append(
            paint(f"{failures} {noun} found.", RED, BOLD)
            + " Follow the steps above, then run this command again."
        )
    elif skipped:
        # Saying "everything looks good" would be misleading when most of the
        # checks never ran.
        ran = len(report.checks) - skipped
        sections.append(
            paint(f"{ran} of {len(report.checks)} checks passed, ", BOLD)
            + paint(f"but {skipped} could not be run.", YELLOW, BOLD)
        )
    else:
        sections.append(paint("Everything looks good.", GREEN, BOLD))

    advice = ADVICE.get(report.advice)
    if advice:
        sections.append("")
        sections += render_advice(advice, report.token_variable, paint)

    if report.faculty_skipped_in_actions:
        sections.append(
            paint(
                "The faculty-access check is not run inside GitHub Actions.",
                DIM,
            )
        )

    return "\n".join(sections)


def report_to_json(report: SetupCheckReport) -> str:
    """Serialise the report for machine consumption."""
    return json.dumps(
        {
            "lab": report.lab,
            "ok": report.ok,
            # The key, not the rendered sentence: exporting the prose would
            # freeze the wording into a machine contract.
            "advice": str(report.advice),
            "facultySkippedInActions": report.faculty_skipped_in_actions,
            "checks": [
                {**dataclasses.asdict(check), "status": str(check.status)}
                for check in report.checks
            ],
        },
        indent=2,
    )


def emit_annotations(report: SetupCheckReport, stream: TextIO) -> None:
    """Emit GitHub Actions annotations so failures show up on the pull request."""
    for check in report.failures:
        message = " ".join(part for part in (check.detail, check.explanation) if part)
        if check.commands:
            message += " To fix this, run: " + " && ".join(check.commands)
        # Annotations must be a single line.
        print(f"::error title={check.title}::{message}", file=stream)


def handle(args: argparse.Namespace) -> int:
    """Run the command for parsed ``args`` and return an exit code."""
    lab = args.lab

    if lab is not None and not LAB_PATTERN.match(lab):
        print(
            f"gh lab setup-check: {lab!r} is not a valid lab name. Use letters, "
            "numbers, dots, dashes, or underscores, for example: 1",
            file=sys.stderr,
        )
        return 2

    try:
        report = run(lab)
    except ConfigError as error:
        print(f"gh lab setup-check: {error}", file=sys.stderr)
        return 2

    if args.format == "json":
        print(report_to_json(report))
        return 0 if report.ok else 1

    paint = Painter(use_colour(args.color, sys.stdout, os.environ))
    print(render_report(report, paint, symbols_for(sys.stdout)))

    if os.environ.get("GITHUB_ACTIONS") == "true":
        emit_annotations(report, sys.stdout)

    return 0 if report.ok else 1
