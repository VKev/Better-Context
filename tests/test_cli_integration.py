"""Integration tests for CLI commands."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
from better_context.cli import main


@pytest.fixture
def test_project(tmp_path):
    """Create a temporary test project."""
    project_dir = tmp_path / "cli_test_project"
    project_dir.mkdir()
    
    # Create pyproject.toml
    (project_dir / "pyproject.toml").write_text("""
[project]
name = "cli-test"
version = "0.1.0"
""", encoding="utf-8")

    # Create src structure
    src = project_dir / "src"
    src.mkdir()
    (src / "main.py").write_text("print('hello')", encoding="utf-8")
    
    return project_dir


def run_cli(args: list[str]) -> tuple[int, str, str]:
    """Run CLI with arguments and capture output."""
    # Mock sys.argv
    with patch.object(sys, "argv", ["better-context"] + args):
        # Capture stdout/stderr
        from io import StringIO
        stdout = StringIO()
        stderr = StringIO()
        
        with patch.object(sys, "stdout", stdout), patch.object(sys, "stderr", stderr):
            try:
                exit_code = main()
            except SystemExit as e:
                exit_code = e.code
                
        return exit_code, stdout.getvalue(), stderr.getvalue()


class TestCLIPrimitives:
    """Test primitive CLI commands."""
    
    def test_overview_json(self, test_project):
        exit_code, out, err = run_cli(["--root", str(test_project), "overview", "--format", "json"])
        
        assert exit_code == 0
        data = json.loads(out)
        assert data["project_name"] == "cli-test"
        assert data["primary_language"] == "python"
        
    def test_tree_json(self, test_project):
        exit_code, out, err = run_cli(["--root", str(test_project), "tree", "--format", "json"])
        
        assert exit_code == 0
        data = json.loads(out)
        assert data["root"] == str(test_project)
        # Verify structure
        paths = [d["path"] for d in data["directories"]]
        assert "src" in paths
        
    def test_file_json(self, test_project):
        exit_code, out, err = run_cli(["--root", str(test_project), "file", "src/main.py", "--format", "json"])
        
        assert exit_code == 0
        data = json.loads(out)
        # Allow either relative or absolute path in output, check end
        assert data["path"].endswith("src/main.py")
        assert data["language"] == "python"
        
    def test_scripts_json(self, test_project):
        exit_code, out, err = run_cli(["--root", str(test_project), "scripts", "--format", "json"])
        
        assert exit_code == 0
        data = json.loads(out)
        # We didn't add scripts, so list might be empty
        assert isinstance(data["scripts"], list)
        
    def test_entries_json(self, test_project):
        exit_code, out, err = run_cli(["--root", str(test_project), "entries", "--format", "json"])
        
        assert exit_code == 0
        data = json.loads(out)
        # Should detect src/main.py as script
        entries = [e["path"] for e in data["entry_points"]]
        assert "src/main.py" in entries
        
    def test_deps_no_graph(self, test_project):
        # deps command fails without graph (scan)
        exit_code, out, err = run_cli(["--root", str(test_project), "deps", "src/main.py"])
        
        assert exit_code == 1
        assert "No dependency graph available" in err

    def test_overview_markdown(self, test_project):
        exit_code, out, err = run_cli(["--root", str(test_project), "overview", "--format", "markdown"])
        
        assert exit_code == 0
        assert "# Project Overview" in out
        assert "- **Project Name**: cli-test" in out
        
    def test_tree_markdown(self, test_project):
        exit_code, out, err = run_cli(["--root", str(test_project), "tree", "--format", "markdown"])
        
        assert exit_code == 0
        assert "## Directory Structure" in out
        assert "| Directory | Files |" in out

