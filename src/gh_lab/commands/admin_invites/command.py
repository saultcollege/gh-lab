"""Core logic for the ``admin invites`` commands.

The decisions are pure: :func:`build_roster` turns a course configuration into
the list of people to invite, and :func:`result_for` turns the membership state
GitHub reported into what actually happened to one of them. Reaching GitHub is
kept separate and deliberately thin.
"""

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from enum import StrEnum

from gh_lab.adapters import AdapterError, github_cli
from gh_lab.course_config import (
    ConfigError,
    CourseConfig,
    CourseConfigRef,
    Person,
    parse_course_config,
    parse_course_config_ref,
)

# Named in error messages, so that what the user has to fix is the thing they
# typed rather than a file they have never seen.
CONFIG_FILE_OPTION = "--config-file"

# Everyone on a course joins as an ordinary member. Ownership of the course
# organization is not something this command should hand out.
MEMBER_ROLE = "member"


class Outcome(StrEnum):
    """What happened to one person's invitation."""

    INVITED = "invited"
    ALREADY_MEMBER = "already-member"
    FAILED = "failed"


@dataclass(frozen=True)
class InviteResult:
    """The outcome of inviting one person.

    Attributes:
        person: Who was invited.
        outcome: What happened.
        detail: Why, when something went wrong. Empty otherwise.
    """

    person: Person
    outcome: Outcome
    detail: str = ""


@dataclass(frozen=True)
class SendReport:
    """The outcome of one ``admin invites send``.

    ``roster`` is who the command set out to invite and is populated even for a
    dry run; ``results`` is what became of each of them and is empty for one.

    Attributes:
        org: The organization people were invited to.
        source: The course configuration they came from.
        roster: Everyone the command intended to invite, in order.
        results: What happened to each of them.
        dry_run: Whether the invitations were only described, not sent.
        skipped_self: The roster entry for whoever ran the command, when they
            were on it. They are never invited; see :func:`set_self_aside`.
    """

    org: str
    source: str
    roster: tuple[Person, ...] = ()
    results: tuple[InviteResult, ...] = ()
    dry_run: bool = False
    skipped_self: Person | None = None

    @property
    def invited(self) -> tuple[InviteResult, ...]:
        return self._with(Outcome.INVITED)

    @property
    def already_members(self) -> tuple[InviteResult, ...]:
        return self._with(Outcome.ALREADY_MEMBER)

    @property
    def failures(self) -> tuple[InviteResult, ...]:
        return self._with(Outcome.FAILED)

    @property
    def ok(self) -> bool:
        """Whether every invitation the command attempted succeeded."""
        return not self.failures

    def _with(self, outcome: Outcome) -> tuple[InviteResult, ...]:
        return tuple(result for result in self.results if result.outcome is outcome)


def build_roster(config: CourseConfig) -> tuple[Person, ...]:
    """Everyone named in a course configuration, faculty first.

    Nobody is invited twice. A handle repeated within an array, or appearing in
    both arrays because a teaching assistant is also enrolled, is one person and
    one invitation; GitHub handles are compared without regard to case, as they
    are elsewhere in this project.

    Pure: takes already-parsed configuration and returns plain data.
    """
    roster: list[Person] = []
    seen: set[str] = set()

    for person in (*config.faculty, *config.students):
        handle = person.github.casefold()

        if handle in seen:
            continue

        seen.add(handle)
        roster.append(person)

    return tuple(roster)


def set_self_aside(
    roster: Sequence[Person],
    handle: str,
) -> tuple[tuple[Person, ...], Person | None]:
    """Separate whoever is running the command from the rest of the roster.

    Faculty list themselves in their own course configuration, so the person
    running this is usually on it. Inviting yourself is never what was meant:
    only an owner of the organization can invite anyone, so the caller is
    already a member, and the request asks GitHub to set their membership to
    ``member`` — at best doing nothing, at worst taking away the ownership that
    let them run the command at all.

    Handles are compared without regard to case, as they are elsewhere.

    Returns:
        The rest of the roster, and the entry set aside if there was one.

    Pure: takes plain data and returns plain data.
    """
    wanted = handle.casefold()
    kept: list[Person] = []
    found: Person | None = None

    for person in roster:
        if found is None and person.github.casefold() == wanted:
            found = person
        else:
            kept.append(person)

    return tuple(kept), found


def result_for(person: Person, state: str) -> InviteResult:
    """Turn the membership state GitHub reported into a result.

    ``pending`` means an invitation is now outstanding, ``active`` that the
    person was already in the organization and nothing needed to be sent. Any
    other state is treated as a failure rather than guessed at, because the
    report tells faculty who still has to accept something.

    Pure: takes plain data and returns plain data.
    """
    if state == "pending":
        return InviteResult(person, Outcome.INVITED)

    if state == "active":
        return InviteResult(person, Outcome.ALREADY_MEMBER)

    return InviteResult(
        person,
        Outcome.FAILED,
        f"GitHub reported an unrecognised membership state: {state!r}",
    )


