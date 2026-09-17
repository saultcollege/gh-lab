"""Tests for the ``admin invites`` commands.

The decisions are pure and are called directly with plain data. Only the two
functions that reach GitHub are stubbed, which is also how the suite proves that
a dry run reaches it at all.
"""

import argparse
import io
import sys

import pytest

from gh_lab.adapters import AdapterError, github_cli
from gh_lab.cli import build_parser as main_parser
from gh_lab.cli import main
from gh_lab.commands.admin_invites import command as command_module
from gh_lab.commands.admin_invites import shell
from gh_lab.commands.admin_invites.command import (
    Choice,
    InviteResult,
    Outcome,
    RepositoryInvitation,
    Review,
    SendReport,
    Stage,
    apply_review,
    begin_review,
    build_roster,
    cancel,
    choose,
    confirm,
    edit,
    invite_everyone,
    parse_invitation,
    parse_invitations,
    result_for,
    run_send,
)
from gh_lab.course_config import ConfigError, CourseConfig, Person

CONFIG_REF = "saultcollege-csd217/course-info/config/26f.json"

PROF = Person(github="prof", name="Pro Fessor")
STUDENT = Person(github="student", name="Stu Dent")
OTHER = Person(github="other")

COURSE_CONFIG = CourseConfig(faculty=(PROF,), students=(STUDENT, OTHER))


def send_parser() -> argparse.ArgumentParser:
    """The subparser registered for ``admin invites send``."""
    parser = main_parser()

    for name in ("admin", "invites", "send"):
        parser = _subparser(parser, name)

    return parser


def _subparser(parser: argparse.ArgumentParser, name: str) -> argparse.ArgumentParser:
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction) and name in action.choices:
            return action.choices[name]

    raise AssertionError(f"{name} is not registered")


def stub_github(monkeypatch, states=None, failing=()):
    """Answer every membership call from ``states``, failing for ``failing``."""
    states = states or {}
    seen = []

    def set_org_membership(org, username, role):
        seen.append((org, username, role))

        if username in failing:
            raise AdapterError(f"HTTP 404: Not Found (users/{username})")

        return states.get(username, "pending")

    monkeypatch.setattr(github_cli, "set_org_membership", set_org_membership)

    return seen


def stub_config(monkeypatch, config=COURSE_CONFIG):
    """Answer the course configuration fetch without touching the network."""
    monkeypatch.setattr(command_module, "load_course_config", lambda reference: config)


# --- CLI wiring ------------------------------------------------------------


def test_argument_surface_is_stable():
    """Pin the arguments, because CI invokes them directly.

    `.github/workflows/ci.yml` hard-codes these, and a stale invocation there is
    not caught by this suite: it fails only once the change has been pushed. If
    this test fails, update the workflow in the same change.
    """
    parser = send_parser()

    options = {option for action in parser._actions for option in action.option_strings}
    positionals = [
        action.dest for action in parser._actions if not action.option_strings
    ]

    assert options == {"-h", "--help", "--config-file", "--dry-run"}
    assert positionals == []


def test_config_file_is_required():
    """There is no default course: naming one is the whole input."""
    with pytest.raises(SystemExit) as exc_info:
        main(["admin", "invites", "send"])

    assert exc_info.value.code == 2


# --- Building the roster ---------------------------------------------------


def test_roster_is_faculty_then_students():
    assert build_roster(COURSE_CONFIG) == (PROF, STUDENT, OTHER)


def test_an_empty_course_has_an_empty_roster():
    assert build_roster(CourseConfig(faculty=())) == ()


def test_a_course_with_no_students_still_invites_faculty():
    assert build_roster(CourseConfig(faculty=(PROF,))) == (PROF,)


def test_nobody_is_invited_twice_within_one_array():
    config = CourseConfig(faculty=(PROF, PROF))

    assert build_roster(config) == (PROF,)


def test_a_teaching_assistant_in_both_arrays_is_invited_once():
    """Someone who teaches a course may also be enrolled in it."""
    config = CourseConfig(faculty=(PROF,), students=(STUDENT, Person(github="prof")))

    assert build_roster(config) == (PROF, STUDENT)


