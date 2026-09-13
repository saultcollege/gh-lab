"""gh-lab: a GitHub CLI extension for managing programming lab repositories."""

# The runtime source of truth for the version. When gh-lab is installed as a gh
# script extension the package is not installed into an environment, so
# importlib.metadata cannot find it; a literal here works from a plain checkout
# and from an installed wheel alike. A test asserts this matches the version in
# pyproject.toml.
__version__ = "0.1.0"

__all__ = ["__version__"]
