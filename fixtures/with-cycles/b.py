"""Module B in circular dependency.

A -> B -> C -> A (forms a cycle)
"""

from a import get_a_value


def get_b_value() -> str:
    return "B"


def b_depends_on_a() -> str:
    """B imports A."""
    return f"B uses {get_a_value()}"
