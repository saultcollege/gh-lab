"""Tests for the ``setup-check`` command."""

import argparse
import dataclasses
import json

import pytest

from gh_lab.adapters import AdapterError, ToolNotFound
from gh_lab.cli import build_parser as main_parser
from gh_lab.cli import main
from gh_lab.commands.setup_check import shell
from gh_lab.commands.setup_check.command import (
    Advice,
    Check,
    CourseConfigResult,
    RepoFacts,
    SetupCheckReport,
    Status,
    choose_advice,
    env_token_variable,
    evaluate,
    in_codespace,
    resolve_branch,
)
from gh_lab.commands.setup_check.config import LabConfig
from gh_lab.course_config import CourseConfig, CourseConfigRef, Person

CONFIG_REF = CourseConfigRef("saultcollege-csd110", "course-config", "26f.json")

LAB_CONFIG = LabConfig(
    repo_name="csd110-lab-1",
    course_config=CONFIG_REF,
)

COURSE_CONFIG = CourseConfig(faculty=(Person(github="bobber24", name="Bob Bob"),))

GOOD_FACTS = RepoFacts(
    name="csd110-lab-1",
    owner="student-user",
    is_private=True,
    is_fork=False,
    collaborators=("student-user", "bobber24"),
    current_branch="lab-1",
    # These facts describe a run in which GitHub answered, so say so; the
    # advice is chosen from whether anything reached GitHub at all.
    github_reached=True,
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
            "fork",
            {"is_fork": True},
            "is a fork",
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


def test_every_failure_explains_itself_and_says_what_to_do():
    """A student must be able to act on a failure without asking for help.

    A command where there is one, and otherwise a note: a fork cannot be undone
    from the command line, so there is nothing to print for it that would work.
    """
    broken = dataclasses.replace(
        GOOD_FACTS,
        name="wrong",
        current_branch="main",
        is_private=False,
        collaborators=(),
        owner="saultcollege-csd110",
        is_fork=True,
    )

    report = report_for(broken)

    for check in report.failures:
        assert check.detail, f"{check.id} does not say what was found"
        assert check.explanation, f"{check.id} does not say why it matters"
        assert check.commands or check.note, f"{check.id} does not say what to do"


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
    assert status_of(report, "fork") is Status.SKIPPED
    # A skipped check is not a failure.
    assert report.ok


def test_the_fork_check_is_skipped_only_when_the_repository_is_unreadable():
    """Its one input comes from the same call as the name and the visibility.

    So there is no case where it alone cannot be answered, and the reason it
    gives is the one already recorded for that call.
    """
    facts = dataclasses.replace(
        GOOD_FACTS, is_fork=None, unavailable={"repo": "could not ask GitHub"}
    )

    check = check_named(report_for(facts), "fork")

    assert check.status is Status.SKIPPED
    assert "could not ask GitHub" in check.detail


def test_a_fork_says_what_to_do_without_offering_a_command():
    """There is no command that leaves a fork network, so none is printed."""
    check = check_named(
        report_for(dataclasses.replace(GOOD_FACTS, is_fork=True)), "fork"
    )

    assert check.status is Status.FAIL
    assert check.commands == ()
    assert "ask your instructor" in check.note


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

    for check_id in ("repo-name", "branch", "fork", "private", "not-course-org"):
        assert status_of(report, check_id) is Status.PASS

    assert report.ok


def test_faculty_check_is_omitted_entirely_in_github_actions():
    """The Actions token cannot list collaborators, so the check is not shown."""
    report = report_for(GOOD_FACTS, in_actions=True)

    assert [check.id for check in report.checks] == [
        "repo-name",
        "branch",
        "fork",
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
        lambda reference: (
            calls.append(reference),
            CourseConfigResult(config=COURSE_CONFIG, fetched=True),
        )[1],
    )

    report = command_module.run("1", env={})

    assert calls == [CONFIG_REF]
    assert status_of(report, "faculty") is Status.PASS


# --- Advice: what to say about checks that could not run ---------------------
#
# The command used to print "run gh auth login" whenever anything was skipped,
# for any cause. That is a dead end wherever the environment supplies a token,
# because gh refuses to run it then, which is exactly what a Codespace does.


def test_gh_token_is_preferred_over_github_token():
    env = {"GH_TOKEN": "a", "GITHUB_TOKEN": "b"}

    assert env_token_variable(env) == "GH_TOKEN"


def test_an_empty_token_is_no_token():
    assert env_token_variable({"GITHUB_TOKEN": "   "}) is None
    assert env_token_variable({}) is None


def test_github_token_is_found_on_its_own():
    assert env_token_variable({"GITHUB_TOKEN": "x"}) == "GITHUB_TOKEN"


def test_a_codespace_is_recognised():
    assert in_codespace({"CODESPACES": "true"})
    assert not in_codespace({"CODESPACES": "false"})
    assert not in_codespace({})


def advice_for(**kwargs) -> Advice:
    """``choose_advice`` with the arguments of an ordinary failing run."""
    return choose_advice(
        **{
            "anything_skipped": True,
            "in_actions": False,
            "github_cli_missing": False,
            "github_reached": True,
            "course_config_read": True,
            "course_config_fetched": True,
            "env": {},
            **kwargs,
        }
    )


def test_nothing_skipped_needs_no_advice():
    assert advice_for(anything_skipped=False) is Advice.NONE


def test_a_missing_gh_outranks_everything():
    """The workflow token snippet is useless where there is no gh to take it."""
    assert (
        advice_for(
            github_cli_missing=True,
            in_actions=True,
            env={"GH_TOKEN": "x"},
        )
        is Advice.INSTALL_GH
    )


def test_actions_advice_is_unchanged():
    assert advice_for(in_actions=True, github_reached=False) is Advice.ACTIONS_TOKEN


def test_nothing_reached_github_without_a_token_advises_signing_in():
    assert advice_for(github_reached=False) is Advice.SIGN_IN


@pytest.mark.parametrize("variable", ["GH_TOKEN", "GITHUB_TOKEN"])
def test_an_environment_token_is_never_told_to_sign_in(variable):
    assert (
        advice_for(github_reached=False, env={variable: "x"})
        is Advice.ENV_TOKEN_REJECTED
    )


def test_a_codespace_that_cannot_read_the_course_config():
    """The reported bug: signed in, reaching GitHub, config out of reach."""
    assert (
        advice_for(
            course_config_read=False,
            course_config_fetched=False,
            env={"CODESPACES": "true", "GITHUB_TOKEN": "x"},
        )
        is Advice.CODESPACE_TOKEN_SCOPE
    )


def test_an_unreadable_course_config_outside_a_codespace():
    assert (
        advice_for(course_config_read=False, course_config_fetched=False)
        is Advice.COURSE_CONFIG_UNREADABLE
    )


def test_a_malformed_course_config_is_not_blamed_on_a_codespace_token():
    """It was read, so the token reached it; the file itself is the problem."""
    assert (
        advice_for(
            course_config_read=False,
            course_config_fetched=True,
            env={"CODESPACES": "true", "GITHUB_TOKEN": "x"},
        )
        is Advice.COURSE_CONFIG_UNREADABLE
    )


def test_a_skip_that_is_not_about_access_says_so():
    """A detached HEAD is not a reason to sign in again."""
    assert advice_for() is Advice.SEE_REASONS


def test_evaluate_reports_the_codespace_case_end_to_end():
    report = report_for(
        GOOD_FACTS,
        course_config=None,
        course_config_error="gh: Not Found (HTTP 404)",
        course_config_fetched=False,
        env={"CODESPACES": "true", "GITHUB_TOKEN": "x"},
    )

    assert report.advice is Advice.CODESPACE_TOKEN_SCOPE
    assert report.token_variable == "GITHUB_TOKEN"
    assert status_of(report, "faculty") is Status.SKIPPED


def test_a_codespace_is_not_told_it_might_not_be_a_member():
    """The old reason named two causes, neither of which applies here."""
    report = report_for(
        GOOD_FACTS,
        course_config=None,
        course_config_error="gh: Not Found (HTTP 404)",
        course_config_fetched=False,
        env={"CODESPACES": "true", "GITHUB_TOKEN": "x"},
    )
    reason = check_named(report, "faculty").detail

    assert "can only see this repository" in reason
    assert "not yet a member" not in reason


def test_a_good_run_has_no_advice():
    assert report_for(GOOD_FACTS).advice is Advice.NONE


# --- gather_facts records how far gh got -------------------------------------


def test_gather_facts_notes_that_github_answered(monkeypatch):
    from gh_lab.commands.setup_check import command as command_module

    monkeypatch.setattr(
        command_module.github_cli,
        "repo_view",
        lambda: {"name": "csd110-lab-1", "owner": {"login": "student-user"}},
    )
    monkeypatch.setattr(
        command_module.github_cli, "list_collaborators", lambda owner, name: ("x",)
    )
    monkeypatch.setattr(command_module.git, "current_branch", lambda: "lab-1")

    facts = command_module.gather_facts(in_actions=False, env={})

    assert facts.github_reached
    assert not facts.github_cli_missing


def test_gather_facts_notices_a_missing_gh(monkeypatch):
    from gh_lab.commands.setup_check import command as command_module

    def missing():
        raise ToolNotFound("the GitHub CLI (gh) is not installed or not on PATH")

    monkeypatch.setattr(command_module.github_cli, "repo_view", missing)
    monkeypatch.setattr(command_module.git, "current_branch", lambda: "lab-1")

    facts = command_module.gather_facts(in_actions=False, env={})

    assert facts.github_cli_missing
    assert not facts.github_reached
    # The check still degrades to skipped rather than failing.
    assert "repo" in facts.unavailable


def test_gather_facts_does_not_call_a_refusal_a_missing_tool(monkeypatch):
    from gh_lab.commands.setup_check import command as command_module

    def refused():
        raise AdapterError("gh: Not Found (HTTP 404)")

    monkeypatch.setattr(command_module.github_cli, "repo_view", refused)
    monkeypatch.setattr(command_module.git, "current_branch", lambda: "lab-1")

    facts = command_module.gather_facts(in_actions=False, env={})

    assert not facts.github_cli_missing


# --- How the advice is rendered ----------------------------------------------


def rendered(advice: Advice, token_variable: str | None = None) -> str:
    """The whole report for a run carrying ``advice``, without colour."""
    report = SetupCheckReport(
        checks=(
            Check(id="faculty", title="Faculty have access", status=Status.SKIPPED),
        ),
        lab="1",
        advice=advice,
        token_variable=token_variable,
    )
    return shell.render_report(report, shell.Painter(False), shell.SYMBOLS)


def test_every_advice_has_wording():
    """A new Advice member cannot be added without something to print."""
    assert set(shell.ADVICE) == set(Advice) - {Advice.NONE}


@pytest.mark.parametrize(
    "advice",
    [
        Advice.INSTALL_GH,
        Advice.ENV_TOKEN_REJECTED,
        Advice.COURSE_CONFIG_UNREADABLE,
        Advice.ACTIONS_TOKEN,
        Advice.SEE_REASONS,
    ],
)
def test_the_footer_never_offers_gh_auth_login_where_it_would_refuse(advice):
    """The regression test for the bug as reported."""
    assert "gh auth login" not in rendered(advice)


def test_a_codespace_is_told_to_clear_the_token_before_signing_in():
    output = rendered(Advice.CODESPACE_TOKEN_SCOPE, "GITHUB_TOKEN")

    # gh auth login is offered, but never without the unset that makes it work.
    assert "unset GH_TOKEN GITHUB_TOKEN" in output
    assert output.index("unset GH_TOKEN GITHUB_TOKEN") < output.index("gh auth login")


def test_the_advice_names_the_variable_actually_set():
    """Sending someone after the variable they did not set wastes their time."""
    # Asserted by absence of the other name, because wrapping may split either.
    assert "GITHUB_TOKEN" not in rendered(Advice.ENV_TOKEN_REJECTED, "GH_TOKEN")
    assert "GITHUB_TOKEN" in rendered(Advice.ENV_TOKEN_REJECTED, "GITHUB_TOKEN")


def test_sign_in_advice_still_offers_gh_auth_login():
    assert "gh auth login" in rendered(Advice.SIGN_IN)


def test_the_actions_snippet_survives_rendering():
    """Its braces must not be eaten by the token interpolation."""
    assert "GH_TOKEN: ${{ github.token }}" in rendered(Advice.ACTIONS_TOKEN)


def test_no_advice_is_printed_when_nothing_was_skipped():
    report = SetupCheckReport(
        checks=(
            Check(id="private", title="Repository is private", status=Status.PASS),
        ),
        lab="1",
    )
    output = shell.render_report(report, shell.Painter(False), shell.SYMBOLS)

    assert "Look for 'not checked'" not in output


def test_json_reports_the_advice():
    report = SetupCheckReport(lab="1", advice=Advice.CODESPACE_TOKEN_SCOPE)

    assert json.loads(shell.report_to_json(report))["advice"] == "codespace-token-scope"
