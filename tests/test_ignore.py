"""Tests for ignore module."""

from better_context.ignore import (
    should_ignore,
    fnmatch_extended,
    load_ignore_patterns,
    DEFAULT_IGNORES,
)


def test_default_ignores_present():
    """Test that default ignores are defined."""
    assert len(DEFAULT_IGNORES) > 0
    assert ".git/" in DEFAULT_IGNORES
    assert "node_modules/" in DEFAULT_IGNORES


def test_should_ignore_basic():
    """Test basic ignore matching."""
    patterns = [".git/", "*.pyc"]

    assert should_ignore(".git/config", patterns) is True
    assert should_ignore("src/__pycache__/module.pyc", patterns) is True
    assert should_ignore("src/main.py", patterns) is False


def test_should_ignore_negation():
    """Test negation patterns."""
    patterns = ["*.txt", "!important.txt"]

    assert should_ignore("notes.txt", patterns) is True
    assert should_ignore("important.txt", patterns) is False


def test_fnmatch_extended_directory():
    """Test directory pattern matching."""
    assert fnmatch_extended("node_modules/package/index.js", "node_modules/") is True
    assert fnmatch_extended("src/node_modules/x.js", "node_modules/") is True
    assert fnmatch_extended("src/main.py", "node_modules/") is False


def test_fnmatch_extended_glob():
    """Test ** glob patterns."""
    assert fnmatch_extended("src/lib/utils.py", "**/*.py") is True
    assert fnmatch_extended("main.py", "**/*.py") is True
    assert fnmatch_extended("src/lib/utils.js", "**/*.py") is False
