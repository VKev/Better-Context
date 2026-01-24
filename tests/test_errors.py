"""Tests for errors module."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from better_context.errors import (
    FileError,
    AnalysisWarning,
    AnalysisErrors,
    read_file_with_fallback,
    format_error_report,
    get_exit_code,
    BetterContextError,
    ConfigurationError,
    ManifestError,
    ParseError,
    ResolutionError,
)


class TestFileError:
    """Tests for FileError dataclass."""

    def test_file_error_basic(self):
        """Test basic file error creation."""
        err = FileError(
            path="src/main.py",
            error_type="parse",
            message="Syntax error",
        )
        
        assert err.path == "src/main.py"
        assert err.error_type == "parse"
        assert err.line is None
        assert err.recoverable is True

    def test_file_error_with_line(self):
        """Test file error with line number."""
        err = FileError(
            path="src/main.py",
            error_type="parse",
            message="Unexpected token",
            line=42,
        )
        
        assert err.line == 42
        assert "42" in str(err)

    def test_file_error_str(self):
        """Test string representation."""
        err = FileError(
            path="test.py",
            error_type="encoding",
            message="Invalid UTF-8",
            line=10,
        )
        
        s = str(err)
        assert "test.py" in s
        assert ":10" in s
        assert "encoding" in s
        assert "Invalid UTF-8" in s


class TestAnalysisWarning:
    """Tests for AnalysisWarning dataclass."""

    def test_warning_basic(self):
        """Test basic warning creation."""
        warn = AnalysisWarning(
            category="config",
            message="Unknown option 'foo'",
        )
        
        assert warn.category == "config"
        assert warn.file is None
        assert warn.suggestion is None

    def test_warning_with_file(self):
        """Test warning with file reference."""
        warn = AnalysisWarning(
            category="pattern",
            message="Invalid glob pattern",
            file=".ctxignore",
            suggestion="Use ** for recursive matching",
        )
        
        s = str(warn)
        assert ".ctxignore" in s
        assert "pattern" in s


class TestAnalysisErrors:
    """Tests for AnalysisErrors collection."""

    def test_empty_errors(self):
        """Test empty error collection."""
        errors = AnalysisErrors()
        
        assert not errors.has_errors()
        assert not errors.has_warnings()
        assert not errors.has_critical_errors()
        assert errors.error_count() == 0
        assert errors.warning_count() == 0

    def test_add_error(self):
        """Test adding errors."""
        errors = AnalysisErrors()
        errors.add_error("test.py", "parse", "Bad syntax")
        
        assert errors.has_errors()
        assert errors.error_count() == 1
        assert errors.file_errors[0].path == "test.py"

    def test_add_warning(self):
        """Test adding warnings."""
        errors = AnalysisErrors()
        errors.add_warning("config", "Deprecated option")
        
        assert errors.has_warnings()
        assert errors.warning_count() == 1

    def test_critical_errors(self):
        """Test detecting critical errors."""
        errors = AnalysisErrors()
        errors.add_error("test.py", "parse", "Bad syntax", recoverable=True)
        assert not errors.has_critical_errors()
        
        errors.add_error("critical.py", "system", "Out of memory", recoverable=False)
        assert errors.has_critical_errors()

    def test_errors_by_type(self):
        """Test grouping errors by type."""
        errors = AnalysisErrors()
        errors.add_error("a.py", "parse", "Error 1")
        errors.add_error("b.py", "parse", "Error 2")
        errors.add_error("c.py", "encoding", "Error 3")
        
        by_type = errors.errors_by_type()
        assert len(by_type["parse"]) == 2
        assert len(by_type["encoding"]) == 1

    def test_summary(self):
        """Test error summary."""
        errors = AnalysisErrors()
        assert "No errors" in errors.summary()
        
        errors.add_error("a.py", "parse", "Error")
        errors.add_warning("config", "Warning")
        
        summary = errors.summary()
        assert "parse" in summary
        assert "Warning" in summary


class TestReadFileWithFallback:
    """Tests for read_file_with_fallback function."""

    def test_read_utf8_file(self):
        """Test reading a UTF-8 file."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False, encoding="utf-8") as f:
            f.write("Hello, World!")
            path = Path(f.name)
        
        try:
            content, encoding, error = read_file_with_fallback(path)
            assert content == "Hello, World!"
            assert encoding == "utf-8"
            assert error is None
        finally:
            path.unlink()

    def test_read_latin1_file(self):
        """Test reading a Latin-1 file."""
        with tempfile.NamedTemporaryFile(mode="wb", suffix=".txt", delete=False) as f:
            # Write bytes that are valid Latin-1 but not UTF-8
            f.write(b"caf\xe9")  # café in Latin-1
            path = Path(f.name)
        
        try:
            content, encoding, error = read_file_with_fallback(path)
            assert "caf" in content
            assert encoding in ("latin-1", "utf-8-replace")
        finally:
            path.unlink()

    def test_read_nonexistent_file(self):
        """Test reading a file that doesn't exist."""
        path = Path("/nonexistent/file.txt")
        content, encoding, error = read_file_with_fallback(path)
        
        assert content == ""
        assert encoding is None
        assert error is not None


