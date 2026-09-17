"""Tests for parsing the course configuration document."""

import pytest

from gh_lab.course_config import (
    ConfigError,
    CourseConfigRef,
    Person,
    normalise_repo_ref,
    parse_course_config,
    parse_course_config_ref,
    parse_roster,
    private_counterpart,
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


# --- students --------------------------------------------------------------


def test_students_are_absent_by_default():
    """A course configuration predating the invite commands must still parse."""
    assert parse_course_config(COURSE_CONFIG, SOURCE).students == ()


def test_students_may_be_empty():
    data = {**COURSE_CONFIG, "students": []}

    assert parse_course_config(data, SOURCE).students == ()


def test_parses_the_student_list():
    data = {**COURSE_CONFIG, "students": [{"name": "Stu Dent", "github": "student"}]}

    (person,) = parse_course_config(data, SOURCE).students

    assert person.github == "student"
    assert person.display == "Stu Dent (@student)"


def test_student_name_is_optional():
    data = {**COURSE_CONFIG, "students": [{"github": "student"}]}

    (person,) = parse_course_config(data, SOURCE).students

    assert person.name is None
    assert person.display == "@student"


def test_a_student_entry_without_github_names_its_position():
    data = {**COURSE_CONFIG, "students": [{"github": "ok"}, {"name": "No Handle"}]}

    with pytest.raises(ConfigError, match=r"students\[1\].*github"):
        parse_course_config(data, SOURCE)


def test_a_student_entry_that_is_a_bare_string_is_rejected():
    data = {**COURSE_CONFIG, "students": ["student"]}

    with pytest.raises(ConfigError, match=r"students\[0\]"):
        parse_course_config(data, SOURCE)


def test_a_students_property_that_is_not_an_array_is_rejected():
    """Absent is fine; present and the wrong shape is a mistake worth naming."""
    data = {**COURSE_CONFIG, "students": "student"}

    with pytest.raises(ConfigError, match="students"):
        parse_course_config(data, SOURCE)


def test_faculty_and_students_are_kept_apart():
    data = {"faculty": [{"github": "prof"}], "students": [{"github": "student"}]}

    config = parse_course_config(data, SOURCE)

    assert [person.github for person in config.faculty] == ["prof"]
    assert [person.github for person in config.students] == ["student"]


# --- Where the private roster lives ------------------------------------------


def test_the_private_roster_sits_beside_the_public_configuration():
    reference = CourseConfigRef("an-org", "course-info", "config/26f.json")

    assert private_counterpart(reference) == CourseConfigRef(
        "an-org", "course-info-private", "config/26f.json"
    )


def test_deriving_the_roster_keeps_the_owner_path_and_ref():
    """The path is what lets several deliveries live in one repository."""
    reference = CourseConfigRef("an-org", "course-info", "config/26w.json", "main")
    derived = private_counterpart(reference)

    assert derived.owner == "an-org"
    assert derived.path == "config/26w.json"
    assert derived.ref == "main"


def test_a_reference_already_private_is_returned_unchanged():
    """Otherwise a single-file course is sent to course-info-private-private."""
    reference = CourseConfigRef("an-org", "course-info-private", "26f.json")

    assert private_counterpart(reference) is reference


# --- Parsing a private roster ------------------------------------------------


def test_a_roster_holds_students():
    assert parse_roster({"students": [{"github": "student"}]}, "roster") == (
        Person(github="student"),
    )


def test_a_roster_need_not_name_any_faculty():
    """The faculty it belongs with are in the public file, not this one."""
    assert parse_roster({"students": []}, "roster") == ()


def test_a_roster_ignores_faculty_it_does_carry():
    """So that a course can split an existing file by copying it."""
    data = {"faculty": [{"github": "prof"}], "students": [{"github": "student"}]}

    assert parse_roster(data, "roster") == (Person(github="student"),)


def test_a_roster_without_students_is_empty_rather_than_an_error():
    assert parse_roster({}, "roster") == ()


def test_a_roster_must_be_an_object():
    with pytest.raises(ConfigError, match="must contain a JSON object"):
        parse_roster([], "roster")
