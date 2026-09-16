"""The course configuration document, shared by every command.

A course configuration is held in a repository owned by the course
organization and describes the course as a whole: who teaches it and, in time,
who is enrolled in it. It is shared by every lab in the course, and by more than
one command — ``setup-check`` reads the faculty list to check repository
access, and the invite commands read it to decide who to invite — so it lives
here rather than inside any one command package.

The lab-specific half of the configuration, ``.lab/config.json``, stays with
the command that owns it.

Everything here is pure: parsing takes already-loaded data and returns
structured values, so it can be tested without a repository or the network.
"""

from dataclasses import dataclass
from typing import Any

GITHUB_HOST = "github.com"


class ConfigError(Exception):
    """A configuration file is missing a required field or is malformed."""


def require_string(data: dict[str, Any], key: str, source: str) -> str:
    """Read a required string property, naming ``source`` if it is absent."""
    value = data.get(key)

    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"{source} is missing a {key!r} value")

    return value.strip()


def optional_string(data: dict[str, Any], key: str, source: str) -> str | None:
    """Read an optional string property, rejecting a present but empty one."""
    value = data.get(key)

    if value is None:
        return None

    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"{source} has an invalid {key!r} value")

    return value.strip()


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
class CourseConfig:
    """The contents of the course configuration document.

    Only the faculty list: a workflow running in a student's repository cannot
    read a private repository in the course organization, so everything
    ``setup-check`` needs about the lab itself is stated in ``.lab/config.json``
    instead.
    """

    faculty: tuple[Faculty, ...]


def parse_course_config_ref(value: str, source: str) -> CourseConfigRef:
    """Locate the course configuration from a reference to it.

    Three spellings are accepted, because faculty writing the template are as
    likely to paste a link from the browser as to type the short form::

        org/course-config/26f.json
        org/course-config/26f.json@main
        https://github.com/org/course-config/blob/main/26f.json

    Args:
        value: The reference to parse.
        source: What to name in an error message — the file the reference was
            read from, or the option it was given on.
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
                github=require_string(entry, "github", where),
                name=optional_string(entry, "name", where),
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
