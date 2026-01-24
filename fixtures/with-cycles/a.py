"""Module A in circular dependency.

A -> B -> C -> A (forms a cycle)
"""

from c import get_c_value


def get_a_value() -> str:
    return "A"


def a_depends_on_c() -> str:
    """This creates the cycle: A imports C."""
    return f"A uses {get_c_value()}"
