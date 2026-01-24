"""Module C in circular dependency.

A -> B -> C -> A (forms a cycle)
"""

from b import get_b_value


def get_c_value() -> str:
    return "C"


def c_depends_on_b() -> str:
    """C imports B, completing the cycle back to A."""
    return f"C uses {get_b_value()}"
