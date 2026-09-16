"""Tests for parsing the course configuration document."""

import pytest

from gh_lab.course_config import (
    ConfigError,
    CourseConfigRef,
    normalise_repo_ref,
    parse_course_config,
    parse_course_config_ref,
)

SOURCE = "org/course-config/26f.json"

# Where a 'course-config' reference is read from. Deliberately not SOURCE, so
# that a test asserting on the word 'course-config' cannot pass on the name of
# the file alone.
REF_SOURCE = ".lab/config.json"

COURSE_CONFIG = {"faculty": [{"name": "Bob Bob", "github": "bobber24"}]}

TEMPLATE_URL = "https://github.com/saultcollege-csd110/lab-1-template"
TEMPLATE_REF = "saultcollege-csd110/lab-1-template"


# --- Repository reference normalisation ------------------------------------


@pytest.mark.parametrize(
    "value",
    [
        TEMPLATE_URL,
        TEMPLATE_URL + "/",
        TEMPLATE_URL + ".git",
        "saultcollege-csd110/lab-1-template",
        "SaultCollege-CSD110/Lab-1-Template",
        "git@github.com:saultcollege-csd110/lab-1-template.git",
        {"name": "lab-1-template", "owner": {"login": "saultcollege-csd110"}},
    ],
)
def test_normalise_repo_ref_accepts_every_form(value):
    assert normalise_repo_ref(value) == TEMPLATE_REF


@pytest.mark.parametrize("value", [None, "", "   ", "just-a-name", {}, 42])
def test_normalise_repo_ref_rejects_non_repositories(value):
    assert normalise_repo_ref(value) is None


# --- locating the course config --------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (
            "org/course-config/26f.json",
            CourseConfigRef("org", "course-config", "26f.json"),
        ),
        (
            "org/course-config/26f.json@main",
            CourseConfigRef("org", "course-config", "26f.json", "main"),
        ),
        (
            "org/course-config/courses/csd110/26f.json",
            CourseConfigRef("org", "course-config", "courses/csd110/26f.json"),
        ),
        (
            "https://github.com/org/course-config/blob/main/26f.json",
            CourseConfigRef("org", "course-config", "26f.json", "main"),
        ),
        (
            "https://github.com/org/course-config/raw/spring/sub/26f.json",
            CourseConfigRef("org", "course-config", "sub/26f.json", "spring"),
        ),
    ],
)
def test_every_accepted_spelling_resolves_the_same_way(value, expected):
    """Faculty are as likely to paste a browser link as type the short form."""
    assert parse_course_config_ref(value, REF_SOURCE) == expected


@pytest.mark.parametrize(
    "value",
    ["", "   ", "just-a-name", "org/course-config", "https://github.com/org/repo"],
)
def test_a_course_config_that_does_not_name_a_file_is_rejected(value):
    with pytest.raises(ConfigError, match="course-config"):
        parse_course_config_ref(value, REF_SOURCE)


def test_an_error_names_where_the_reference_came_from():
    """The source is whatever the caller read it from, not a fixed filename."""
    with pytest.raises(ConfigError, match="--config-file"):
        parse_course_config_ref("just-a-name", "--config-file")


def test_the_ref_suffix_is_split_from_the_right():
    """A path containing '@' must survive."""
    reference = parse_course_config_ref("org/repo/dir@odd/26f.json", REF_SOURCE)

    assert reference.path == "dir@odd/26f.json"
    assert reference.ref is None


# --- course configuration --------------------------------------------------


def test_parses_the_faculty_list():
    (person,) = parse_course_config(COURSE_CONFIG, SOURCE).faculty

    assert person.github == "bobber24"
    assert person.display == "Bob Bob (@bobber24)"


def test_faculty_name_is_optional():
    data = {"faculty": [{"github": "alice99"}]}

    (person,) = parse_course_config(data, SOURCE).faculty
    assert person.name is None
    assert person.display == "@alice99"


def test_a_faculty_entry_without_github_names_its_position():
    """The person fixing this file is the faculty member who wrote it."""
    data = {"faculty": [{"github": "ok"}, {"name": "No Handle"}]}

    with pytest.raises(ConfigError, match=r"faculty\[1\].*github"):
        parse_course_config(data, SOURCE)


def test_a_faculty_entry_that_is_a_bare_string_is_rejected():
    with pytest.raises(ConfigError, match=r"faculty\[0\]"):
        parse_course_config({"faculty": ["bobber24"]}, SOURCE)


def test_faculty_may_be_empty():
    assert parse_course_config({"faculty": []}, SOURCE).faculty == ()


def test_a_missing_faculty_array_is_an_error():
    with pytest.raises(ConfigError, match="faculty"):
        parse_course_config({}, SOURCE)


def test_course_config_must_be_an_object():
    with pytest.raises(ConfigError, match="JSON object"):
        parse_course_config(["not", "an", "object"], SOURCE)


def test_superseded_properties_are_ignored():
    """An older file carrying course-org or branch-pattern must not hard-fail."""
    data = {
        **COURSE_CONFIG,
        "course-org": "ignored",
        "branch-pattern": "ignored-{lab}",
    }

    assert len(parse_course_config(data, SOURCE).faculty) == 1
