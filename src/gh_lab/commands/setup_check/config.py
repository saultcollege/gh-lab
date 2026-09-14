"""Configuration used by ``setup-check``.

Two files describe a lab:

* ``.lab/config.json`` in the root of the student's repository, written by the
  lab template and unique to it;
* a course configuration document, held in a private repository owned by the
  course organization and shared by every lab in the course.

The course configuration carries only the faculty list. Everything else a check
needs is either stated in ``.lab/config.json`` or derived from it, because a
workflow running in a student's repository cannot read a private repository in
the course organization. Keeping the rest local means ``setup-check`` behaves
the same in a devcontainer and in GitHub Actions.

Everything here is pure: parsing takes already-loaded data and returns
structured values, so it can be tested without a repository or the network.
"""

from dataclasses import dataclass
from typing import Any

LAB_CONFIG_PATH = ".lab/config.json"

DEFAULT_BRANCH_PATTERN = "lab-{lab}"

GITHUB_HOST = "github.com"


class ConfigError(Exception):
    """A configuration file is missing a required field or is malformed."""


def normalise_repo_ref(value: Any) -> str | None:
    """Reduce a repository reference to a lowercase ``owner/name``.

    Accepts the URL form used in ``.lab/config.json``
    (``https://github.com/org/repo``, with or without ``.git``), the
    ``owner/name`` shorthand, and the object returned by
    ``gh repo view --json templateRepository``.

    Returns:
        The normalised reference, or ``None`` if ``value`` does not identify a
        repository.
    """
    if isinstance(value, dict):
        owner = value.get("owner")
        if isinstance(owner, dict):
            owner = owner.get("login")
        name = value.get("name")

        if isinstance(owner, str) and isinstance(name, str) and owner and name:
            return f"{owner}/{name}".casefold()

        return None

    if not isinstance(value, str):
        return None

    text = value.strip().rstrip("/")
    if not text:
        return None

    # Strip any scheme and host, leaving the path.
    for separator in ("://", "@"):
        if separator in text:
            text = text.split(separator, 1)[1]

    text = text.replace(":", "/")

    if text.casefold().startswith(f"{GITHUB_HOST}/"):
        text = text[len(GITHUB_HOST) + 1 :]

    if text.casefold().endswith(".git"):
        text = text[: -len(".git")]

    parts = [part for part in text.split("/") if part]
    if len(parts) < 2:
        return None

    return f"{parts[-2]}/{parts[-1]}".casefold()


@dataclass(frozen=True)
class Faculty:
    """A member of faculty who should have access to student repositories."""

    github: str
    name: str | None = None

    @property
    def display(self) -> str:
        """A human-readable identification, e.g. ``Bob Bob (@bobber24)``."""
        return f"{self.name} (@{self.github})" if self.name else f"@{self.github}"


@dataclass(frozen=True)
class CourseConfigRef:
    """Where the course configuration file lives."""

    owner: str
    repo: str
    path: str
    ref: str | None = None

    def __str__(self) -> str:
        suffix = f"@{self.ref}" if self.ref else ""
        return f"{self.owner}/{self.repo}/{self.path}{suffix}"


@dataclass(frozen=True)
class LabConfig:
    """The contents of ``.lab/config.json``.

    Attributes:
        repo_name: The name the student's repository must have.
        template_repo: The template the repository should have been created from.
        course_config: Where to find the course configuration.
        branch_pattern: Expected branch name, with ``{lab}`` replaced by the lab.
        lab: The lab this repository is for. Set by templates that serve a single
            lab; omitted when one repository is used for several labs, in which
            case the student names the lab on the command line.
    """

    repo_name: str
    template_repo: str
    course_config: CourseConfigRef
    branch_pattern: str = DEFAULT_BRANCH_PATTERN
    lab: str | None = None

    @property
    def course_org(self) -> str | None:
        """The organization that owns the lab template.

        Student repositories must not be owned by it. It is not configured
        separately because it is, by definition, the owner of ``template_repo``.
        """
        reference = normalise_repo_ref(self.template_repo)

        return reference.split("/")[0] if reference else None


@dataclass(frozen=True)
class CourseConfig:
    """The contents of the course configuration document.

    Only the faculty list: see the module docstring for why nothing else lives
    here.
    """

    faculty: tuple[Faculty, ...]


def _require_string(data: dict[str, Any], key: str, source: str) -> str:
    value = data.get(key)

    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"{source} is missing a {key!r} value")

    return value.strip()


