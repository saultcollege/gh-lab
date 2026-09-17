"""Adapters isolating interactions with external tools and services.

Each module here is a thin wrapper that returns plain data or raises
:class:`AdapterError`. Decision-making belongs in the command layer, so that it
can be tested without git, the GitHub CLI, or the network.
"""


class AdapterError(Exception):
    """An external tool or service could not supply the requested information."""


class ToolNotFound(AdapterError):
    """The external tool itself is not installed or not on PATH.

    A subclass, so that handlers treating every adapter failure as a reason to
    skip a check keep working unchanged. A caller that needs to tell "the tool
    is missing" from "the tool said no" catches this instead of inspecting the
    message text.
    """
