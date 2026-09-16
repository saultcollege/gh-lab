"""Core logic for the ``admin invites`` commands.

Nothing lives here yet. The operations themselves — building the roster to
invite from a course configuration, and deciding what to do with a set of
pending repository invitations — arrive with the commands that need them.

The contract is the one the rest of the project follows: this module takes plain
data and returns structured results, must not import argparse or the shell
layer, and holds the wording of anything reported to the user so that
``shell.py`` decides only how it is laid out.
"""
