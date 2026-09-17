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
    """

    org: str
    source: str
    roster: tuple[Person, ...] = ()
    results: tuple[InviteResult, ...] = ()
    dry_run: bool = False

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

    Raises:
        AdapterError: The course configuration could not be fetched.
        ConfigError: The reference was malformed, or the file it named was not a
            usable course configuration.
    """
    reference = parse_course_config_ref(config_file, CONFIG_FILE_OPTION)
    config = load_course_config(reference)
    roster = build_roster(config)

    return SendReport(
        org=reference.owner,
        source=str(reference),
        roster=roster,
        results=() if dry_run else invite_everyone(reference.owner, roster),
        dry_run=dry_run,
    )


@dataclass(frozen=True)
class RepositoryInvitation:
    """An invitation for the current user to collaborate on one repository.

    Attributes:
        id: GitHub's identifier, needed to accept or decline it.
        repository: The full ``owner/name`` of the repository.
        owner: Who owns it — a student, for a lab repository.
        inviter: Who sent the invitation, when GitHub said.
        permission: The access the invitation grants.
    """

    id: int
    repository: str
    owner: str
    inviter: str | None = None
    permission: str | None = None

    @property
    def display(self) -> str:
        """A human-readable identification, e.g. ``org/lab-1 (write)``."""
        return (
            f"{self.repository} ({self.permission})"
            if self.permission
            else (self.repository)
        )


def parse_invitation(entry: Mapping[str, object]) -> RepositoryInvitation | None:
    """Shape one entry of the invitations listing.

    Returns ``None`` for an entry without the identifier and repository needed
    to act on it. GitHub's schema makes both non-nullable, so this should not
    happen; skipping the entry rather than raising follows what listing
    collaborators already does, and keeps one odd row from hiding a whole class
    of invitations that are perfectly usable.

    Pure: takes already-parsed JSON and returns plain data.
    """
    identifier = entry.get("id")
    repository = entry.get("repository")

    if not isinstance(identifier, int) or not isinstance(repository, dict):
        return None

    full_name = repository.get("full_name")
    owner = repository.get("owner")

    if not isinstance(full_name, str) or not full_name:
        return None

    login = owner.get("login") if isinstance(owner, dict) else None
    inviter = entry.get("inviter")
    permission = entry.get("permissions")

    return RepositoryInvitation(
        id=identifier,
        repository=full_name,
        owner=login if isinstance(login, str) else full_name.split("/")[0],
        inviter=inviter.get("login") if isinstance(inviter, dict) else None,
        permission=permission if isinstance(permission, str) else None,
    )


def parse_invitations(
    entries: Sequence[Mapping[str, object]],
) -> tuple[RepositoryInvitation, ...]:
    """Shape the invitations listing, dropping any entry that cannot be acted on."""
    shaped = (parse_invitation(entry) for entry in entries)

    return tuple(invitation for invitation in shaped if invitation is not None)


def invitations_from_org(
    invitations: Sequence[RepositoryInvitation],
    org: str | None,
) -> tuple[RepositoryInvitation, ...]:
    """Narrow a listing to one organization.

    Faculty generally have invitations that have nothing to do with the course
    in front of them. ``None`` means no narrowing at all. Owners are compared
    without regard to case, as GitHub handles are elsewhere in this project.

    Pure: takes plain data and returns plain data.
    """
    if org is None:
        return tuple(invitations)

    wanted = org.casefold()

    return tuple(
        invitation
        for invitation in invitations
        if invitation.owner.casefold() == wanted
    )


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
    if review.stage is not Stage.REVIEWING or review.current is None:
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


def list_pending(org: str | None = None) -> tuple[RepositoryInvitation, ...]:
    """The invitations pending for the current user, optionally one org's only.

    Raises:
        AdapterError: The invitations could not be listed.
    """
    entries = github_cli.list_repository_invitations()

    return invitations_from_org(parse_invitations(entries), org)


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
