"""Error handling and partial results for better-context.

This module defines a consistent error handling strategy that allows the tool
to continue and produce useful output even when some files fail.

Key principles:
- One broken file shouldn't crash entire analysis
- Partial results are better than no results
- Users need to know what failed and why
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


# Encoding fallback order
ENCODING_FALLBACKS = ["utf-8", "latin-1", "cp1252"]


@dataclass
class FileError:
    """An error encountered while processing a file."""

    path: str  # File path (relative to root)
    error_type: str  # 'permission', 'encoding', 'parse', 'resolution'
    message: str  # Human-readable error message
    line: int | None = None  # Line number if applicable
    recoverable: bool = True  # Can we continue without this file?

    def __str__(self) -> str:
        loc = f":{self.line}" if self.line else ""
        return f"{self.path}{loc}: [{self.error_type}] {self.message}"


@dataclass
class AnalysisWarning:
    """A warning encountered during analysis (non-fatal)."""

    category: str  # 'config', 'pattern', 'deprecated', 'performance'
    message: str  # Warning message
    file: str | None = None  # Related file if any
    suggestion: str | None = None  # How to fix

    def __str__(self) -> str:
        prefix = f"{self.file}: " if self.file else ""
        suffix = f" ({self.suggestion})" if self.suggestion else ""
        return f"{prefix}[{self.category}] {self.message}{suffix}"


@dataclass
class AnalysisErrors:
    """Collection of errors and warnings from analysis."""

    file_errors: list[FileError] = field(default_factory=list)
    warnings: list[AnalysisWarning] = field(default_factory=list)

    def add_error(
        self,
        path: str,
        error_type: str,
        message: str,
        line: int | None = None,
        recoverable: bool = True,
    ) -> None:
        """Add a file error to the collection."""
        self.file_errors.append(
            FileError(
                path=path,
                error_type=error_type,
                message=message,
                line=line,
                recoverable=recoverable,
            )
        )

    def add_warning(
        self,
        category: str,
        message: str,
        file: str | None = None,
        suggestion: str | None = None,
    ) -> None:
        """Add a warning to the collection."""
        self.warnings.append(
            AnalysisWarning(
                category=category,
                message=message,
                file=file,
                suggestion=suggestion,
            )
        )

    def has_critical_errors(self) -> bool:
        """Check if any non-recoverable errors occurred."""
        return any(not e.recoverable for e in self.file_errors)

    def has_errors(self) -> bool:
        """Check if any errors occurred."""
        return len(self.file_errors) > 0

    def has_warnings(self) -> bool:
        """Check if any warnings occurred."""
        return len(self.warnings) > 0

    def error_count(self) -> int:
        """Get total error count."""
        return len(self.file_errors)

    def warning_count(self) -> int:
        """Get total warning count."""
        return len(self.warnings)

    def errors_by_type(self) -> dict[str, list[FileError]]:
        """Group errors by type."""
        result: dict[str, list[FileError]] = {}
        for err in self.file_errors:
            if err.error_type not in result:
                result[err.error_type] = []
            result[err.error_type].append(err)
        return result

    def summary(self) -> str:
        """Generate a summary string."""
        parts = []
        if self.file_errors:
            by_type = self.errors_by_type()
            type_counts = [f"{len(v)} {k}" for k, v in by_type.items()]
            parts.append(f"Errors: {', '.join(type_counts)}")
        if self.warnings:
            parts.append(f"Warnings: {len(self.warnings)}")
        return "; ".join(parts) if parts else "No errors or warnings"


def read_file_with_fallback(path: Path) -> tuple[str, str | None, str | None]:
    """Read file with encoding fallback.

    Tries multiple encodings before giving up.

    Args:
        path: Path to the file

    Returns:
        Tuple of (content, encoding_used, error_message)
        - content: File content (may use replacement chars if all encodings fail)
        - encoding_used: The encoding that worked, or 'utf-8-replace' if all failed
        - error_message: None if successful, error message if fallback was used
    """
    for encoding in ENCODING_FALLBACKS:
        try:
            content = path.read_text(encoding=encoding)
            return content, encoding, None
        except UnicodeDecodeError:
            continue
        except OSError as e:
            return "", None, str(e)

    # Last resort: read as bytes with replacement
    try:
        content = path.read_bytes().decode("utf-8", errors="replace")
        return content, "utf-8-replace", "All encodings failed, using replacement characters"
    except OSError as e:
        return "", None, str(e)


def format_error_report(errors: AnalysisErrors, verbose: bool = False) -> str:
    """Format errors and warnings for display.

    Args:
        errors: The error collection
        verbose: Whether to show all errors or truncate

    Returns:
        Formatted error report string
    """
    lines = []

    if errors.file_errors:
        lines.append(f"⚠️  {len(errors.file_errors)} file(s) had errors:")
        lines.append("")

        by_type = errors.errors_by_type()
        for error_type, type_errors in by_type.items():
            lines.append(f"  {error_type.upper()} ({len(type_errors)}):")
            display_errors = type_errors if verbose else type_errors[:3]
            for err in display_errors:
                loc = f":{err.line}" if err.line else ""
                lines.append(f"    - {err.path}{loc}: {err.message}")
            if not verbose and len(type_errors) > 3:
                lines.append(f"    ... and {len(type_errors) - 3} more")
            lines.append("")

    if errors.warnings:
        lines.append(f"📝 {len(errors.warnings)} warning(s):")
        lines.append("")
        display_warnings = errors.warnings if verbose else errors.warnings[:5]
        for warn in display_warnings:
            prefix = f"  {warn.file}: " if warn.file else "  "
            lines.append(f"{prefix}[{warn.category}] {warn.message}")
            if warn.suggestion:
                lines.append(f"    → {warn.suggestion}")
        if not verbose and len(errors.warnings) > 5:
            lines.append(f"  ... and {len(errors.warnings) - 5} more")

    return "\n".join(lines)


def get_exit_code(errors: AnalysisErrors) -> int:
    """Determine appropriate exit code based on errors.

    Args:
        errors: The error collection

    Returns:
        0 = clean, 1 = errors but continued, 2 = critical failure
    """
    if errors.has_critical_errors():
        return 2
    if errors.has_errors():
        return 1
    return 0


class BetterContextError(Exception):
    """Base exception for better-context errors."""

    pass


class ConfigurationError(BetterContextError):
    """Error in configuration (invalid .ctx.json, etc.)."""

    pass


class ManifestError(BetterContextError):
    """Error in manifest (invalid format, version mismatch, etc.)."""

    pass


class ParseError(BetterContextError):
    """Error parsing a source file."""

    def __init__(self, message: str, path: str | None = None, line: int | None = None):
        super().__init__(message)
        self.path = path
        self.line = line


class ResolutionError(BetterContextError):
    """Error resolving an import/dependency."""

    def __init__(self, message: str, source_path: str, target: str):
        super().__init__(message)
        self.source_path = source_path
        self.target = target
