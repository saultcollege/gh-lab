"""Tests for parsing the lab and course configuration files."""

import pytest

from gh_lab.commands.setup_check.config import (
    DEFAULT_BRANCH_PATTERN,
    ConfigError,
    CourseConfigRef,
    parse_course_config,
    parse_course_config_ref,
    parse_lab_config,
)

SOURCE = "org/course-config/26f.json"

LAB_CONFIG = {
    "repo-name": "csd110-lab-1",
    "template-repo": "https://github.com/saultcollege-csd110/lab-1-template",
    "course-config": "saultcollege-csd110/course-config/26f.json",
}

COURSE_CONFIG = {"faculty": [{"name": "Bob Bob", "github": "bobber24"}]}


# --- .lab/config.json ------------------------------------------------------


def test_parses_a_lab_config():
    config = parse_lab_config(LAB_CONFIG)

    assert config.repo_name == "csd110-lab-1"
    assert config.course_config.repo == "course-config"


def test_lab_is_optional_and_absent_in_a_multi_lab_repository():
    assert parse_lab_config(LAB_CONFIG).lab is None


def test_lab_is_read_when_a_template_serves_a_single_lab():
    assert parse_lab_config({**LAB_CONFIG, "lab": "1"}).lab == "1"


def test_branch_pattern_defaults():
    assert parse_lab_config(LAB_CONFIG).branch_pattern == DEFAULT_BRANCH_PATTERN


def test_branch_pattern_can_be_overridden():
    data = {**LAB_CONFIG, "branch-pattern": "week-{lab}"}

    assert parse_lab_config(data).branch_pattern == "week-{lab}"


@pytest.mark.parametrize("missing", ["repo-name", "template-repo", "course-config"])
def test_a_missing_required_field_names_itself(missing):
    data = {key: value for key, value in LAB_CONFIG.items() if key != missing}

    with pytest.raises(ConfigError, match=missing):
        parse_lab_config(data)


def test_lab_config_must_be_an_object():
    with pytest.raises(ConfigError, match="JSON object"):
        parse_lab_config(["not", "an", "object"])


# --- course-org is derived, not configured ---------------------------------


def test_course_org_is_derived_from_the_template_owner():
    """The course org is, by definition, whoever owns the lab template."""
    assert parse_lab_config(LAB_CONFIG).course_org == "saultcollege-csd110"


def test_course_org_is_derived_from_the_shorthand_template_form():
    data = {**LAB_CONFIG, "template-repo": "Some-Org/lab-1-template"}

    assert parse_lab_config(data).course_org == "some-org"


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
    assert parse_course_config_ref(value) == expected


@pytest.mark.parametrize(
    "value",
    ["", "   ", "just-a-name", "org/course-config", "https://github.com/org/repo"],
)
def test_a_course_config_that_does_not_name_a_file_is_rejected(value):
    with pytest.raises(ConfigError, match="course-config"):
        parse_course_config_ref(value)


def test_the_ref_suffix_is_split_from_the_right():
    """A path containing '@' must survive."""
    reference = parse_course_config_ref("org/repo/dir@odd/26f.json")

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


def test_superseded_properties_are_ignored():
    """An older file carrying course-org or branch-pattern must not hard-fail."""
    data = {
        **COURSE_CONFIG,
        "course-org": "ignored",
        "branch-pattern": "ignored-{lab}",
    }

    assert len(parse_course_config(data, SOURCE).faculty) == 1
