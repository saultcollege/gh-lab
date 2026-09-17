"""Tests for the ``admin invites`` commands.

The decisions are pure and are called directly with plain data. Only the two
functions that reach GitHub are stubbed, which is also how the suite proves that
a dry run reaches it at all.
"""

import argparse

import pytest

from gh_lab.adapters import AdapterError, github_cli
from gh_lab.cli import build_parser as main_parser
from gh_lab.cli import main
from gh_lab.commands.admin_invites import command as command_module
from gh_lab.commands.admin_invites import shell
from gh_lab.commands.admin_invites.command import (
    InviteResult,
    Outcome,
    RepositoryInvitation,
    SendReport,
    build_roster,
    invitations_from_org,
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
        owner="student",
        inviter="student",
        permission="write",
    )


def test_an_invitation_without_an_inviter_is_still_usable():
    """GitHub types inviter as nullable, and the id is what acting on it needs."""
    invitation = parse_invitation(invitation_entry(inviter=None))

    assert invitation is not None
    assert invitation.inviter is None


def test_an_owner_is_taken_from_the_full_name_when_absent():
    entry = invitation_entry()
    entry["repository"].pop("owner")

    assert parse_invitation(entry).owner == "student"


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


# --- Narrowing to one organization -----------------------------------------


INVITATIONS = (
    RepositoryInvitation(1, "course-org/lab-1", "course-org"),
    RepositoryInvitation(2, "someone-else/notes", "someone-else"),
    RepositoryInvitation(3, "Course-Org/lab-2", "Course-Org"),
)


def test_no_organization_keeps_everything():
    assert invitations_from_org(INVITATIONS, None) == INVITATIONS


def test_an_organization_narrows_the_listing():
    """Faculty have invitations that have nothing to do with the course."""
    kept = invitations_from_org(INVITATIONS, "course-org")

    assert [invitation.id for invitation in kept] == [1, 3]


def test_the_organization_is_matched_ignoring_case():
    assert [i.id for i in invitations_from_org(INVITATIONS, "COURSE-ORG")] == [1, 3]


def test_an_organization_with_no_invitations_keeps_nothing():
    assert invitations_from_org(INVITATIONS, "other-org") == ()
