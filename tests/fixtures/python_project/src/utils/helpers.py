"""Utility functions."""


def format_name(name: str) -> str:
    return f"Hello, {name}!"


def validate_input(value: str) -> bool:
    return bool(value and value.strip())
