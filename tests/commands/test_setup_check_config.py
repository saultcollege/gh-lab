"""Tests for parsing the lab configuration file.

The course configuration document is shared by several commands and is tested
in ``tests/test_course_config.py``.
"""

import pytest

from gh_lab.commands.setup_check.config import (
    DEFAULT_BRANCH_PATTERN,
    parse_lab_config,
)
from gh_lab.course_config import ConfigError

LAB_CONFIG = {
    "repo-name": "csd110-lab-1",
    "template-repo": "https://github.com/saultcollege-csd110/lab-1-template",
    "course-config": "saultcollege-csd110/course-config/26f.json",
}


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


def test_course_org_is_derived_from_the_course_config_owner():
    """The course org is, by definition, whoever owns the course config."""
    assert parse_lab_config(LAB_CONFIG).course_org == "saultcollege-csd110"


def test_course_org_follows_the_course_config_to_another_owner():
    data = {**LAB_CONFIG, "course-config": "Some-Org/course-config/26f.json"}

    assert parse_lab_config(data).course_org == "Some-Org"
