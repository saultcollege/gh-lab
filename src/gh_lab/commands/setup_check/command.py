"""Core logic for the ``setup-check`` command.

The checks themselves are pure: :func:`evaluate` takes plain data describing the
repository and returns a structured report, including the remediation advice for
anything that failed. Gathering that data is kept separate and deliberately thin.
"""

import json
import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum

from gh_lab.adapters import AdapterError, git, github_cli
from gh_lab.commands.setup_check.config import (
    LAB_CONFIG_PATH,
    ConfigError,
    CourseConfig,
    CourseConfigRef,
    LabConfig,
    normalise_repo_ref,
    parse_course_config,
    parse_lab_config,
)


class Status(StrEnum):
    """The outcome of a single check."""

    PASS = "pass"
    FAIL = "fail"
    SKIPPED = "skipped"


@dataclass(frozen=True)
class Check:
    """The outcome of one check, with everything needed to explain it.

    The remediation is held as structured data rather than formatted text so
    that the wording can be tested field by field and the shell layer stays
    responsible only for wrapping and colour.

    Attributes:
        id: Stable identifier, used in JSON output.
        title: Short human-readable name.
        status: Whether the check passed, failed, or could not run.
        detail: What was found.
        explanation: Why it matters, in plain language.
        commands: Exact commands to run, in order, to fix the problem.
        note: A caveat worth reading before acting on ``commands``.
    """

    id: str
    title: str
    status: Status
    detail: str = ""
    explanation: str = ""
    commands: tuple[str, ...] = ()
    note: str = ""


@dataclass(frozen=True)
class SetupCheckReport:
    """The result of running every applicable check."""

    checks: tuple[Check, ...] = ()
    lab: str = ""
    faculty_skipped_in_actions: bool = False

    @property
    def failures(self) -> tuple[Check, ...]:
        """The checks that failed."""
        return tuple(check for check in self.checks if check.status is Status.FAIL)

    @property
    def skipped(self) -> tuple[Check, ...]:
        """The checks that could not be run."""
        return tuple(check for check in self.checks if check.status is Status.SKIPPED)

    @property
    def ok(self) -> bool:
        """Whether every check that ran passed."""
        return not self.failures


@dataclass(frozen=True)
class RepoFacts:
    """What could be discovered about the repository.

    A field is ``None`` when it could not be determined, which produces a
    skipped check rather than a failure. ``unavailable`` explains why, keyed by
    the source that failed.
    """

    name: str | None = None
    owner: str | None = None
    is_private: bool | None = None
    template_repo: str | None = None
    collaborators: tuple[str, ...] | None = None
    current_branch: str | None = None
    unavailable: Mapping[str, str] = field(default_factory=dict)


def in_github_actions(env: Mapping[str, str] | None = None) -> bool:
    """Whether the command is running inside a GitHub Actions workflow."""
    env = os.environ if env is None else env

    return env.get("GITHUB_ACTIONS") == "true"


def resolve_branch(
    env: Mapping[str, str],
    git_branch: str | None,
) -> str | None:
    """Determine the branch the student is working on.

    Inside GitHub Actions the working tree is not necessarily on a branch: on a
    pull request ``actions/checkout`` leaves a detached HEAD, so git reports no
    branch at all, and ``GITHUB_REF_NAME`` holds ``<number>/merge`` rather than
    a branch name. ``GITHUB_HEAD_REF``, which is set only for pull request
    events, holds the branch the pull request came from.
    """
    if in_github_actions(env):
        head_ref = (env.get("GITHUB_HEAD_REF") or "").strip()
        if head_ref:
            return head_ref

        ref_name = (env.get("GITHUB_REF_NAME") or "").strip()
        if ref_name:
            return ref_name

    return git_branch


def _skipped(check_id: str, title: str, reason: str) -> Check:
    return Check(id=check_id, title=title, status=Status.SKIPPED, detail=reason)


def _course_reason(error: str | None) -> str:
    """Explain why the faculty check could not run.

    GitHub answers 404 for a repository you cannot see as well as for one that
    does not exist, so a failure cannot tell the two apart. Name both, since the
    student can act on one of them and only their instructor can act on the other.
    """
    base = (
        "the course configuration could not be read. Either you are not yet a "
        "member of the course organization, or the course configuration has "
        "moved — ask your instructor if this does not resolve itself"
    )

    return f"{base} ({error})" if error else base


