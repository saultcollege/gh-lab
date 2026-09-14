"""Configuration used by ``setup-check``.

Two files describe a lab:

* ``.lab/config.json`` in the root of the student's repository, written by the
  lab template and unique to it;
* a course configuration document, fetched from the URL that file names, shared
  by every lab in the course.

Everything here is pure: parsing takes already-loaded JSON and returns
structured data, so it can be tested without a repository or the network.
"""

from dataclasses import dataclass
from typing import Any

LAB_CONFIG_PATH = ".lab/config.json"

DEFAULT_BRANCH_PATTERN = "lab-{lab}"


class ConfigError(Exception):
    """A configuration file is missing a required field or is malformed."""


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
class LabConfig:
    """The contents of ``.lab/config.json``.

    Attributes:
        repo_name: The name the student's repository must have.
        template_repo: The template the repository should have been created from.
        course_config_url: Where to fetch the course configuration.
        lab: The lab this repository is for. Set by templates that serve a single
            lab; omitted when one repository is used for several labs, in which
            case the student names the lab on the command line.
    """

    repo_name: str
    template_repo: str
    course_config_url: str
    lab: str | None = None


@dataclass(frozen=True)
class CourseConfig:
    """The contents of the course configuration document."""

    course_org: str
    faculty: tuple[Faculty, ...]
    branch_pattern: str = DEFAULT_BRANCH_PATTERN


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


def parse_lab_config(data: Any, source: str = LAB_CONFIG_PATH) -> LabConfig:
    """Build a :class:`LabConfig` from already-loaded JSON."""
    if not isinstance(data, dict):
        raise ConfigError(f"{source} must contain a JSON object")

    return LabConfig(
        repo_name=_require_string(data, "repo-name", source),
        template_repo=_require_string(data, "template-repo", source),
        course_config_url=_require_string(data, "course-config-url", source),
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
    """Build a :class:`CourseConfig` from already-loaded JSON."""
    if not isinstance(data, dict):
        raise ConfigError(f"{source} must contain a JSON object")

    return CourseConfig(
        course_org=_require_string(data, "course-org", source),
        faculty=parse_faculty(data.get("faculty"), source),
        branch_pattern=_optional_string(data, "branch-pattern", source)
        or DEFAULT_BRANCH_PATTERN,
    )