def test_duplicate_handles_are_matched_ignoring_case():
    config = CourseConfig(faculty=(PROF,), students=(Person(github="PROF"),))

    assert build_roster(config) == (PROF,)


def test_the_first_spelling_of_a_duplicate_is_kept():
    """Faculty come first, so their entry is the one carrying the name."""
    config = CourseConfig(faculty=(PROF,), students=(Person(github="prof"),))

    (person,) = build_roster(config)

    assert person.name == "Pro Fessor"


# --- Reading a membership state --------------------------------------------


def test_pending_means_an_invitation_was_sent():
    assert result_for(STUDENT, "pending").outcome is Outcome.INVITED


def test_active_means_they_were_already_a_member():
    assert result_for(STUDENT, "active").outcome is Outcome.ALREADY_MEMBER


def test_an_unrecognised_state_is_a_failure_naming_it():
    """The report says who still has to accept something; a guess would not."""
    result = result_for(STUDENT, "banished")

    assert result.outcome is Outcome.FAILED
    assert "banished" in result.detail


# --- Inviting --------------------------------------------------------------


def test_each_person_is_invited_as_a_member(monkeypatch):
    seen = stub_github(monkeypatch)

    invite_everyone("course-org", (PROF, STUDENT))

    assert seen == [
        ("course-org", "prof", "member"),
        ("course-org", "student", "member"),
    ]


def test_a_failure_does_not_stop_the_rest_of_the_roster(monkeypatch):
    """One mistyped handle must not decide whether the class gets invited."""
    stub_github(monkeypatch, failing={"prof"})

    results = invite_everyone("course-org", (PROF, STUDENT, OTHER))

    assert [result.outcome for result in results] == [
        Outcome.FAILED,
        Outcome.INVITED,
        Outcome.INVITED,
    ]


def test_a_failure_is_recorded_against_the_person_it_belongs_to(monkeypatch):
    stub_github(monkeypatch, failing={"student"})

    results = invite_everyone("course-org", (PROF, STUDENT))
    failure = next(r for r in results if r.outcome is Outcome.FAILED)

    assert failure.person is STUDENT
    assert "404" in failure.detail


# --- Running the command ---------------------------------------------------


def test_a_dry_run_sends_nothing(monkeypatch):
    """The point of --dry-run is that no student hears about it."""
    stub_config(monkeypatch)

    def fail(*args, **kwargs):
        raise AssertionError("a dry run must not reach GitHub")

    monkeypatch.setattr(github_cli, "set_org_membership", fail)

    report = run_send(config_file=CONFIG_REF, dry_run=True)

    assert report.dry_run
    assert report.results == ()


def test_a_dry_run_still_reports_who_would_be_invited(monkeypatch):
    stub_config(monkeypatch)
    monkeypatch.setattr(github_cli, "set_org_membership", lambda *a: "pending")

    report = run_send(config_file=CONFIG_REF, dry_run=True)

    assert report.roster == (PROF, STUDENT, OTHER)


@pytest.mark.parametrize(
    "reference",
    [
        "course-org/course-info/26f.json",
        "course-org/course-info/26f.json@main",
        "https://github.com/course-org/course-info/blob/main/26f.json",
    ],
)
def test_the_organization_is_the_owner_of_the_config_file(monkeypatch, reference):
    """The course org is, by definition, whoever owns the configuration."""
    stub_config(monkeypatch)
    stub_github(monkeypatch)

    assert run_send(config_file=reference).org == "course-org"


def test_the_report_names_the_configuration_it_read(monkeypatch):
    stub_config(monkeypatch)
    stub_github(monkeypatch)

    assert run_send(config_file=CONFIG_REF).source == CONFIG_REF


def test_an_empty_roster_invites_nobody(monkeypatch):
    stub_config(monkeypatch, CourseConfig(faculty=()))
    seen = stub_github(monkeypatch)

    report = run_send(config_file=CONFIG_REF)

    assert seen == []
    assert report.results == ()
    assert report.ok


def test_new_and_existing_members_are_reported_separately(monkeypatch):
    stub_config(monkeypatch)
    stub_github(monkeypatch, states={"prof": "active", "student": "pending"})

    report = run_send(config_file=CONFIG_REF)

    assert [r.person for r in report.already_members] == [PROF]
    assert [r.person for r in report.invited] == [STUDENT, OTHER]
    assert report.ok