def _check_repo_name(lab_config: LabConfig, facts: RepoFacts) -> Check:
    title = "Repository name"
    expected = lab_config.repo_name

    if facts.name is None:
        return _skipped("repo-name", title, facts.unavailable.get("repo", "unknown"))

    if facts.name == expected:
        return Check(id="repo-name", title=title, status=Status.PASS, detail=facts.name)

    return Check(
        id="repo-name",
        title=title,
        status=Status.FAIL,
        detail=f"Your repository is named '{facts.name}', but this lab expects '{expected}'.",
        explanation=(
            "Your instructor's tools find your work by its repository name, so it has "
            "to match exactly."
        ),
        commands=(f"gh repo rename {expected}",),
    )


def _check_branch(lab: str, lab_config: LabConfig, facts: RepoFacts) -> Check:
    title = "Branch"
    expected = lab_config.branch_pattern.format(lab=lab)

    if facts.current_branch is None:
        return _skipped(
            "branch", title, facts.unavailable.get("branch", "the branch is unknown")
        )

    if facts.current_branch == expected:
        return Check(id="branch", title=title, status=Status.PASS, detail=expected)

    return Check(
        id="branch",
        title=title,
        status=Status.FAIL,
        detail=(
            f"You are on branch '{facts.current_branch}', but your work for lab {lab} "
            f"must be on a branch named '{expected}'."
        ),
        explanation=(
            "Each lab is submitted from its own branch so that your work stays "
            "separate and can be reviewed in a pull request."
        ),
        commands=(f"git switch -c {expected}",),
        note=(
            f"That command creates the branch and brings any uncommitted work with "
            f"you. If you have already made commits on '{facts.current_branch}', ask "
            f"your instructor before continuing — moving commits needs care."
        ),
    )


def _check_template(lab_config: LabConfig, facts: RepoFacts) -> Check:
    title = "Created from the lab template"
    expected = normalise_repo_ref(lab_config.template_repo)

    if "repo" in facts.unavailable:
        return _skipped("template", title, facts.unavailable["repo"])

    if expected is None:
        return _skipped(
            "template",
            title,
            f"{LAB_CONFIG_PATH} does not name a valid template repository",
        )

    if facts.template_repo == expected:
        return Check(id="template", title=title, status=Status.PASS, detail=expected)

    if facts.template_repo is None:
        detail = "Your repository was not created from a template."
    else:
        detail = (
            f"Your repository was created from '{facts.template_repo}', "
            f"but this lab expects '{expected}'."
        )

    return Check(
        id="template",
        title=title,
        status=Status.FAIL,
        detail=detail,
        explanation=(
            "Lab repositories must be created using the 'Use this template' button on "
            "the template repository, so that they start with the right files and "
            "settings. Downloading, copying, or forking the files is not the same thing."
        ),
        commands=(
            (
                f"gh repo create {lab_config.repo_name} --private "
                f"--template {expected} --clone"
            ),
        ),
        note=(
            "That command makes a fresh repository from the template. If you have "
            "already done work in this one, ask your instructor for help moving it "
            "across before you delete anything."
        ),
    )


def _check_private(facts: RepoFacts) -> Check:
    title = "Repository is private"

    if facts.is_private is None:
        return _skipped("private", title, facts.unavailable.get("repo", "unknown"))

    if facts.is_private:
        return Check(id="private", title=title, status=Status.PASS)

    return Check(
        id="private",
        title=title,
        status=Status.FAIL,
        detail="Your repository is public.",
        explanation=(
            "Lab repositories must be private so that other students cannot see your "
            "work."
        ),
        commands=(
            (
                "gh repo edit --visibility private "
                "--accept-visibility-change-consequences"
            ),
        ),
    )


