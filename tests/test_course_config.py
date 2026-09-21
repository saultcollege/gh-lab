"""Tests for parsing the course configuration document."""

import pytest

from gh_lab.course_config import (
    ConfigError,
    CourseConfigRef,
    Person,
    Unidentified,
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


def test_a_roster_without_students_is_absent_rather_than_an_error():
    """A course may be configured before anyone has enrolled."""
    assert parse_roster({}, SOURCE).students == ()


def test_students_may_be_empty():
    assert parse_roster({"students": []}, SOURCE).students == ()


def test_parses_the_student_list():
    data = {"students": [{"name": "Stu Dent", "github": "student"}]}

    (person,) = parse_roster(data, SOURCE).students

    assert person.github == "student"
    assert person.display == "Stu Dent (@student)"


def test_student_name_is_optional():
    (person,) = parse_roster({"students": [{"github": "student"}]}, SOURCE).students

    assert person.name is None
    assert person.display == "@student"


def test_a_student_entry_without_a_github_property_names_its_position():
    """Absent is an unfinished entry, and says nothing about what was meant."""
    data = {"students": [{"github": "ok"}, {"name": "No Handle"}]}

    with pytest.raises(ConfigError, match=r"students\[1\].*github"):
        parse_roster(data, SOURCE)


def test_the_missing_github_message_says_how_to_state_an_unknown_handle():
    """The faculty member who meets this is the one who deleted the line."""
    with pytest.raises(ConfigError, match="null"):
        parse_roster({"students": [{"name": "No Handle"}]}, SOURCE)


@pytest.mark.parametrize("handle", [None, "", "   "])
def test_a_student_handle_that_is_not_known_yet_is_not_an_error(handle):
    """An enrolled student whose handle nobody has collected yet."""
    data = {"students": [{"name": "Stu Dent", "github": handle}]}

    roster = parse_roster(data, SOURCE)

    assert roster.students == ()
    assert roster.unidentified == (Unidentified(where="students[0]", name="Stu Dent"),)


def test_an_unidentified_student_is_named_by_its_position():
    """There may be no name either, and the position is what has to be edited."""
    data = {"students": [{"github": "ok"}, {"github": None}]}

    (student,) = parse_roster(data, SOURCE).unidentified

    assert student.name is None
    assert student.display == "students[1]"


def test_an_unidentified_student_with_a_name_is_named_by_both():
    data = {"students": [{"name": "Stu Dent", "github": None}]}

    (student,) = parse_roster(data, SOURCE).unidentified

    assert student.display == "Stu Dent (students[0])"


def test_students_with_and_without_a_handle_are_kept_apart():
    data = {
        "students": [
            {"github": "student"},
            {"name": "No Handle", "github": None},
            {"github": "other"},
        ]
    }

    roster = parse_roster(data, SOURCE)

    assert [person.github for person in roster.students] == ["student", "other"]
    assert [student.where for student in roster.unidentified] == ["students[1]"]


def test_a_student_handle_that_is_not_a_string_is_rejected():
    """Nothing about a number says the handle is not known yet."""
    with pytest.raises(ConfigError, match=r"students\[0\].*github"):
        parse_roster({"students": [{"github": 42}]}, SOURCE)


@pytest.mark.parametrize("handle", [None, "", "   "])
def test_a_faculty_entry_still_needs_a_handle(handle):
    """A faculty member with no handle is a check that cannot be made."""
    with pytest.raises(ConfigError, match=r"faculty\[0\].*github"):
        parse_course_config({"faculty": [{"github": handle}]}, SOURCE)


def test_a_student_entry_that_is_a_bare_string_is_rejected():
    with pytest.raises(ConfigError, match=r"students\[0\]"):
        parse_roster({"students": ["student"]}, SOURCE)


def test_a_students_property_that_is_not_an_array_is_rejected():
    """Absent is fine; present and the wrong shape is a mistake worth naming."""
    with pytest.raises(ConfigError, match="students"):
        parse_roster({"students": "student"}, SOURCE)


def test_faculty_and_students_come_from_different_files():
    faculty = parse_course_config({"faculty": [{"github": "prof"}]}, SOURCE).faculty
    students = parse_roster({"students": [{"github": "student"}]}, SOURCE).students

    assert [person.github for person in faculty] == ["prof"]
    assert [person.github for person in students] == ["student"]


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


def test_the_public_configuration_may_not_list_students():
    """Publishing the roster is the mistake this arrangement exists to avoid."""
    data = {"faculty": [], "students": [{"github": "student"}]}

    with pytest.raises(ConfigError, match="public course configuration"):
        parse_course_config(data, SOURCE)


# --- Parsing a private roster ------------------------------------------------


def test_a_roster_holds_students():
    assert parse_roster({"students": [{"github": "student"}]}, "roster").students == (
        Person(github="student"),
    )


def test_a_roster_need_not_name_any_faculty():
    """The faculty it belongs with are in the public file, not this one."""
    assert parse_roster({"students": []}, "roster").students == ()


def test_a_roster_ignores_faculty_it_does_carry():
    """The faculty it belongs with are named in the public file."""
    data = {"faculty": [{"github": "prof"}], "students": [{"github": "student"}]}

    assert parse_roster(data, "roster").students == (Person(github="student"),)


def test_a_roster_without_students_is_empty_rather_than_an_error():
    roster = parse_roster({}, "roster")

    assert roster.students == ()
    assert roster.unidentified == ()


def test_a_roster_must_be_an_object():
    with pytest.raises(ConfigError, match="must contain a JSON object"):
        parse_roster([], "roster")
