"""Tests for the ``setup-check`` command."""

import argparse
import dataclasses

import pytest

from gh_lab.cli import build_parser as main_parser
from gh_lab.cli import main
from gh_lab.commands.setup_check.command import (
    RepoFacts,
    Status,
    evaluate,
    resolve_branch,
)
from gh_lab.commands.setup_check.config import LabConfig
from gh_lab.course_config import CourseConfig, CourseConfigRef, Person

TEMPLATE_URL = "https://github.com/saultcollege-csd110/lab-1-template"
TEMPLATE_REF = "saultcollege-csd110/lab-1-template"

CONFIG_REF = CourseConfigRef("saultcollege-csd110", "course-config", "26f.json")

LAB_CONFIG = LabConfig(
    repo_name="csd110-lab-1",
    template_repo=TEMPLATE_URL,
    course_config=CONFIG_REF,
)

COURSE_CONFIG = CourseConfig(faculty=(Person(github="bobber24", name="Bob Bob"),))

GOOD_FACTS = RepoFacts(
    name="csd110-lab-1",
    owner="student-user",
    is_private=True,
    template_repo=TEMPLATE_REF,
    collaborators=("student-user", "bobber24"),
    current_branch="lab-1",
)


def report_for(facts: RepoFacts, **kwargs):
    """Evaluate ``facts`` against the standard configuration."""
    return evaluate(
        lab=kwargs.pop("lab", "1"),
        lab_config=kwargs.pop("lab_config", LAB_CONFIG),
        course_config=kwargs.pop("course_config", COURSE_CONFIG),
        facts=facts,
        **kwargs,
    )


def status_of(report, check_id: str) -> Status:
    """The status of a single check within ``report``."""
    return next(check.status for check in report.checks if check.id == check_id)


def check_named(report, check_id: str):
    """A single check within ``report``."""
    return next(check for check in report.checks if check.id == check_id)


# --- CLI wiring ------------------------------------------------------------


def test_setup_check_appears_in_top_level_help(capsys):
    with pytest.raises(SystemExit):
        main(["--help"])

    assert "setup-check" in capsys.readouterr().out


def test_lab_argument_is_optional(capsys):
    """The lab may come from .lab/config.json, so it must not be required."""
    with pytest.raises(SystemExit) as exc_info:
        main(["setup-check", "--help"])

    assert exc_info.value.code == 0
    assert "[LAB]" in capsys.readouterr().out


def test_rejects_a_lab_name_that_could_forge_a_branch(capsys):
    exit_code = main(["setup-check", "../evil"])

    assert exit_code == 2
    assert "not a valid lab name" in capsys.readouterr().err


def setup_check_parser() -> argparse.ArgumentParser:
    """The subparser registered for setup-check."""
    for action in main_parser()._actions:
        if isinstance(action, argparse._SubParsersAction):
            return action.choices["setup-check"]

    raise AssertionError("setup-check is not registered")


def test_argument_surface_is_stable():
    """Pin the arguments, because CI invokes them directly.

    `.github/workflows/ci.yml` hard-codes these, and a stale invocation there is
    not caught by this suite: it fails only once the change has been pushed. If
    this test fails, update the workflow in the same change.
    """
    parser = setup_check_parser()

    options = {option for action in parser._actions for option in action.option_strings}
    positionals = [
        action.dest for action in parser._actions if not action.option_strings
    ]

    assert options == {"-h", "--help", "--format", "--color"}
    assert positionals == ["lab"]


# --- A fully correct setup -------------------------------------------------


def test_everything_passes_for_a_correct_setup():
    report = report_for(GOOD_FACTS)

    assert report.ok
    assert {check.status for check in report.checks} == {Status.PASS}
    assert report.lab == "1"


# --- Individual checks -----------------------------------------------------


@pytest.mark.parametrize(
    ("check_id", "facts", "expected_in_detail"),
    [
        (
            "repo-name",
            {"name": "my-cool-repo"},
            "'my-cool-repo'",
        ),
        (
            "branch",
            {"current_branch": "main"},
            "'main'",
        ),
        (
            "template",
            {"template_repo": None},
            "not created from a template",
        ),
        (
            "template",
            {"template_repo": "someone-else/other-template"},
            "someone-else/other-template",
        ),
        (
            "private",
            {"is_private": False},
            "public",
        ),
        (
            "faculty",
            {"collaborators": ("student-user",)},
            "Bob Bob (@bobber24)",
        ),
        (
            "not-course-org",
            {"owner": "saultcollege-csd110"},
            "saultcollege-csd110",
        ),
    ],
)
def test_each_check_can_fail(check_id, facts, expected_in_detail):
    report = report_for(dataclasses.replace(GOOD_FACTS, **facts))
    check = check_named(report, check_id)

    assert check.status is Status.FAIL
    assert expected_in_detail in check.detail
    assert not report.ok


def test_every_failure_explains_itself_and_says_what_to_run():
    """A student must be able to act on a failure without asking for help."""
    broken = dataclasses.replace(
        GOOD_FACTS,
        name="wrong",
        current_branch="main",
        is_private=False,
        collaborators=(),
        owner="saultcollege-csd110",
        template_repo=None,
    )

    report = report_for(broken)

    for check in report.failures:
        assert check.detail, f"{check.id} does not say what was found"
        assert check.explanation, f"{check.id} does not say why it matters"
        assert check.commands, f"{check.id} does not say what to run"