def load_course_config(reference: CourseConfigRef) -> CourseConfig:
    """Fetch and parse the course configuration the command was pointed at.

    Reads through the GitHub CLI, so it uses the authentication the environment
    already provides.

    Unlike ``setup-check``, which degrades a single check when the course
    configuration cannot be read, this command has nothing to do without it, so
    a failure is raised rather than reported.

    Raises:
        AdapterError: The file could not be fetched.
        ConfigError: The file was fetched but is not a usable configuration.
    """
    raw = github_cli.fetch_repo_file(
        reference.owner, reference.repo, reference.path, reference.ref
    )

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as error:
        raise ConfigError(f"{reference} is not valid JSON: {error}") from error

    return parse_course_config(data, source=str(reference))


def invite_everyone(org: str, roster: Sequence[Person]) -> tuple[InviteResult, ...]:
    """Invite each person in turn, recording what happened to each.

    One failure does not stop the others. A mistyped handle part-way down a
    roster should not decide whether the rest of the course gets invited, and
    the endpoint behind this states a membership rather than creating an
    invitation, so the command can simply be run again once the entry is fixed.
    """
    results = []

    for person in roster:
        try:
            state = github_cli.set_org_membership(org, person.github, MEMBER_ROLE)
        except AdapterError as error:
            results.append(InviteResult(person, Outcome.FAILED, str(error)))
        else:
            results.append(result_for(person, state))

    return tuple(results)


def run_send(*, config_file: str, dry_run: bool = False) -> SendReport:
    """Invite everyone in a course configuration to the organization owning it.

    The organization is not configured separately: it is, by definition, the
    owner of the repository the course configuration lives in.

    Whoever is running the command is never invited, even when the course
    configuration lists them.

    Raises:
        AdapterError: The course configuration could not be fetched, or gh could
            not say who is signed in. The second is fatal rather than ignored:
            without knowing who is running this, the command cannot tell that it
            is about to act on them.
        ConfigError: The reference was malformed, or the file it named was not a
            usable course configuration.
    """
    reference = parse_course_config_ref(config_file, CONFIG_FILE_OPTION)
    config = load_course_config(reference)
    roster, you = set_self_aside(build_roster(config), github_cli.current_user())

    return SendReport(
        org=reference.owner,
        source=str(reference),
        roster=roster,
        results=() if dry_run else invite_everyone(reference.owner, roster),
        dry_run=dry_run,
        skipped_self=you,
    )


@dataclass(frozen=True)
class RepositoryInvitation:
    """An invitation for the current user to collaborate on one repository.

    Attributes:
        id: GitHub's identifier, and all that acting on the invitation needs.
        repository: The full ``owner/name``, or ``None`` when GitHub no longer
            names one because the repository has been deleted.
        inviter: Who sent the invitation, when GitHub said.
        permission: The access the invitation grants.
        expired: Whether GitHub considers the invitation no longer valid.
    """

    id: int
    repository: str | None = None
    inviter: str | None = None
    permission: str | None = None
    expired: bool = False

    @property
    def name(self) -> str:
        """The repository, or a stand-in when GitHub no longer names one."""
        return self.repository or MISSING_REPOSITORY

    @property
    def acceptable(self) -> bool:
        """Whether accepting this invitation would achieve anything.

        Accepting an expired invitation is answered as a success and grants no
        access, while still consuming the invitation. Nothing in the response
        says so, so the only way not to be misled by it is not to send it.
        """
        return not self.expired

    @property
    def display(self) -> str:
        """A human-readable identification, e.g. ``org/lab-1 (write)``.

        The permission is left off an invitation whose repository is gone: it
        grants access to nothing, and reads as noise beside the stand-in.
        """
        notes = []

        if self.repository is not None and self.permission:
            notes.append(self.permission)

        if self.expired:
            notes.append("expired")

        return f"{self.name} ({', '.join(notes)})" if notes else self.name


def parse_invitation(entry: Mapping[str, object]) -> RepositoryInvitation | None:
    """Shape one entry of the invitations listing.

    Only the identifier is required, because it is all that accepting or
    declining needs. GitHub answers with a null repository for an invitation
    whose repository has since been deleted, and those are worth showing rather
    than hiding: they cannot be accepted, but they can be declined, which is the
    only way to clear one.

    Returns ``None`` only when there is no usable identifier, which leaves
    nothing that could be acted on.

    Pure: takes already-parsed JSON and returns plain data.
    """
    identifier = entry.get("id")

    if not isinstance(identifier, int):
        return None

    repository = entry.get("repository")
    repository = repository if isinstance(repository, dict) else {}

    full_name = repository.get("full_name")
    inviter = entry.get("inviter")
    permission = entry.get("permissions")

    return RepositoryInvitation(
        id=identifier,
        repository=full_name if isinstance(full_name, str) and full_name else None,
        inviter=inviter.get("login") if isinstance(inviter, dict) else None,
        permission=permission if isinstance(permission, str) else None,
        expired=entry.get("expired") is True,
    )


MISSING_REPOSITORY = "(repository no longer exists)"