def test_a_partial_failure_is_reported_without_losing_the_successes(monkeypatch):
    stub_config(monkeypatch)
    stub_github(monkeypatch, failing={"other"})

    report = run_send(config_file=CONFIG_REF)

    assert [r.person for r in report.invited] == [PROF, STUDENT]
    assert [r.person for r in report.failures] == [OTHER]
    assert not report.ok


def test_a_malformed_reference_is_rejected_before_anything_is_fetched(monkeypatch):
    def fail(*args, **kwargs):
        raise AssertionError("nothing should be fetched for an unusable reference")

    monkeypatch.setattr(command_module, "load_course_config", fail)

    with pytest.raises(ConfigError, match="--config-file"):
        run_send(config_file="not-a-reference")


# --- Exit codes ------------------------------------------------------------


def run_cli(monkeypatch, report=None, error=None, argv=None):
    """Invoke the CLI with run_send stubbed out."""

    def run_send_stub(**kwargs):
        if error is not None:
            raise error

        return report

    monkeypatch.setattr(shell, "run_send", run_send_stub)

    return main(argv or ["admin", "invites", "send", "--config-file", CONFIG_REF])


def test_a_clean_run_exits_zero(monkeypatch, capsys):
    report = SendReport(
        org="course-org",
        source=CONFIG_REF,
        roster=(PROF,),
        results=(InviteResult(PROF, Outcome.INVITED),),
    )

    assert run_cli(monkeypatch, report=report) == 0
    assert "course-org" in capsys.readouterr().out


def test_a_failed_invitation_exits_one(monkeypatch, capsys):
    report = SendReport(
        org="course-org",
        source=CONFIG_REF,
        roster=(PROF,),
        results=(InviteResult(PROF, Outcome.FAILED, "HTTP 404"),),
    )

    assert run_cli(monkeypatch, report=report) == 1
    assert "404" in capsys.readouterr().out


def test_a_dry_run_exits_zero_even_though_nothing_happened(monkeypatch, capsys):
    report = SendReport(
        org="course-org",
        source=CONFIG_REF,
        roster=(PROF,),
        dry_run=True,
    )

    assert run_cli(monkeypatch, report=report) == 0
    assert "Nothing was sent" in capsys.readouterr().out


def test_an_unreadable_configuration_exits_two(monkeypatch, capsys):
    """Unlike setup-check, this command has nothing to do without it."""
    error = AdapterError("HTTP 404: Not Found")

    assert run_cli(monkeypatch, error=error) == 2
    assert "404" in capsys.readouterr().err


def test_an_unusable_configuration_exits_two(monkeypatch, capsys):
    error = ConfigError("26f.json is missing a 'faculty' array")

    assert run_cli(monkeypatch, error=error) == 2
    assert "faculty" in capsys.readouterr().err


# --- Rendering -------------------------------------------------------------


def test_the_summary_counts_each_outcome():
    report = SendReport(
        org="course-org",
        source=CONFIG_REF,
        roster=(PROF, STUDENT, OTHER),
        results=(
            InviteResult(PROF, Outcome.INVITED),
            InviteResult(STUDENT, Outcome.ALREADY_MEMBER),
            InviteResult(OTHER, Outcome.FAILED, "HTTP 404"),
        ),
    )

    assert "1 invited, 1 already a member, 1 failed" in shell.render_results(report)


def test_the_summary_omits_outcomes_that_did_not_occur():
    report = SendReport(
        org="course-org",
        source=CONFIG_REF,
        roster=(PROF,),
        results=(InviteResult(PROF, Outcome.INVITED),),
    )

    summary = shell.render_results(report)

    assert "1 invited" in summary
    assert "already a member" not in summary
    assert "failed" not in summary


def test_an_empty_roster_says_so():
    report = SendReport(org="course-org", source=CONFIG_REF)

    assert "Nobody to invite." in shell.render_results(report)


