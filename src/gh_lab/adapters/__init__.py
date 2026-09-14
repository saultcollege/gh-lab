"""Adapters isolating interactions with external tools and services.

Each module here is a thin wrapper that returns plain data or raises
:class:`AdapterError`. Decision-making belongs in the command layer, so that it
can be tested without git, the GitHub CLI, or the network.
"""


class AdapterError(Exception):
    """An external tool or service could not supply the requested information."""
