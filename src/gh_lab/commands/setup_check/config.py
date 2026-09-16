"""The lab configuration read by ``setup-check``.

Two files describe a lab:

* ``.lab/config.json`` in the root of the student's repository, written by the
  lab template and unique to it — parsed here;
* a course configuration document, held in a private repository owned by the
  course organization and shared by every lab in the course — parsed by
  :mod:`gh_lab.course_config`, because more than one command reads it.

Everything a check needs beyond the faculty list is either stated in
``.lab/config.json`` or derived from it, because a workflow running in a
student's repository cannot read a private repository in the course
organization. Keeping the rest local means ``setup-check`` behaves the same in a
devcontainer and in GitHub Actions.

Everything here is pure: parsing takes already-loaded data and returns
structured values, so it can be tested without a repository or the network.
"""

from dataclasses import dataclass
from typing import Any

from gh_lab.course_config import (
    ConfigError,
    CourseConfigRef,
    normalise_repo_ref,
    optional_string,
    parse_course_config_ref,
    require_string,
)

LAB_CONFIG_PATH = ".lab/config.json"

DEFAULT_BRANCH_PATTERN = "lab-{lab}"


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


def parse_lab_config(data: Any, source: str = LAB_CONFIG_PATH) -> LabConfig:
    """Build a :class:`LabConfig` from already-loaded JSON."""
    if not isinstance(data, dict):
        raise ConfigError(f"{source} must contain a JSON object")

    return LabConfig(
        repo_name=require_string(data, "repo-name", source),
        template_repo=require_string(data, "template-repo", source),
        course_config=parse_course_config_ref(
            require_string(data, "course-config", source), source
        ),
        branch_pattern=optional_string(data, "branch-pattern", source)
        or DEFAULT_BRANCH_PATTERN,
        lab=optional_string(data, "lab", source),
    )
