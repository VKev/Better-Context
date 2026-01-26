"""Tests for ignore module."""

from pathlib import Path

from better_context.ignore import (
    should_ignore,
    _match_pattern,
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


def test_match_pattern_directory():
    """Test directory pattern matching."""
    assert _match_pattern("node_modules/package/index.js", "node_modules/") is True
    assert _match_pattern("src/node_modules/x.js", "node_modules/") is True
    assert _match_pattern("src/main.py", "node_modules/") is False


def test_match_pattern_glob():
    """Test ** glob patterns."""
    assert _match_pattern("src/lib/utils.py", "**/*.py") is True
    assert _match_pattern("main.py", "**/*.py") is True
    assert _match_pattern("src/lib/utils.js", "**/*.py") is False


def test_ctxignore_overrides_fixture_gitignore(tmp_path: Path):
    """Fixture .ctxignore should override broader ignore patterns."""
    root = tmp_path / "project"
    root.mkdir()
    (root / "uv.lock").write_text("lockfile", encoding="utf-8")
    (root / "other.lock").write_text("lockfile", encoding="utf-8")
    (root / ".ctxignore").write_text("*.lock\n!uv.lock\n", encoding="utf-8")

    patterns = load_ignore_patterns(root)

    assert should_ignore("other.lock", patterns) is True
    assert should_ignore("uv.lock", patterns) is False