def test_branch_name_follows_the_configured_pattern():
    lab_config = dataclasses.replace(LAB_CONFIG, branch_pattern="week-{lab}")

    facts = dataclasses.replace(GOOD_FACTS, current_branch="week-05")
    report = report_for(facts, lab="05", lab_config=lab_config)

    assert status_of(report, "branch") is Status.PASS


def test_faculty_matching_ignores_case():
    facts = dataclasses.replace(GOOD_FACTS, collaborators=("BobBer24",))

    assert status_of(report_for(facts), "faculty") is Status.PASS


def test_multiple_missing_faculty_each_get_a_command():
    course = CourseConfig(
        faculty=(
            Person(github="bobber24", name="Bob Bob"),
            Person(github="alice99"),
        ),
    )

    facts = dataclasses.replace(GOOD_FACTS, collaborators=())
    check = check_named(report_for(facts, course_config=course), "faculty")

    assert check.status is Status.FAIL
    assert len(check.commands) == 2
    assert "are not collaborators" in check.detail


# --- Degrading when information is unavailable -----------------------------


def test_unavailable_information_skips_rather_than_fails():
    facts = RepoFacts(
        current_branch="lab-1",
        unavailable={"repo": "could not ask GitHub", "collaborators": "no access"},
    )

    report = report_for(facts)

    assert status_of(report, "repo-name") is Status.SKIPPED
    assert status_of(report, "private") is Status.SKIPPED
    assert status_of(report, "faculty") is Status.SKIPPED
    # A skipped check is not a failure.
    assert report.ok


def test_an_unreadable_course_config_costs_only_the_faculty_check():
    """The course config lives in a private repo a workflow cannot read.

    Everything except the faculty list is stated in or derived from
    .lab/config.json precisely so that the rest keeps working without it.
    """
    report = report_for(GOOD_FACTS, course_config=None, course_config_error="HTTP 404")

    faculty = check_named(report, "faculty")
    assert faculty.status is Status.SKIPPED
    assert "HTTP 404" in faculty.detail
    # It cannot tell "not a member yet" from "moved", so it must name both.
    assert "member of the course organization" in faculty.detail

    for check_id in ("repo-name", "branch", "template", "private", "not-course-org"):
        assert status_of(report, check_id) is Status.PASS

    assert report.ok


def test_faculty_check_is_omitted_entirely_in_github_actions():
    """The Actions token cannot list collaborators, so the check is not shown."""
    report = report_for(GOOD_FACTS, in_actions=True)

    assert [check.id for check in report.checks] == [
        "repo-name",
        "branch",
        "template",
        "private",
        "not-course-org",
    ]
    assert report.faculty_skipped_in_actions


# --- Branch resolution -----------------------------------------------------


def test_resolve_branch_uses_git_outside_actions():
    assert resolve_branch({}, "lab-1") == "lab-1"


def test_resolve_branch_prefers_head_ref_on_a_pull_request():
    """GITHUB_REF_NAME is '<number>/merge' on pull requests, not a branch."""
    env = {
        "GITHUB_ACTIONS": "true",
        "GITHUB_HEAD_REF": "lab-1",
        "GITHUB_REF_NAME": "42/merge",
    }

    assert resolve_branch(env, None) == "lab-1"


def test_resolve_branch_uses_ref_name_on_a_push():
    env = {
        "GITHUB_ACTIONS": "true",
        "GITHUB_HEAD_REF": "",
        "GITHUB_REF_NAME": "lab-1",
    }

    assert resolve_branch(env, None) == "lab-1"


def test_course_config_is_not_fetched_inside_actions(monkeypatch):
    """A workflow token cannot read the course org's private repository."""
    from gh_lab.commands.setup_check import command as command_module

    def fail(*args, **kwargs):
        raise AssertionError("the course configuration must not be fetched in Actions")

    monkeypatch.setattr(command_module, "load_course_config", fail)
    monkeypatch.setattr(command_module, "load_lab_config", lambda: LAB_CONFIG)
    monkeypatch.setattr(command_module, "gather_facts", lambda **kwargs: GOOD_FACTS)

    report = command_module.run("1", env={"GITHUB_ACTIONS": "true"})

    assert report.faculty_skipped_in_actions
    assert not any(check.id == "faculty" for check in report.checks)


def test_course_config_is_fetched_outside_actions(monkeypatch):
    from gh_lab.commands.setup_check import command as command_module

    calls = []

    monkeypatch.setattr(command_module, "load_lab_config", lambda: LAB_CONFIG)
    monkeypatch.setattr(command_module, "gather_facts", lambda **kwargs: GOOD_FACTS)
    monkeypatch.setattr(
        command_module,
        "load_course_config",
        lambda reference: (calls.append(reference), (COURSE_CONFIG, None))[1],
    )

    report = command_module.run("1", env={})

    assert calls == [CONFIG_REF]
    assert status_of(report, "faculty") is Status.PASS
