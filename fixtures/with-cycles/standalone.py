"""Standalone module - not part of the cycle.

This module has no dependencies and nothing depends on it.
Used to test that cycle detection only flags the actual cycle.
"""


def standalone_function() -> str:
    return "I am independent"


class StandaloneClass:
    """A class with no external dependencies."""

    def __init__(self, value: str):
        self.value = value

    def get_value(self) -> str:
        return self.value
