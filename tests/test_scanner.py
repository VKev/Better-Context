"""Tests for scanner module."""

from pathlib import Path
from better_context.scanner import (
    is_binary_extension,
    is_text_file,
    can_process_file,
    BINARY_EXTENSIONS,
)


def test_binary_extensions_defined():
    """Test that binary extensions are defined."""
    assert len(BINARY_EXTENSIONS) > 0
    assert ".png" in BINARY_EXTENSIONS
    assert ".exe" in BINARY_EXTENSIONS


def test_is_binary_extension():
    """Test binary extension detection."""
    assert is_binary_extension(Path("image.png")) is True
    assert is_binary_extension(Path("document.pdf")) is True
    assert is_binary_extension(Path("source.py")) is False
    assert is_binary_extension(Path("script.js")) is False


def test_is_binary_extension_case_insensitive():
    """Test that extension check is case-insensitive."""
    assert is_binary_extension(Path("IMAGE.PNG")) is True
    assert is_binary_extension(Path("Source.PY")) is False
