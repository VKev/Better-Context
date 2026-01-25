"""Tests for context staleness detection."""

import json
import pytest
import tempfile
from pathlib import Path

from src.better_context.staleness import (
    STALENESS_FILE_NAME,
    StalenessInfo,
    StalenessResult,
    compute_source_hash,
    collect_current_hashes,
    check_staleness,
    save_staleness_info,
    load_staleness_info,
    get_staleness_footer,
    extract_source_hash_from_agents_md,
    format_staleness_report,
)


class TestStalenessInfo:
    """Tests for StalenessInfo dataclass."""

    def test_to_dict(self):
        info = StalenessInfo(
            source_hash="abc123def456",
            file_hashes={"a.py": "hash1", "b.py": "hash2"},
            generated_at="2026-01-24T10:30:00Z",
            file_count=2,
        )
        
        data = info.to_dict()
        
        assert data["source_hash"] == "abc123def456"
        assert data["file_hashes"]["a.py"] == "hash1"
        assert data["file_count"] == 2

    def test_from_dict(self):
        data = {
            "source_hash": "abc123",
            "file_hashes": {"test.py": "xyz789"},
            "generated_at": "2026-01-24T00:00:00Z",
            "file_count": 1,
        }
        
        info = StalenessInfo.from_dict(data)
        
        assert info.source_hash == "abc123"
        assert info.file_hashes["test.py"] == "xyz789"
        assert info.file_count == 1

    def test_from_dict_with_defaults(self):
        data = {}
        
        info = StalenessInfo.from_dict(data)
        
        assert info.source_hash == ""
        assert info.file_hashes == {}
        assert info.file_count == 0


class TestStalenessResult:
    """Tests for StalenessResult dataclass."""

    def test_total_changes(self):
        result = StalenessResult(
            is_stale=True,
            source_hash="new",
            previous_hash="old",
            changed=["a.py", "b.py"],
            added=["c.py"],
            removed=["d.py", "e.py", "f.py"],
        )
        
        assert result.total_changes == 6

    def test_summary_fresh(self):
        result = StalenessResult(
            is_stale=False,
            source_hash="abc123def456",
            previous_hash="abc123def456",
        )
        
        assert "up-to-date" in result.summary
        assert "abc123def456"[:12] in result.summary

    def test_summary_stale(self):
        result = StalenessResult(
            is_stale=True,
            source_hash="new",
            previous_hash="old",
            changed=["a.py"],
            added=["b.py", "c.py"],
        )
        
        assert "STALE" in result.summary
        assert "1 modified" in result.summary
        assert "2 added" in result.summary


class TestComputeSourceHash:
    """Tests for compute_source_hash function."""

    def test_deterministic(self):
        hashes = {"a.py": "hash1", "b.py": "hash2"}
        
        result1 = compute_source_hash(hashes)
        result2 = compute_source_hash(hashes)
        
        assert result1 == result2
        assert len(result1) == 16

    def test_order_independent(self):
        """Hash should be same regardless of dict order."""
        hashes1 = {"a.py": "hash1", "b.py": "hash2"}
        hashes2 = {"b.py": "hash2", "a.py": "hash1"}
        
        result1 = compute_source_hash(hashes1)
        result2 = compute_source_hash(hashes2)
        
        assert result1 == result2

    def test_different_content_different_hash(self):
        hashes1 = {"a.py": "hash1"}
        hashes2 = {"a.py": "hash2"}
        
        result1 = compute_source_hash(hashes1)
        result2 = compute_source_hash(hashes2)
        
        assert result1 != result2

    def test_empty_hashes(self):
        result = compute_source_hash({})
        
        assert result == "0" * 16