class TestFormatErrorReport:
    """Tests for format_error_report function."""

    def test_format_empty(self):
        """Test formatting empty errors."""
        errors = AnalysisErrors()
        report = format_error_report(errors)
        assert report == ""

    def test_format_with_errors(self):
        """Test formatting with errors."""
        errors = AnalysisErrors()
        errors.add_error("a.py", "parse", "Syntax error", line=10)
        errors.add_error("b.py", "parse", "Missing bracket")
        
        report = format_error_report(errors)
        assert "a.py" in report
        assert "b.py" in report
        assert "parse" in report.upper() or "PARSE" in report

    def test_format_with_warnings(self):
        """Test formatting with warnings."""
        errors = AnalysisErrors()
        errors.add_warning("config", "Unknown key", suggestion="Check spelling")
        
        report = format_error_report(errors)
        assert "warning" in report.lower()
        assert "config" in report
        assert "Check spelling" in report

    def test_format_truncation(self):
        """Test that non-verbose mode truncates."""
        errors = AnalysisErrors()
        for i in range(10):
            errors.add_error(f"file{i}.py", "parse", f"Error {i}")
        
        report = format_error_report(errors, verbose=False)
        # Should show some and indicate more exist
        assert "more" in report or "file0.py" in report


class TestGetExitCode:
    """Tests for get_exit_code function."""

    def test_exit_code_clean(self):
        """Test exit code for clean run."""
        errors = AnalysisErrors()
        assert get_exit_code(errors) == 0

    def test_exit_code_with_recoverable_errors(self):
        """Test exit code with recoverable errors."""
        errors = AnalysisErrors()
        errors.add_error("test.py", "parse", "Error", recoverable=True)
        assert get_exit_code(errors) == 1

    def test_exit_code_with_critical_errors(self):
        """Test exit code with critical errors."""
        errors = AnalysisErrors()
        errors.add_error("test.py", "system", "Fatal", recoverable=False)
        assert get_exit_code(errors) == 2


class TestExceptions:
    """Tests for custom exceptions."""

    def test_better_context_error(self):
        """Test base exception."""
        with pytest.raises(BetterContextError):
            raise BetterContextError("Test error")

    def test_configuration_error(self):
        """Test configuration exception."""
        with pytest.raises(ConfigurationError):
            raise ConfigurationError("Invalid config")

    def test_manifest_error(self):
        """Test manifest exception."""
        with pytest.raises(ManifestError):
            raise ManifestError("Invalid manifest")

    def test_parse_error(self):
        """Test parse exception with metadata."""
        err = ParseError("Syntax error", path="test.py", line=42)
        assert err.path == "test.py"
        assert err.line == 42

    def test_resolution_error(self):
        """Test resolution exception."""
        err = ResolutionError("Cannot find module", source_path="a.py", target="b")
        assert err.source_path == "a.py"
        assert err.target == "b"