def test_a_dry_run_lists_the_roster_and_says_nothing_was_sent():
    report = SendReport(
        org="course-org",
        source=CONFIG_REF,
        roster=(PROF, STUDENT),
        dry_run=True,
    )

    output = shell.render_roster(report)

    assert "Pro Fessor (@prof)" in output
    assert "Stu Dent (@student)" in output
    assert "Nothing was sent" in output


# --- Shaping the invitations listing ---------------------------------------


def invitation_entry(identifier=1, full_name="student/csd217-lab-1", **overrides):
    """One entry as GitHub returns it, trimmed to the fields that are read."""
    entry = {
        "id": identifier,
        "repository": {
            "name": full_name.split("/")[1],
            "full_name": full_name,
            "owner": {"login": full_name.split("/")[0]},
        },
        "inviter": {"login": "student"},
        "permissions": "write",
    }
    entry.update(overrides)

    return entry


def test_an_invitation_is_shaped_from_its_entry():
    invitation = parse_invitation(invitation_entry())

    assert invitation == RepositoryInvitation(
        id=1,
        repository="student/csd217-lab-1",
        inviter="student",
        permission="write",
    )


def test_an_invitation_without_an_inviter_is_still_usable():
    """GitHub types inviter as nullable, and the id is what acting on it needs."""
    invitation = parse_invitation(invitation_entry(inviter=None))

    assert invitation is not None
    assert invitation.inviter is None


@pytest.mark.parametrize(
    "entry",
    [
        {"repository": {"full_name": "student/lab"}},
        {"id": 1},
        {"id": "not-a-number", "repository": {"full_name": "student/lab"}},
        {"id": 1, "repository": {"full_name": ""}},
        {"id": 1, "repository": "not-an-object"},
    ],
)
def test_an_entry_that_cannot_be_acted_on_is_dropped(entry):
    """Without an id and a repository there is nothing to accept or show."""
    assert parse_invitation(entry) is None


def test_unusable_entries_do_not_hide_the_usable_ones():
    entries = [invitation_entry(1), {"id": 2}, invitation_entry(3, "student/lab-2")]

    assert [i.id for i in parse_invitations(entries)] == [1, 3]


def test_an_empty_listing_shapes_to_nothing():
    assert parse_invitations([]) == ()


def test_the_display_names_the_repository_and_permission():
    assert parse_invitation(invitation_entry()).display == (
        "student/csd217-lab-1 (write)"
    )


# --- Reviewing invitations -------------------------------------------------


LAB_1 = RepositoryInvitation(1, "alice/lab-1", "alice", "write")
LAB_2 = RepositoryInvitation(2, "bob/lab-1", "bob", "write")
SPAM = RepositoryInvitation(3, "spammer/crypto", "spammer", "admin")

PENDING = (LAB_1, LAB_2, SPAM)


class FakeTerminal(io.StringIO):
    """Stdin that claims to be a terminal, so the prompt loop will run."""

    def isatty(self):
        return True


def accept_parser() -> argparse.ArgumentParser:
    """The subparser registered for ``admin invites accept``."""
    parser = main_parser()

    for name in ("admin", "invites", "accept"):
        parser = _subparser(parser, name)

    return parser


def review_with(keys, invitations=PENDING):
    """Run the prompt loop against scripted keystrokes."""
    return shell.review_interactively(
        begin_review(invitations), FakeTerminal(keys), io.StringIO()
    )


def stub_actions(monkeypatch, failing=()):
    """Record every acceptance and declining, failing for ``failing`` ids."""
    done = []

    def accept(invitation_id):
        if invitation_id in failing:
            raise AdapterError("HTTP 404: Not Found")
        done.append(("accept", invitation_id))

    def decline(invitation_id):
        if invitation_id in failing:
            raise AdapterError("HTTP 404: Not Found")
        done.append(("decline", invitation_id))

    monkeypatch.setattr(github_cli, "accept_repository_invitation", accept)
    monkeypatch.setattr(github_cli, "decline_repository_invitation", decline)

    return done