def _optional_string(data: dict[str, Any], key: str, source: str) -> str | None:
    value = data.get(key)

    if value is None:
        return None

    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"{source} has an invalid {key!r} value")

    return value.strip()


def parse_course_config_ref(
    value: str,
    source: str = LAB_CONFIG_PATH,
) -> CourseConfigRef:
    """Locate the course configuration from a ``course-config`` value.

    Three spellings are accepted, because faculty writing the template are as
    likely to paste a link from the browser as to type the short form::

        org/course-config/26f.json
        org/course-config/26f.json@main
        https://github.com/org/course-config/blob/main/26f.json
    """
    text = value.strip()

    if not text:
        raise ConfigError(f"{source} is missing a 'course-config' value")

    if "://" in text or text.casefold().startswith(f"{GITHUB_HOST}/"):
        return _parse_url_ref(text, source)

    # An '@ref' suffix is the tail of the whole value, so anything after it
    # containing a '/' is part of the path instead. This leaves a path such as
    # 'dir@odd/26f.json' alone, at the cost of not supporting a ref containing a
    # '/' in this form; use the URL form for those.
    head, separator, tail = text.rpartition("@")
    ref = tail if separator and head and "/" not in tail else None
    if ref:
        text = head

    parts = [part for part in text.split("/") if part]

    if len(parts) < 3:
        raise ConfigError(
            f"{source} has a 'course-config' value of {value!r}, which does not "
            "name a file. Expected owner/repo/path, for example "
            "my-org/course-config/26f.json"
        )

    return CourseConfigRef(
        owner=parts[0],
        repo=parts[1],
        path="/".join(parts[2:]),
        ref=ref,
    )


def _parse_url_ref(text: str, source: str) -> CourseConfigRef:
    """Parse the ``blob``/``raw`` URL form copied from a browser."""
    body = text.split("://", 1)[1] if "://" in text else text

    if body.casefold().startswith(f"{GITHUB_HOST}/"):
        body = body[len(GITHUB_HOST) + 1 :]

    parts = [part for part in body.split("/") if part]

    if len(parts) >= 5 and parts[2].casefold() in ("blob", "raw"):
        return CourseConfigRef(
            owner=parts[0],
            repo=parts[1],
            ref=parts[3],
            path="/".join(parts[4:]),
        )

    raise ConfigError(
        f"{source} has a 'course-config' URL of {text!r} that does not point at "
        "a file. Expected a link to the file on GitHub, for example "
        "https://github.com/my-org/course-config/blob/main/26f.json"
    )


def parse_lab_config(data: Any, source: str = LAB_CONFIG_PATH) -> LabConfig:
    """Build a :class:`LabConfig` from already-loaded JSON."""
    if not isinstance(data, dict):
        raise ConfigError(f"{source} must contain a JSON object")

    return LabConfig(
        repo_name=_require_string(data, "repo-name", source),
        template_repo=_require_string(data, "template-repo", source),
        course_config=parse_course_config_ref(
            _require_string(data, "course-config", source), source
        ),
        branch_pattern=_optional_string(data, "branch-pattern", source)
        or DEFAULT_BRANCH_PATTERN,
        lab=_optional_string(data, "lab", source),
    )


def parse_faculty(entries: Any, source: str) -> tuple[Faculty, ...]:
    """Build the faculty list from the ``faculty`` array of a course config.

    Each entry is an object; only its ``github`` property is required. Errors
    name the offending index, because the person who has to fix the file is the
    faculty member who wrote it.
    """
    if not isinstance(entries, list):
        raise ConfigError(f"{source} is missing a 'faculty' array")

    faculty = []
    for index, entry in enumerate(entries):
        where = f"{source} faculty[{index}]"

        if not isinstance(entry, dict):
            raise ConfigError(f"{where} must be an object with a 'github' property")

        faculty.append(
            Faculty(
                github=_require_string(entry, "github", where),
                name=_optional_string(entry, "name", where),
            )
        )

    return tuple(faculty)


def parse_course_config(data: Any, source: str) -> CourseConfig:
    """Build a :class:`CourseConfig` from already-loaded JSON.

    Unrecognised properties are ignored, so a file still carrying the
    ``course-org`` and ``branch-pattern`` of an earlier design does not fail.
    """
    if not isinstance(data, dict):
        raise ConfigError(f"{source} must contain a JSON object")

    return CourseConfig(faculty=parse_faculty(data.get("faculty"), source))