def parse_invitations(
    entries: Sequence[Mapping[str, object]],
) -> tuple[RepositoryInvitation, ...]:
    """Shape the invitations listing, dropping any entry that cannot be acted on."""
    shaped = (parse_invitation(entry) for entry in entries)

    return tuple(invitation for invitation in shaped if invitation is not None)


class Choice(StrEnum):
    """What the user decided to do with one invitation."""

    ACCEPT = "accept"
    DECLINE = "decline"
    SKIP = "skip"


class Stage(StrEnum):
    """Where a review has got to.

    Nothing is accepted or declined before :attr:`CONFIRMED`, which is the whole
    point of having a stage at all: the user sees every invitation, and what
    they chose for each, before anything is acted on.
    """

    REVIEWING = "reviewing"
    CONFIRMING = "confirming"
    CONFIRMED = "confirmed"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class Review:
    """A review in progress.

    ``choices`` runs parallel to ``invitations``: every invitation has a choice
    from the outset, defaulting to :attr:`Choice.SKIP`, so that abandoning a
    review part-way through cannot leave an invitation in an undecided state.

    Attributes:
        invitations: What is being reviewed, in the order shown.
        choices: What was chosen for each, same length and order.
        position: The invitation under review, or one past the end once every
            invitation has been seen.
        stage: Where the review has got to.
    """

    invitations: tuple[RepositoryInvitation, ...]
    choices: tuple[Choice, ...]
    position: int = 0
    stage: Stage = Stage.REVIEWING

    @property
    def current(self) -> RepositoryInvitation | None:
        """The invitation under review, or ``None`` past the end of the list."""
        if self.position >= len(self.invitations):
            return None

        return self.invitations[self.position]

    @property
    def decided(self) -> tuple[tuple[RepositoryInvitation, Choice], ...]:
        """Every invitation whose choice asks for something to be done."""
        return tuple(
            (invitation, choice)
            for invitation, choice in zip(self.invitations, self.choices)
            if choice is not Choice.SKIP
        )

    @property
    def skipped(self) -> tuple[RepositoryInvitation, ...]:
        return tuple(
            invitation
            for invitation, choice in zip(self.invitations, self.choices)
            if choice is Choice.SKIP
        )


def begin_review(invitations: Sequence[RepositoryInvitation]) -> Review:
    """Start a review with every invitation skipped.

    Pure: takes plain data and returns plain data.
    """
    return Review(
        invitations=tuple(invitations),
        choices=tuple(Choice.SKIP for _ in invitations),
    )


def choose(review: Review, choice: Choice) -> Review:
    """Record ``choice`` for the invitation under review and move to the next.

    Once every invitation has been seen the review moves to
    :attr:`Stage.CONFIRMING`; it never acts on anything by itself.

    Pure: returns a new review rather than modifying one.
    """
    invitation = review.current

    if review.stage is not Stage.REVIEWING or invitation is None:
        return review

    # Refused here rather than only in the prompt, so that the rule holds for
    # any caller: accepting an expired invitation destroys it and grants
    # nothing, and the response gives no sign of either.
    if choice is Choice.ACCEPT and not invitation.acceptable:
        return review

    choices = list(review.choices)
    choices[review.position] = choice
    position = review.position + 1

    return replace(
        review,
        choices=tuple(choices),
        position=position,
        stage=(
            Stage.CONFIRMING if position >= len(review.invitations) else Stage.REVIEWING
        ),
    )


def edit(review: Review) -> Review:
    """Go back to the start of the list, keeping every choice already made."""
    return replace(review, position=0, stage=Stage.REVIEWING)


def confirm(review: Review) -> Review:
    """Agree to everything chosen. The only stage from which anything happens."""
    return replace(review, stage=Stage.CONFIRMED)


def cancel(review: Review) -> Review:
    """Abandon the review, whatever was chosen."""
    return replace(review, stage=Stage.CANCELLED)


@dataclass(frozen=True)
class ActionResult:
    """What became of one accepted or declined invitation."""

    invitation: RepositoryInvitation
    choice: Choice
    error: str = ""

    @property
    def ok(self) -> bool:
        return not self.error


def list_pending() -> tuple[RepositoryInvitation, ...]:
    """Every repository invitation pending for the current user.

    Raises:
        AdapterError: The invitations could not be listed.
    """
    return parse_invitations(github_cli.list_repository_invitations())


def apply_review(review: Review) -> tuple[ActionResult, ...]:
    """Carry out everything a confirmed review asked for.

    Does nothing at all unless the review was confirmed, so that a cancelled or
    half-finished review cannot accept anything by accident.

    One failure does not stop the rest: an invitation someone has already
    revoked should not decide whether the others are accepted.
    """
    if review.stage is not Stage.CONFIRMED:
        return ()

    results = []

    for invitation, choice in review.decided:
        act = (
            github_cli.accept_repository_invitation
            if choice is Choice.ACCEPT
            else github_cli.decline_repository_invitation
        )

        try:
            act(invitation.id)
        except AdapterError as error:
            results.append(ActionResult(invitation, choice, str(error)))
        else:
            results.append(ActionResult(invitation, choice))

    return tuple(results)