def test_accept_argument_surface_is_stable():
    """Pin the arguments, because CI invokes them directly.

    `.github/workflows/ci.yml` hard-codes these, and a stale invocation there is
    not caught by this suite: it fails only once the change has been pushed. If
    this test fails, update the workflow in the same change.
    """
    parser = accept_parser()

    options = {option for action in parser._actions for option in action.option_strings}
    positionals = [
        action.dest for action in parser._actions if not action.option_strings
    ]

    assert options == {"-h", "--help"}
    assert positionals == []


def test_a_review_starts_with_everything_skipped():
    """An abandoned review must not leave an invitation undecided."""
    review = begin_review(PENDING)

    assert review.choices == (Choice.SKIP, Choice.SKIP, Choice.SKIP)
    assert review.stage is Stage.REVIEWING
    assert review.current is LAB_1


def test_choosing_records_and_moves_on():
    review = choose(begin_review(PENDING), Choice.ACCEPT)

    assert review.choices[0] is Choice.ACCEPT
    assert review.current is LAB_2


def test_the_last_invitation_leads_to_confirming():
    review = begin_review(PENDING)

    for _ in PENDING:
        review = choose(review, Choice.ACCEPT)

    assert review.stage is Stage.CONFIRMING
    assert review.current is None


def test_choosing_does_nothing_once_the_list_is_reviewed():
    review = confirm(begin_review((LAB_1,)))

    assert choose(review, Choice.DECLINE) == review


def test_editing_returns_to_the_start_keeping_the_choices():
    review = choose(begin_review(PENDING), Choice.ACCEPT)
    review = choose(review, Choice.DECLINE)
    review = choose(review, Choice.SKIP)

    edited = edit(review)

    assert edited.position == 0
    assert edited.stage is Stage.REVIEWING
    assert edited.choices == review.choices


def test_only_decided_invitations_are_acted_on():
    review = choose(begin_review(PENDING), Choice.ACCEPT)
    review = choose(review, Choice.SKIP)
    review = choose(review, Choice.DECLINE)

    assert review.decided == ((LAB_1, Choice.ACCEPT), (SPAM, Choice.DECLINE))
    assert review.skipped == (LAB_2,)


# --- Nothing happens before confirmation -----------------------------------


@pytest.mark.parametrize("stage", [Stage.REVIEWING, Stage.CONFIRMING, Stage.CANCELLED])
def test_an_unconfirmed_review_does_nothing_at_all(monkeypatch, stage):
    """The whole point of the confirmation step."""
    done = stub_actions(monkeypatch)
    review = Review(PENDING, (Choice.ACCEPT,) * 3, position=3, stage=stage)

    assert apply_review(review) == ()
    assert done == []


def test_a_confirmed_review_accepts_and_declines(monkeypatch):
    done = stub_actions(monkeypatch)
    review = Review(
        PENDING,
        (Choice.ACCEPT, Choice.SKIP, Choice.DECLINE),
        position=3,
        stage=Stage.CONFIRMED,
    )

    results = apply_review(review)

    assert done == [("accept", 1), ("decline", 3)]
    assert all(result.ok for result in results)


def test_a_failure_does_not_stop_the_other_invitations(monkeypatch):
    """An invitation the student already revoked must not block the rest."""
    done = stub_actions(monkeypatch, failing={1})
    review = Review(
        PENDING,
        (Choice.ACCEPT, Choice.ACCEPT, Choice.ACCEPT),
        position=3,
        stage=Stage.CONFIRMED,
    )

    results = apply_review(review)

    assert done == [("accept", 2), ("accept", 3)]
    assert [result.ok for result in results] == [False, True, True]
    assert results[0].invitation is LAB_1
    assert "404" in results[0].error


# --- The prompt loop -------------------------------------------------------


@pytest.mark.parametrize(
    ("keys", "expected"),
    [
        ("a\n", Choice.ACCEPT),
        ("accept\n", Choice.ACCEPT),
        ("d\n", Choice.DECLINE),
        ("decline\n", Choice.DECLINE),
        ("s\n", Choice.SKIP),
        ("A\n", Choice.ACCEPT),
    ],
)
def test_each_answer_records_a_choice(keys, expected):
    review = review_with(keys + "n\n", invitations=(LAB_1,))

    assert review.choices[0] is expected


