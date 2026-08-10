from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..chunker import parse_file
from ..languages import detect_language
from ..scanner import is_binary_extension, is_text_file
from ..roslyn import RoslynUnavailableError, analyze_csharp_project, discover_project_references
from .base import FileNotFoundPrimitiveError, ParseError, timed


@dataclass
class FileChunk:
    type: str
    name: str
    lines: tuple[int, int]

    def to_dict(self) -> dict[str, object]:
        return {
            "type": self.type,
            "name": self.name,
            "lines": list(self.lines),
        }


@dataclass
class FileInfoResult:
    path: str
    language: str | None
    size_bytes: int
    chunks: list[FileChunk]
    imports: list[dict[str, object]]
    exports: list[dict[str, object]]

    def to_dict(self) -> dict[str, object]:
        return {
            "path": self.path,
            "language": self.language,
            "size_bytes": self.size_bytes,
            "chunks": [chunk.to_dict() for chunk in self.chunks],
            "imports": self.imports,
            "exports": self.exports,
        }


FileInfo = FileInfoResult


def analyze_file(path: str | Path, project_root: Path | None = None) -> FileInfoResult:
    """Alias for get_file_info."""
    return get_file_info(str(path), project_root)


def get_file_info(path: str, project_root: Path | None = None) -> FileInfoResult:
    return _get_file_info(path, project_root)


def get_file_info_with_timing(path: str, project_root: Path | None = None) -> tuple[FileInfoResult, float]:
    return timed(_get_file_info)(path, project_root)


def _get_file_info(path: str, project_root: Path | None = None) -> FileInfoResult:
    file_path = Path(path).resolve()
    if not file_path.exists():
        raise FileNotFoundPrimitiveError(f"File not found: {path}")
    if file_path.is_dir():
        raise ParseError(f"Path is a directory: {path}")
    if is_binary_extension(file_path) or not is_text_file(file_path):
        raise ParseError(f"Binary file not supported: {path}")

    # Determine relative path if possible, but keep absolute if needed
    # Usually we want relative to CWD if within it
    if project_root:
        base_dir = project_root.resolve()
    else:
        base_dir = Path.cwd()
        
    try:
        relative_path = file_path.relative_to(base_dir).as_posix()
    except ValueError:
        relative_path = file_path.as_posix()

    try:
        source = file_path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        source = file_path.read_text(encoding="latin-1")
    except OSError as exc:
        raise ParseError(str(exc)) from exc

    language = detect_language(file_path)
    if language is None:
        # Fallback to text/plain behavior or error? 
        # For now error as per existing logic, or maybe allow but no chunks?
        raise ParseError(f"Unsupported language for file: {path}")

    result = None
    if language == "csharp" and project_root:
        try:
            relative = file_path.relative_to(base_dir).as_posix()
            analysis = analyze_csharp_project(
                base_dir,
                [relative],
                discover_project_references(base_dir),
            )
            result = analysis.parsed_files.get(relative)
        except (ValueError, RoslynUnavailableError):
            result = None
    if result is None:
        result = parse_file(str(file_path), source, language)
    if result.errors:
        # result.errors is a list of strings
        raise ParseError("; ".join(result.errors))

    chunks = [
        FileChunk(
            type=chunk.type,
            name=chunk.name,
            lines=(chunk.start_line, chunk.end_line),
        )
        for chunk in result.chunks
    ]

    imports = [
        {
            "module": entry.module,
            "symbols": entry.symbols,
            "line": entry.line,
            "is_relative": entry.is_relative,
        }
        for entry in result.imports
    ]

    exports = [
        {
            "name": entry.name,
            "type": entry.type,
            "line": entry.line,
        }
        for entry in result.exports
    ]

    return FileInfoResult(
        path=relative_path,
        language=language,
        size_bytes=file_path.stat().st_size,
        chunks=chunks,
        imports=imports,
        exports=exports,
    )
