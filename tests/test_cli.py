"""Tests for CLI module."""

from better_context.cli import create_parser, main


def test_parser_creation():
    """Test that parser is created successfully."""
    parser = create_parser()
    assert parser is not None
    assert parser.prog == "better-context-unity"


def test_version_action():
    """Test --version flag."""
    parser = create_parser()
    # Would raise SystemExit with version info
    # Just verify the parser has the version action
    assert any(a.option_strings == ["--version"] for a in parser._actions)


def test_main_with_help():
    """Test main with no args shows help."""
    assert main(["--help"]) == 0


def test_scan_command():
    """Test scan command parsing."""
    parser = create_parser()
    args = parser.parse_args(["scan", "."])
    assert args.command == "scan"


def test_agents_command():
    parser = create_parser()
    args = parser.parse_args(
        [
            "agents",
            "--dry-run",
            "--summary",
            "Assets/Scripts=Runtime scripts.",
            "--remove-summary",
            "Assets/Old",
        ]
    )
    assert args.command == "agents"
    assert args.dry_run is True
    assert args.summary == ["Assets/Scripts=Runtime scripts."]
    assert args.remove_summary == ["Assets/Old"]


    # test_all_command removed as command is deprecated/removed
    pass