def _check_faculty(
    course_config: CourseConfig | None,
    facts: RepoFacts,
    course_config_error: str | None = None,
) -> Check:
    title = "Faculty have access"

    if course_config is None:
        return _skipped("faculty", title, _course_reason(course_config_error))

    if facts.collaborators is None:
        return _skipped(
            "faculty",
            title,
            facts.unavailable.get("collaborators", "the collaborator list is unknown"),
        )

    present = {login.casefold() for login in facts.collaborators}
    missing = [
        person
        for person in course_config.faculty
        if person.github.casefold() not in present
    ]

    if not missing:
        return Check(
            id="faculty",
            title=title,
            status=Status.PASS,
            detail=", ".join(person.display for person in course_config.faculty),
        )

    names = ", ".join(person.display for person in missing)
    owner = facts.owner or "YOUR-USERNAME"
    name = facts.name or "YOUR-REPO"

    if len(missing) == 1:
        detail = f"{names} is not a collaborator on your repository."
    else:
        detail = f"{names} are not collaborators on your repository."

    return Check(
        id="faculty",
        title=title,
        status=Status.FAIL,
        detail=detail,
        explanation=(
            "Your instructor needs access to your repository in order to see and mark "
            "your work."
        ),
        commands=tuple(
            f"gh api -X PUT repos/{owner}/{name}/collaborators/{person.github}"
            for person in missing
        ),
        note=(
            "This sends an invitation. It will not count as access until your "
            "instructor accepts it, so run this check again later to confirm."
        ),
    )


def _check_not_course_org(lab_config: LabConfig, facts: RepoFacts) -> Check:
    title = "Owned by you, not the course organization"
    course_org = lab_config.course_org

    if course_org is None:
        return _skipped(
            "not-course-org",
            title,
            f"{LAB_CONFIG_PATH} does not name a valid 'template-repo'",
        )

    if facts.owner is None:
        return _skipped(
            "not-course-org", title, facts.unavailable.get("repo", "unknown")
        )

    if facts.owner.casefold() != course_org.casefold():
        return Check(
            id="not-course-org",
            title=title,
            status=Status.PASS,
            detail=f"owned by {facts.owner}",
        )

    return Check(
        id="not-course-org",
        title=title,
        status=Status.FAIL,
        detail=(
            f"Your repository is owned by '{facts.owner}', which is the course "
            "organization."
        ),
        explanation=(
            "Each student works in their own copy of the lab, created in their personal "
            "GitHub account. The course organization only holds the templates."
        ),
        commands=(
            (
                f"gh repo create {lab_config.repo_name} --private "
                f"--template {normalise_repo_ref(lab_config.template_repo)} --clone"
            ),
        ),
        note=(
            "Run that from your own account. Ask your instructor before deleting the "
            "repository you are in now."
        ),
    )


def evaluate(
    *,
    lab: str,
    lab_config: LabConfig,
    course_config: CourseConfig | None,
    facts: RepoFacts,
    in_actions: bool = False,
    course_config_error: str | None = None,
) -> SetupCheckReport:
    """Run every applicable check and return the report.

    Pure: every input is plain data and nothing is read or written.

    Args:
        lab: The lab being checked.
        lab_config: Contents of ``.lab/config.json``.
        course_config: The course configuration, or ``None`` if unavailable.
            Only the faculty check depends on it, so everything else still runs.
        facts: What is known about the repository.
        in_actions: Whether this is running in GitHub Actions, where the faculty
            check is omitted entirely: the available token can neither list
            collaborators nor read the course organization's private repository.
        course_config_error: Why the course configuration was unavailable.
    """
    checks = [
        _check_repo_name(lab_config, facts),
        _check_branch(lab, lab_config, facts),
        _check_template(lab_config, facts),
        _check_private(facts),
    ]

    if not in_actions:
        checks.append(_check_faculty(course_config, facts, course_config_error))

    checks.append(_check_not_course_org(lab_config, facts))

    return SetupCheckReport(
        checks=tuple(checks),
        lab=lab,
        faculty_skipped_in_actions=in_actions,
    )


