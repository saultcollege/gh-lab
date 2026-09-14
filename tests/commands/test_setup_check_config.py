"""Tests for parsing the lab and course configuration files."""

import pytest

from gh_lab.commands.setup_check.config import (
    DEFAULT_BRANCH_PATTERN,
    ConfigError,
    parse_course_config,
    parse_lab_config,
)

SOURCE = "course-config.json"

LAB_CONFIG = {
    "repo-name": "csd110-lab-1",
    "template-repo": "https://github.com/saultcollege-csd110/lab-1-template",
    "course-config-url": "https://saultcollege-csd110.github.io/course-config.json",
}

COURSE_CONFIG = {
    "course-org": "saultcollege-csd110",
    "faculty": [{"name": "Bob Bob", "github": "bobber24"}],
}


# --- .lab/config.json ------------------------------------------------------


def test_parses_a_lab_config():
    config = parse_lab_config(LAB_CONFIG)

    assert config.repo_name == "csd110-lab-1"
    assert config.course_config_url.endswith("course-config.json")


def test_lab_is_optional_and_absent_in_a_multi_lab_repository():
    assert parse_lab_config(LAB_CONFIG).lab is None


def test_lab_is_read_when_a_template_serves_a_single_lab():
    assert parse_lab_config({**LAB_CONFIG, "lab": "1"}).lab == "1"


@pytest.mark.parametrize("missing", ["repo-name", "template-repo", "course-config-url"])
def test_a_missing_required_field_names_itself(missing):
    data = {key: value for key, value in LAB_CONFIG.items() if key != missing}

    with pytest.raises(ConfigError, match=missing):
        parse_lab_config(data)


def test_lab_config_must_be_an_object():
    with pytest.raises(ConfigError, match="JSON object"):
        parse_lab_config(["not", "an", "object"])


# --- course-config.json ----------------------------------------------------


def test_parses_a_course_config():
    config = parse_course_config(COURSE_CONFIG, SOURCE)

    assert config.course_org == "saultcollege-csd110"
    assert config.branch_pattern == DEFAULT_BRANCH_PATTERN


def test_faculty_entries_are_objects_with_a_github_property():
    """Faculty are objects; only the github handle identifies a collaborator."""
    config = parse_course_config(COURSE_CONFIG, SOURCE)

    (person,) = config.faculty
    assert person.github == "bobber24"
    assert person.name == "Bob Bob"
    assert person.display == "Bob Bob (@bobber24)"


def test_faculty_name_is_optional():
    data = {**COURSE_CONFIG, "faculty": [{"github": "alice99"}]}

    (person,) = parse_course_config(data, SOURCE).faculty
    assert person.name is None
    assert person.display == "@alice99"


def test_a_faculty_entry_without_github_names_its_position():
    """The person fixing this file is the faculty member who wrote it."""
    data = {**COURSE_CONFIG, "faculty": [{"github": "ok"}, {"name": "No Handle"}]}

    with pytest.raises(ConfigError, match=r"faculty\[1\].*github"):
        parse_course_config(data, SOURCE)


def test_a_faculty_entry_that_is_a_bare_string_is_rejected():
    data = {**COURSE_CONFIG, "faculty": ["bobber24"]}

    with pytest.raises(ConfigError, match=r"faculty\[0\]"):
        parse_course_config(data, SOURCE)


def test_faculty_may_be_empty():
    data = {**COURSE_CONFIG, "faculty": []}

    assert parse_course_config(data, SOURCE).faculty == ()


def test_a_missing_faculty_array_is_an_error():
    data = {key: value for key, value in COURSE_CONFIG.items() if key != "faculty"}

    with pytest.raises(ConfigError, match="faculty"):
        parse_course_config(data, SOURCE)


def test_branch_pattern_overrides_the_default():
    data = {**COURSE_CONFIG, "branch-pattern": "week-{lab}"}

    assert parse_course_config(data, SOURCE).branch_pattern == "week-{lab}"