class TestSaveAndLoadStalenessInfo:
    """Tests for save_staleness_info and load_staleness_info."""

    @pytest.fixture
    def temp_project(self):
        """Create a temporary project directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    def test_save_and_load(self, temp_project):
        file_hashes = {"src/main.py": "abc123", "src/utils.py": "def456"}
        generated_at = "2026-01-24T10:30:00Z"
        
        save_staleness_info(temp_project, file_hashes, generated_at)
        
        info = load_staleness_info(temp_project)
        
        assert info is not None
        assert info.file_hashes == file_hashes
        assert info.generated_at == generated_at
        assert info.file_count == 2

    def test_load_nonexistent(self, temp_project):
        info = load_staleness_info(temp_project)
        
        assert info is None

    def test_load_corrupted(self, temp_project):
        staleness_path = temp_project / ".better-context" / STALENESS_FILE_NAME
        staleness_path.parent.mkdir(parents=True)
        staleness_path.write_text("{ invalid json")
        
        info = load_staleness_info(temp_project)
        
        assert info is None

    def test_custom_output_dir(self, temp_project):
        file_hashes = {"test.py": "hash123"}
        
        save_staleness_info(
            temp_project,
            file_hashes,
            "2026-01-24T00:00:00Z",
            output_dir="custom-output",
        )
        
        info = load_staleness_info(temp_project, output_dir="custom-output")
        
        assert info is not None
        assert info.file_hashes == file_hashes


class TestCheckStaleness:
    """Tests for check_staleness function."""

    @pytest.fixture
    def project_with_files(self):
        """Create a project with source files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            
            # Create source files
            src_dir = root / "src"
            src_dir.mkdir()
            (src_dir / "main.py").write_text("def main(): pass")
            (src_dir / "utils.py").write_text("def helper(): pass")
            
            yield root

    def test_no_previous_info(self, project_with_files):
        """When no staleness info exists, everything is 'added'."""
        result = check_staleness(project_with_files)
        
        assert result.is_stale is True
        assert len(result.added) > 0
        assert result.previous_hash == ""

    def test_unchanged_files(self, project_with_files):
        """When files haven't changed, result is fresh."""
        # First, generate staleness info
        file_hashes = {
            "src/main.py": "",
            "src/utils.py": "",
        }
        
        # Collect actual hashes
        from src.better_context.staleness import collect_current_hashes
        file_hashes = collect_current_hashes(project_with_files)
        
        save_staleness_info(
            project_with_files,
            file_hashes,
            "2026-01-24T00:00:00Z",
        )
        
        # Check staleness
        result = check_staleness(project_with_files)
        
        assert result.is_stale is False
        assert result.changed == []
        assert result.added == []
        assert result.removed == []

    def test_modified_file(self, project_with_files):
        """When a file is modified, it should be in changed list."""
        # Collect and save initial hashes
        file_hashes = collect_current_hashes(project_with_files)
        save_staleness_info(
            project_with_files,
            file_hashes,
            "2026-01-24T00:00:00Z",
        )
        
        # Modify a file
        (project_with_files / "src" / "main.py").write_text("def main(): return 42")
        
        # Check staleness
        result = check_staleness(project_with_files)
        
        assert result.is_stale is True
        assert "src/main.py" in result.changed

    def test_added_file(self, project_with_files):
        """When a file is added, it should be in added list."""
        # Collect and save initial hashes
        file_hashes = collect_current_hashes(project_with_files)
        save_staleness_info(
            project_with_files,
            file_hashes,
            "2026-01-24T00:00:00Z",
        )
        
        # Add a new file
        (project_with_files / "src" / "new_file.py").write_text("# new file")
        
        # Check staleness
        result = check_staleness(project_with_files)
        
        assert result.is_stale is True
        assert "src/new_file.py" in result.added

    def test_removed_file(self, project_with_files):
        """When a file is removed, it should be in removed list."""
        # Collect and save initial hashes
        file_hashes = collect_current_hashes(project_with_files)
        save_staleness_info(
            project_with_files,
            file_hashes,
            "2026-01-24T00:00:00Z",
        )
        
        # Remove a file
        (project_with_files / "src" / "utils.py").unlink()
        
        # Check staleness
        result = check_staleness(project_with_files)
        
        assert result.is_stale is True
        assert "src/utils.py" in result.removed


class TestGetStalenessFooter:
    """Tests for get_staleness_footer function."""

    def test_contains_hash(self):
        footer = get_staleness_footer("abc123def456", "2026-01-24T10:30:00Z")
        
        assert "abc123def456" in footer
        assert "2026-01-24T10:30:00Z" in footer
        assert "better-context verify" in footer


class TestExtractSourceHashFromAgentsMd:
    """Tests for extract_source_hash_from_agents_md function."""

    @pytest.fixture
    def temp_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    def test_extract_hash(self, temp_dir):
        agents_md = temp_dir / "AGENTS.md"
        agents_md.write_text("""# Project

Some content here.

---
*Generated by better-context at 2026-01-24T10:30:00Z*
*Source hash: abc123def456*
*Verify: `better-context verify`*
""")
        
        result = extract_source_hash_from_agents_md(agents_md)
        
        assert result == "abc123def456"

    def test_no_hash(self, temp_dir):
        agents_md = temp_dir / "AGENTS.md"
        agents_md.write_text("# Project\n\nNo hash here.")
        
        result = extract_source_hash_from_agents_md(agents_md)
        
        assert result is None

    def test_file_not_exists(self, temp_dir):
        agents_md = temp_dir / "AGENTS.md"
        
        result = extract_source_hash_from_agents_md(agents_md)
        
        assert result is None


class TestFormatStalenessReport:
    """Tests for format_staleness_report function."""

    def test_fresh_report(self):
        result = StalenessResult(
            is_stale=False,
            source_hash="abc123def456",
            previous_hash="abc123def456",
        )
        
        report = format_staleness_report(result)
        
        assert "✓" in report
        assert "up-to-date" in report

    def test_stale_report(self):
        result = StalenessResult(
            is_stale=True,
            source_hash="new",
            previous_hash="old",
            changed=["a.py"],
            added=["b.py"],
            removed=["c.py"],
        )
        
        report = format_staleness_report(result)
        
        assert "⚠" in report
        assert "STALE" in report
        assert "better-context all" in report

    def test_verbose_report(self):
        result = StalenessResult(
            is_stale=True,
            source_hash="new",
            previous_hash="old",
            changed=["src/main.py", "src/utils.py"],
            added=["src/new.py"],
        )
        
        report = format_staleness_report(result, verbose=True)
        
        assert "Modified files:" in report
        assert "src/main.py" in report
        assert "Added files:" in report
        assert "src/new.py" in report
