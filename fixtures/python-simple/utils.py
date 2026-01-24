"""Utility functions for the python-simple fixture.

This module has no internal dependencies - it's a leaf node.
"""


def format_name(name: str) -> str:
    """Format a name for display."""
    return name.strip().title()


def calculate_total(price: float, quantity: int) -> float:
    """Calculate total price."""
    return price * quantity


def validate_email(email: str) -> bool:
    """Simple email validation."""
    return "@" in email and "." in email