def test_return_keeps_the_existing_choice():
    """Editing one entry must not quietly undo the others."""
    review = review_with("a\na\nd\ne\n\n\n\ny\n")

    assert review.choices == (Choice.ACCEPT, Choice.ACCEPT, Choice.DECLINE)
    assert review.stage is Stage.CONFIRMED


def test_an_unrecognised_answer_keeps_the_default():
    """The confirmation screen is where a mistyped answer is caught."""
    review = review_with("zzz\n" + "n\n", invitations=(LAB_1,))

    assert review.choices[0] is Choice.SKIP


def test_quitting_mid_review_cancels():
    review = review_with("a\nq\n")

    assert review.stage is Stage.CANCELLED


def test_a_closed_input_cancels():
    """A closed pipe must cancel rather than raise."""
    review = review_with("a\n")

    assert review.stage is Stage.CANCELLED


def test_declining_to_confirm_cancels():
    review = review_with("a\na\na\nn\n")

    assert review.stage is Stage.CANCELLED
    assert review.choices == (Choice.ACCEPT,) * 3


def test_editing_then_confirming_reaches_confirmed():
    review = review_with("a\ns\ns\ne\nd\ns\ns\ny\n")

    assert review.stage is Stage.CONFIRMED
    assert review.choices[0] is Choice.DECLINE


def test_the_review_shows_every_invitation_before_confirming():
    output = io.StringIO()
    shell.review_interactively(
        begin_review(PENDING), FakeTerminal("a\na\na\nn\n"), output
    )

    shown = output.getvalue()

    for invitation in PENDING:
        assert invitation.repository in shown


# --- Exit codes ------------------------------------------------------------


def run_accept_cli(monkeypatch, invitations=PENDING, review=None, error=None, tty=True):
    """Invoke ``handle_accept`` with the listing and the review stubbed."""
    if error is not None:
        monkeypatch.setattr(shell, "list_pending", _raiser(error))
    else:
        monkeypatch.setattr(shell, "list_pending", lambda: invitations)

    stdin = FakeTerminal("") if tty else io.StringIO("")
    monkeypatch.setattr(sys, "stdin", stdin)

    if review is not None:
        monkeypatch.setattr(shell, "review_interactively", lambda *a: review)

    return shell.handle_accept(argparse.Namespace())


def _raiser(error):
    def raise_it(*args, **kwargs):
        raise error

    return raise_it


def test_nothing_pending_exits_zero(monkeypatch, capsys):
    assert run_accept_cli(monkeypatch, invitations=()) == 0
    assert "No invitations" in capsys.readouterr().out


def test_without_a_terminal_it_lists_and_exits_two(monkeypatch, capsys):
    """A review cannot be conducted down a pipe; blocking would be worse."""
    assert run_accept_cli(monkeypatch, tty=False) == 2

    captured = capsys.readouterr()
    assert "alice/lab-1" in captured.out
    assert "needs a terminal" in captured.err


def test_a_cancelled_review_changes_nothing(monkeypatch, capsys):
    done = stub_actions(monkeypatch)
    review = cancel(begin_review(PENDING))

    assert run_accept_cli(monkeypatch, review=review) == 0
    assert done == []
    assert "Cancelled" in capsys.readouterr().out


def test_a_confirmed_review_exits_zero(monkeypatch, capsys):
    stub_actions(monkeypatch)
    review = Review(
        PENDING, (Choice.ACCEPT, Choice.SKIP, Choice.SKIP), 3, Stage.CONFIRMED
    )

    assert run_accept_cli(monkeypatch, review=review) == 0
    assert "1 accepted" in capsys.readouterr().out


def test_a_failed_action_exits_one(monkeypatch, capsys):
    stub_actions(monkeypatch, failing={1})
    review = Review(
        PENDING, (Choice.ACCEPT, Choice.SKIP, Choice.SKIP), 3, Stage.CONFIRMED
    )

    assert run_accept_cli(monkeypatch, review=review) == 1
    assert "404" in capsys.readouterr().out


def test_an_unlistable_set_of_invitations_exits_two(monkeypatch, capsys):
    error = AdapterError("gh auth login required")

    assert run_accept_cli(monkeypatch, error=error) == 2
    assert "auth login" in capsys.readouterr().err
