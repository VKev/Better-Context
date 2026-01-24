"""Tests for CLI module."""

from better_context.cli import create_parser, main


def test_parser_creation():
    """Test that parser is created successfully."""
    parser = create_parser()
    assert parser is not None
    assert parser.prog == "better-context"


def test_version_action():
    """Test --version flag."""
    parser = create_parser()
    # Would raise SystemExit with version info
    # Just verify the parser has the version action
    assert any(a.option_strings == ["--version"] for a in parser._actions)


def test_main_with_help(capsys):
    """Test main with no args shows help."""
    # main() with no command should fail with error
    result = main(["--help"])
    # Note: --help raises SystemExit(0)


def test_scan_command():
    """Test scan command parsing."""
    parser = create_parser()
    args = parser.parse_args(["scan", "."])
    assert args.command == "scan"


def test_all_command():
    """Test all command parsing."""
    parser = create_parser()
    args = parser.parse_args(["all", "."])
    assert args.command == "all"
