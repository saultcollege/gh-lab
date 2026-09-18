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

from gh_lab.adapters import AdapterError, ToolNotFound, git, github_cli
from gh_lab.commands.setup_check.config import (
    LAB_CONFIG_PATH,
    LabConfig,
    parse_lab_config,
)
from gh_lab.course_config import (
    ConfigError,
    CourseConfig,
    CourseConfigRef,
    normalise_repo_ref,
    parse_course_config,
)


class Status(StrEnum):
    """The outcome of a single check."""

    PASS = "pass"
    FAIL = "fail"
    SKIPPED = "skipped"


class Advice(StrEnum):
    """What to tell the reader about the checks that could not run.

    Chosen here rather than in the shell layer because it is a conclusion drawn
    from what the run observed. Only the wording belongs to the shell.

    The distinction that matters most is between "the GitHub CLI could not
    reach GitHub" and "it reached GitHub and was refused". A single successful
    call proves the caller is signed in, which makes advising them to sign in
    demonstrably wrong.
    """

    NONE = "none"
    INSTALL_GH = "install-gh"
    SIGN_IN = "sign-in"
    ENV_TOKEN_REJECTED = "env-token-rejected"
    COURSE_CONFIG_UNREADABLE = "course-config-unreadable"
    CODESPACE_TOKEN_SCOPE = "codespace-token-scope"
    ACTIONS_TOKEN = "actions-token"
    SEE_REASONS = "see-reasons"


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
    advice: Advice = Advice.NONE
    token_variable: str | None = None
    """The environment variable supplying gh's token, if one is."""

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
    github_reached: bool = False
    """Whether at least one request to GitHub through gh succeeded."""
    github_cli_missing: bool = False
    """Whether gh itself could not be found."""


def in_github_actions(env: Mapping[str, str] | None = None) -> bool:
    """Whether the command is running inside a GitHub Actions workflow."""
    env = os.environ if env is None else env

    return env.get("GITHUB_ACTIONS") == "true"


# gh reads GH_TOKEN first and falls back to GITHUB_TOKEN. Both take precedence
# over stored credentials, and while either is set `gh auth login` refuses to
# run, so no advice may suggest it without first clearing them.
TOKEN_VARIABLES = ("GH_TOKEN", "GITHUB_TOKEN")


def env_token_variable(env: Mapping[str, str]) -> str | None:
    """Name the environment variable gh is taking its token from, if any.

    Returns the variable rather than a boolean because the advice quotes it:
    telling someone to clear GITHUB_TOKEN when they set GH_TOKEN would send
    them after the wrong one.
    """
    for name in TOKEN_VARIABLES:
        if (env.get(name) or "").strip():
            return name

    return None


def in_codespace(env: Mapping[str, str]) -> bool:
    """Whether the command is running inside a GitHub Codespace.

    A Codespace is given a token scoped to the repository it belongs to, so it
    cannot read a private repository in another organization however well
    signed in the student is.
    """
    return env.get("CODESPACES") == "true"


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


def _course_reason(error: str | None, *, token_scoped: bool = False) -> str:
    """Explain why the faculty check could not run.

    GitHub answers 404 for a repository you cannot see as well as for one that
    does not exist, so a failure cannot tell the two apart.

    The faculty list is public precisely so that this does not happen, so both
    messages describe a course whose configuration is misplaced rather than a
    student who has done something wrong.

    Args:
        error: What the failed read reported, if anything.
        token_scoped: Whether the token in use is scoped to this repository, as
            a Codespace's is. Membership is then beside the point — the student
            may well be a member — so saying otherwise would send them to fix
            something that is not broken.
    """
    if token_scoped:
        base = (
            "the course configuration could not be read, because the token this "
            "environment provides can only see this repository. In a Codespace "
            "that means the course's faculty list is not public where it should "
            "be, which is nothing you have done wrong — tell your instructor"
        )
    else:
        base = (
            "the course configuration could not be read. It may have moved, or "
            "it may be private and you not yet a member of the course "
            "organization — ask your instructor if this does not resolve itself"
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
    *,
    token_scoped: bool = False,
) -> Check:
    title = "Faculty have access"

    if course_config is None:
        return _skipped(
            "faculty",
            title,
            _course_reason(course_config_error, token_scoped=token_scoped),
        )

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


def choose_advice(
    *,
    anything_skipped: bool,
    in_actions: bool,
    github_cli_missing: bool,
    github_reached: bool,
    course_config_read: bool,
    course_config_fetched: bool,
    env: Mapping[str, str],
) -> Advice:
    """Decide what to say about the checks that could not run.

    Pure, and a plain decision table: first match wins.

    The command previously advised ``gh auth login`` whenever anything was
    skipped, for any cause. That is wrong wherever the environment supplies a
    token, because gh refuses to run it then, and it is wrong wherever a
    request to GitHub has already succeeded, because that proves the caller is
    signed in.
    """
    if not anything_skipped:
        return Advice.NONE

    # A missing gh outranks the workflow case: the token snippet would be
    # useless advice on a runner that has no gh to give it to.
    if github_cli_missing:
        return Advice.INSTALL_GH

    if in_actions:
        return Advice.ACTIONS_TOKEN

    if not github_reached:
        if env_token_variable(env):
            return Advice.ENV_TOKEN_REJECTED
        return Advice.SIGN_IN

    if not course_config_read:
        # Only an unread *file* points at the token's reach. One that was read
        # and would not parse is the instructor's to fix.
        if in_codespace(env) and not course_config_fetched:
            return Advice.CODESPACE_TOKEN_SCOPE
        return Advice.COURSE_CONFIG_UNREADABLE

    return Advice.SEE_REASONS