def load_lab_config() -> LabConfig:
    """Read and parse ``.lab/config.json`` from the current repository.

    Raises:
        ConfigError: If the repository or the file cannot be read, or the file
            is malformed.
    """
    try:
        root = git.repo_root()
    except AdapterError as error:
        raise ConfigError(
            f"this does not look like a git repository ({error})"
        ) from error

    path = root / LAB_CONFIG_PATH

    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as error:
        raise ConfigError(
            f"could not read {LAB_CONFIG_PATH} in {root} — "
            "is this a lab repository created from a lab template?"
        ) from error

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as error:
        raise ConfigError(f"{LAB_CONFIG_PATH} is not valid JSON: {error}") from error

    return parse_lab_config(data)


def load_course_config(
    reference: CourseConfigRef,
) -> tuple[CourseConfig | None, str | None]:
    """Fetch and parse the course configuration from its private repository.

    Reads through the GitHub CLI, so it uses the authentication the environment
    already provides rather than asking the student to arrange any.

    Returns:
        The configuration, or ``(None, reason)`` if it could not be obtained.
    """
    try:
        raw = github_cli.fetch_repo_file(
            reference.owner, reference.repo, reference.path, reference.ref
        )
    except AdapterError as error:
        return None, str(error)

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as error:
        return None, f"{reference} is not valid JSON: {error}"

    try:
        return parse_course_config(data, source=str(reference)), None
    except ConfigError as error:
        return None, str(error)


def gather_facts(*, in_actions: bool, env: Mapping[str, str]) -> RepoFacts:
    """Collect what can be discovered about the repository.

    Each source is consulted independently, so that one failure degrades a
    single check to "skipped" instead of failing the command.
    """
    unavailable: dict[str, str] = {}

    name = owner = None
    is_private = None
    template_repo = None

    try:
        repo = github_cli.repo_view()
        name = repo.get("name")
        owner_field = repo.get("owner")
        owner = owner_field.get("login") if isinstance(owner_field, dict) else None
        is_private = repo.get("isPrivate")
        template_repo = normalise_repo_ref(repo.get("templateRepository"))
    except AdapterError as error:
        unavailable["repo"] = f"could not ask GitHub about this repository ({error})"

    try:
        git_branch = git.current_branch()
    except AdapterError as error:
        git_branch = None
        unavailable["branch"] = f"could not determine the current branch ({error})"

    current_branch = resolve_branch(env, git_branch)

    collaborators = None
    if in_actions:
        unavailable["collaborators"] = "not checked inside GitHub Actions"
    elif owner and name:
        try:
            collaborators = github_cli.list_collaborators(owner, name)
        except AdapterError as error:
            unavailable["collaborators"] = f"could not list collaborators ({error})"
    else:
        unavailable["collaborators"] = "the repository could not be identified"

    return RepoFacts(
        name=name,
        owner=owner,
        is_private=is_private,
        template_repo=template_repo,
        collaborators=collaborators,
        current_branch=current_branch,
        unavailable=unavailable,
    )


def run(
    lab: str | None = None, env: Mapping[str, str] | None = None
) -> SetupCheckReport:
    """Check that the current lab repository is set up correctly.

    Args:
        lab: The lab to check. Falls back to the ``lab`` field of
            ``.lab/config.json``, which single-lab templates set.
        env: Environment to read, for testing. Defaults to :data:`os.environ`.

    Raises:
        ConfigError: If the lab configuration is missing or unusable, or no lab
            could be determined.
    """
    env = os.environ if env is None else env

    lab_config = load_lab_config()
    resolved_lab = lab or lab_config.lab

    if not resolved_lab:
        raise ConfigError(
            "no lab was given and "
            f"{LAB_CONFIG_PATH} does not set 'lab'. "
            "This repository holds more than one lab, so name the one you are "
            "working on, for example: gh lab setup-check 1"
        )

    actions = in_github_actions(env)

    # A workflow token cannot read a private repository in the course
    # organization, so do not make a request that is bound to fail. The faculty
    # check, the only thing the course configuration feeds, is skipped in
    # Actions anyway.
    course_config: CourseConfig | None = None
    course_config_error: str | None = None
    if not actions:
        course_config, course_config_error = load_course_config(
            lab_config.course_config
        )

    facts = gather_facts(in_actions=actions, env=env)

    return evaluate(
        lab=resolved_lab,
        lab_config=lab_config,
        course_config=course_config,
        facts=facts,
        in_actions=actions,
        course_config_error=course_config_error,
    )
