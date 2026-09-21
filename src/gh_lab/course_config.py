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

from collections.abc import Iterator
from dataclasses import dataclass, replace
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


def declared_string(data: dict[str, Any], key: str, source: str) -> str | None:
    """Read a property that must be stated but whose value may be unknown.

    Unlike :func:`optional_string`, the key itself is required: an absent key is
    an entry somebody has not finished writing, while ``null`` or an empty
    string is somebody saying the value is not known yet. Only whoever wrote the
    file can tell those apart, so the file has to say which it means.

    Returns:
        The value, or ``None`` where it is not known yet.
    """
    if key not in data:
        raise ConfigError(
            f"{source} is missing a {key!r} value. Use null if it is not known yet"
        )

    value = data[key]

    if value is None:
        return None

    if not isinstance(value, str):
        raise ConfigError(f"{source} has an invalid {key!r} value")

    return value.strip() or None


@dataclass(frozen=True)
class Person:
    """Someone named in the course configuration.

    Faculty and students are described the same way — a GitHub handle and,
    optionally, a real name. Which one someone is follows from the array they
    appear in, not from their entry.
    """

    github: str
    name: str | None = None

    @property
    def display(self) -> str:
        """A human-readable identification, e.g. ``Bob Bob (@bobber24)``."""
        return f"{self.name} (@{self.github})" if self.name else f"@{self.github}"


@dataclass(frozen=True)
class Unidentified:
    """Someone on a roster whose GitHub handle is not yet known.

    Not a :class:`Person`, because there is nothing to invite: everything that
    acts on a person acts on their handle. Where they sat in the array is what
    identifies them instead, and is what whoever fixes the file needs.

    Attributes:
        where: The array and position they were read from, ``students[3]``.
        name: Their real name, when the entry gave one.
    """

    where: str
    name: str | None = None

    @property
    def display(self) -> str:
        """A human-readable identification, e.g. ``Stu Dent (students[3])``."""
        return f"{self.name} ({self.where})" if self.name else self.where


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


# The course roster is split across two repositories: a public one holding the
# faculty, and a private one holding the students, named the same with this
# appended. Faculty are public information; an enrolled student's name and
# GitHub handle are not.
PRIVATE_REPO_SUFFIX = "-private"


def private_counterpart(reference: CourseConfigRef) -> CourseConfigRef:
    """Where the private roster for a public course configuration lives.

    Derived by convention rather than configured, so that one reference locates
    both files and no command has to be told two. Only the repository name
    changes: the same path in each is what lets several deliveries of a course
    (``26f.json``, ``26w.json``) sit side by side in both.
    """
    return replace(reference, repo=f"{reference.repo}{PRIVATE_REPO_SUFFIX}")


@dataclass(frozen=True)
class CourseConfig:
    """The contents of the public course configuration document.

    Faculty only. Students are named in the private roster beside it, which is
    read separately — see :func:`private_counterpart` and :func:`parse_roster`.
    """

    faculty: tuple[Person, ...]


@dataclass(frozen=True)
class Roster:
    """The contents of the private roster document.

    Both halves travel together because the parse is the only place that can
    tell them apart: an entry either gives a handle or says it has none yet.

    Attributes:
        students: Everyone whose handle is known, and who can be invited.
        unidentified: Everyone enrolled whose handle is not known yet.
    """

    students: tuple[Person, ...] = ()
    unidentified: tuple[Unidentified, ...] = ()


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


def _entries(
    entries: Any, source: str, key: str
) -> Iterator[tuple[str, str, dict[str, Any]]]:
    """Walk the ``key`` array of a course config, checking its shape.

    Yields each entry with the position it was read from, which is what errors
    and reports name: the person who has to fix the file is the faculty member
    who wrote it, and an entry naming nobody is identified by nothing else.

    The position comes in both spellings, because they are read in different
    places. ``students[3]`` alone identifies an entry in a report that has
    already named the file it came from; an error message has named nothing, so
    it carries the file too.
    """
    if not isinstance(entries, list):
        raise ConfigError(f"{source} is missing a {key!r} array")

    for index, entry in enumerate(entries):
        position = f"{key}[{index}]"
        where = f"{source} {position}"

        if not isinstance(entry, dict):
            raise ConfigError(f"{where} must be an object with a 'github' property")

        yield position, where, entry


def parse_people(entries: Any, source: str, key: str) -> tuple[Person, ...]:
    """Build a list of people from the ``key`` array of a course config.

    Each entry is an object and must give a ``github`` handle. Used for
    ``faculty``, where a missing handle is a check that cannot be made rather
    than an invitation that can wait; students are read by :func:`parse_roster`,
    which allows a handle that is not known yet.
    """
    return tuple(
        Person(
            github=require_string(entry, "github", where),
            name=optional_string(entry, "name", where),
        )
        for _, where, entry in _entries(entries, source, key)
    )


def parse_course_config(data: Any, source: str) -> CourseConfig:
    """Build a :class:`CourseConfig` from already-loaded JSON.

    ``faculty`` is required. ``students`` is refused rather than ignored: this
    is the public document, so an array of enrolled students in it is a course
    that has published its roster. Saying so is the only chance to catch that;
    the tool cannot unpublish the file.

    Other unrecognised properties are ignored, so a file still carrying the
    ``course-org`` and ``branch-pattern`` of an earlier design does not fail.
    """
    if not isinstance(data, dict):
        raise ConfigError(f"{source} must contain a JSON object")

    if data.get("students") is not None:
        raise ConfigError(
            f"{source} lists students, but it is the public course "
            f"configuration. Move them to the matching file in the "
            f"'{PRIVATE_REPO_SUFFIX}' repository beside it"
        )

    return CourseConfig(faculty=parse_people(data.get("faculty"), source, "faculty"))


def parse_roster(data: Any, source: str) -> Roster:
    """The enrolled students from a private roster document.

    A roster holds only ``students``; the faculty it belongs with are named in
    the public file, so ``faculty`` is neither required nor read here.

    An absent ``students`` is an empty roster rather than an error: a course
    may be configured before anyone has enrolled.

    Every entry must state a ``github`` property, but a ``null`` or empty one
    says the handle is not known yet, which is an ordinary state for a roster
    to be in at the start of a term. Those students are separated out as
    :class:`Unidentified` rather than rejected, so that one unfinished entry
    does not stop the rest of the course being invited.
    """
    if not isinstance(data, dict):
        raise ConfigError(f"{source} must contain a JSON object")

    students = data.get("students")

    if students is None:
        return Roster()

    known: list[Person] = []
    unidentified: list[Unidentified] = []

    for position, where, entry in _entries(students, source, "students"):
        github = declared_string(entry, "github", where)
        name = optional_string(entry, "name", where)

        if github is None:
            unidentified.append(Unidentified(where=position, name=name))
        else:
            known.append(Person(github=github, name=name))

    return Roster(students=tuple(known), unidentified=tuple(unidentified))
