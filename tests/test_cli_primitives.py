import subprocess
import json
import pytest
import sys
from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures"
PYTHON_PROJECT = FIXTURES / "python_project"

class TestCLI:
    """Integration tests for CLI commands."""

    def run_cli(self, *args, cwd=None):
        """Run better-context CLI and return output."""
        # Use python -m better_context.cli to ensure we use the local code
        cmd = [sys.executable, "-m", "better_context.cli", *args]
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            cwd=cwd or PYTHON_PROJECT
        )
        return result

    def test_overview_json_output(self):
        result = self.run_cli("overview")
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert "primary_language" in data
        assert data["primary_language"] == "python"

    def test_overview_human_format(self):
        result = self.run_cli("overview", "--format", "human")
        assert result.returncode == 0
        assert "Language: python" in result.stdout

    def test_tree_with_depth(self):
        result = self.run_cli("tree", "--depth", "1")
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert "directories" in data
        # Check depth (root + 1 level)
        # Verify structure logic later if needed

    def test_scripts_output(self):
        result = self.run_cli("scripts")
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert "golden_commands" in data

    def test_entries_output(self):
        result = self.run_cli("entries")
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert "entry_points" in data

    def test_file_with_path(self):
        result = self.run_cli("file", "src/main.py")
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert "chunks" in data
        assert data["path"].endswith("src/main.py")

    def test_file_not_found(self):
        result = self.run_cli("file", "nonexistent.py")
        assert result.returncode != 0
        assert "File not found" in result.stderr or "File not found" in result.stdout

    def test_deps_output(self):
        # Must run scan first to generate graph
        self.run_cli("scan")
        result = self.run_cli("deps", "src/main.py")
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert "dependencies" in data

    def test_timing_flag(self):
        result = self.run_cli("overview", "--timing")
        assert result.returncode == 0
        # Timing is printed to stderr
        assert "Time:" in result.stderr
        
        # Verify valid JSON in stdout
        data = json.loads(result.stdout)
        assert "primary_language" in data

    # Tests for deprecated commands (will fail until bd-309 is done)
    # def test_removed_agents_command(self):
    #     result = self.run_cli("agents")
    #     assert result.returncode != 0
    
    # def test_removed_all_command(self):
    #     result = self.run_cli("all")
    #     assert result.returncode != 0