def evaluate(
    *,
    lab: str,
    lab_config: LabConfig,
    course_config: CourseConfig | None,
    facts: RepoFacts,
    in_actions: bool = False,
    course_config_error: str | None = None,
    course_config_fetched: bool = False,
    env: Mapping[str, str] | None = None,
) -> SetupCheckReport:
    """Run every applicable check and return the report.

    Pure: every input is plain data and nothing is read or written. ``env`` is
    taken as an argument rather than read from :data:`os.environ` for that
    reason, and defaults to empty rather than to the real environment.

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
        course_config_fetched: Whether the file was read, whatever became of
            parsing it. Distinguishes a refused read from a malformed file.
        env: Environment to read for token and Codespace detection.
    """
    env = {} if env is None else env
    token_variable = env_token_variable(env)

    checks = [
        _check_repo_name(lab_config, facts),
        _check_branch(lab, lab_config, facts),
        _check_template(lab_config, facts),
        _check_private(facts),
    ]

    if not in_actions:
        checks.append(
            _check_faculty(
                course_config,
                facts,
                course_config_error,
                token_scoped=in_codespace(env) and not course_config_fetched,
            )
        )

    checks.append(_check_not_course_org(lab_config, facts))

    advice = choose_advice(
        anything_skipped=any(check.status is Status.SKIPPED for check in checks),
        in_actions=in_actions,
        github_cli_missing=facts.github_cli_missing,
        # Reading the course configuration is itself a successful request, so
        # it counts as having reached GitHub even if nothing else did.
        github_reached=facts.github_reached or course_config_fetched,
        course_config_read=course_config is not None,
        course_config_fetched=course_config_fetched,
        env=env,
    )

    return SetupCheckReport(
        checks=tuple(checks),
        lab=lab,
        faculty_skipped_in_actions=in_actions,
        advice=advice,
        token_variable=token_variable,
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


@dataclass(frozen=True)
class CourseConfigResult:
    """The outcome of fetching the course configuration.

    ``fetched`` says the file itself was read. A file that was read but is
    malformed is a mistake in the course's own configuration, not a sign that
    the reader cannot see the repository, and the two call for different
    advice. Collapsing them into a bare ``None`` is what made the command blame
    authentication for everything.
    """

    config: CourseConfig | None = None
    error: str | None = None
    fetched: bool = False


def load_course_config(reference: CourseConfigRef) -> CourseConfigResult:
    """Fetch and parse the course configuration from its private repository.

    Reads through the GitHub CLI, so it uses the authentication the environment
    already provides rather than asking the student to arrange any. Note that
    what that authentication can *see* varies: a Codespace or workflow token is
    scoped to its own repository and cannot read another organization's.
    """
    try:
        raw = github_cli.fetch_repo_file(
            reference.owner, reference.repo, reference.path, reference.ref
        )
    except AdapterError as error:
        return CourseConfigResult(error=str(error))

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as error:
        return CourseConfigResult(
            error=f"{reference} is not valid JSON: {error}", fetched=True
        )

    try:
        return CourseConfigResult(
            config=parse_course_config(data, source=str(reference)), fetched=True
        )
    except ConfigError as error:
        return CourseConfigResult(error=str(error), fetched=True)


def gather_facts(*, in_actions: bool, env: Mapping[str, str]) -> RepoFacts:
    """Collect what can be discovered about the repository.

    Each source is consulted independently, so that one failure degrades a
    single check to "skipped" instead of failing the command.
    """
    unavailable: dict[str, str] = {}

    name = owner = None
    is_private = None
    template_repo = None
    github_reached = False
    github_cli_missing = False

    try:
        repo = github_cli.repo_view()
        github_reached = True
        name = repo.get("name")
        owner_field = repo.get("owner")
        owner = owner_field.get("login") if isinstance(owner_field, dict) else None
        is_private = repo.get("isPrivate")
        template_repo = normalise_repo_ref(repo.get("templateRepository"))
    except AdapterError as error:
        github_cli_missing = isinstance(error, ToolNotFound)
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
            github_reached = True
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
        github_reached=github_reached,
        github_cli_missing=github_cli_missing,
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

    # The faculty check, the only thing the course configuration feeds, is not
    # built at all in Actions, because a workflow token cannot list
    # collaborators. Fetching the configuration there would be work thrown
    # away, whether or not the file is one a workflow token could read.
    course = CourseConfigResult()
    if not actions:
        course = load_course_config(lab_config.course_config)

    facts = gather_facts(in_actions=actions, env=env)

    return evaluate(
        lab=resolved_lab,
        lab_config=lab_config,
        course_config=course.config,
        facts=facts,
        in_actions=actions,
        course_config_error=course.error,
        course_config_fetched=course.fetched,
        env=env,
    )
