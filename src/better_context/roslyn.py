"""Batch Roslyn bridge for exact C# symbols, references, and calls."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .languages.base import ChunkResult, ExportResult, ImportResult, ParseResult


class RoslynUnavailableError(RuntimeError):
    """Raised when the bundled Roslyn analyzer cannot be built or run."""


@dataclass
class RoslynAnalysis:
    parsed_files: dict[str, ParseResult] = field(default_factory=dict)
    dependencies: list[dict[str, Any]] = field(default_factory=list)
    calls: list[dict[str, Any]] = field(default_factory=list)
    diagnostics: list[str] = field(default_factory=list)
    engine: str = "roslyn"


def analyze_csharp_project(
    root: Path,
    paths: Iterable[str],
    references: Iterable[str] = (),
) -> RoslynAnalysis:
    """Analyze every C# file in one compilation so symbol resolution is consistent."""
    normalized_paths = sorted({path.replace("\\", "/") for path in paths})
    if not normalized_paths:
        return RoslynAnalysis()

    analyzer = _ensure_analyzer()
    request = {
        "root": str(root.resolve()),
        "files": normalized_paths,
        "references": sorted({str(Path(value).resolve()) for value in references}),
    }
    request_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".json",
            prefix="better-context-roslyn-",
            encoding="utf-8",
            delete=False,
        ) as handle:
            json.dump(request, handle)
            request_path = Path(handle.name)
        completed = subprocess.run(
            ["dotnet", str(analyzer), str(request_path)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=300,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise RoslynUnavailableError(f"Roslyn execution failed: {error}") from error
    finally:
        if request_path is not None:
            request_path.unlink(missing_ok=True)

    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip() or "unknown error"
        raise RoslynUnavailableError(
            f"Roslyn analyzer exited with {completed.returncode}: {detail}"
        )
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as error:
        raise RoslynUnavailableError(f"Roslyn returned invalid JSON: {error}") from error
    return _convert_response(payload)


def discover_project_references(root: Path) -> list[str]:
    """Find already-built assemblies without requiring a Unity Editor launch."""
    candidates: set[str] = set()
    source_assemblies = {"Assembly-CSharp", "Assembly-CSharp-Editor"}
    for asmdef in root.glob("Assets/**/*.asmdef"):
        try:
            data = json.loads(asmdef.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        name = data.get("name")
        if isinstance(name, str) and name:
            source_assemblies.add(name)

    def should_include(path: Path) -> bool:
        return (
            path.is_file() and path.suffix.lower() == ".dll" and path.stem not in source_assemblies
        )

    script_assemblies = root / "Library" / "ScriptAssemblies"
    if script_assemblies.is_dir():
        for path in script_assemblies.glob("*.dll"):
            if should_include(path):
                candidates.add(str(path.resolve()))

    for project_file in root.glob("*.csproj"):
        try:
            source = project_file.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for raw in _hint_paths(source):
            path = Path(raw)
            if not path.is_absolute():
                path = project_file.parent / path
            if should_include(path):
                candidates.add(str(path.resolve()))
    return sorted(candidates)


def _hint_paths(source: str) -> list[str]:
    import re

    return [
        value.strip()
        for value in re.findall(r"<HintPath>(.*?)</HintPath>", source, re.IGNORECASE | re.DOTALL)
        if "$" not in value
    ]


def _ensure_analyzer() -> Path:
    dotnet = shutil.which("dotnet")
    if not dotnet:
        raise RoslynUnavailableError("A .NET 8+ SDK is required for Roslyn C# analysis.")

    helper = Path(__file__).with_name("roslyn_helper")
    project = helper / "BetterContext.Roslyn.csproj"
    program = helper / "Program.cs"
    if not project.is_file() or not program.is_file():
        raise RoslynUnavailableError(
            "Bundled Roslyn helper sources are missing from the installation."
        )
    digest = hashlib.sha256(project.read_bytes() + program.read_bytes()).hexdigest()[:16]
    cache_dir = _cache_root() / digest
    analyzer = cache_dir / "BetterContext.Roslyn.dll"
    if analyzer.is_file():
        return analyzer

    cache_dir.mkdir(parents=True, exist_ok=True)
    try:
        completed = subprocess.run(
            [
                dotnet,
                "build",
                str(project),
                "-c",
                "Release",
                "--nologo",
                "--verbosity",
                "quiet",
                "-o",
                str(cache_dir),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=300,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise RoslynUnavailableError(f"Could not build the Roslyn helper: {error}") from error
    if completed.returncode != 0 or not analyzer.is_file():
        detail = completed.stderr.strip() or completed.stdout.strip() or "unknown build error"
        raise RoslynUnavailableError(f"Could not build the Roslyn helper: {detail}")
    return analyzer


def _cache_root() -> Path:
    override = os.environ.get("BETTER_CONTEXT_ROSLYN_CACHE")
    if override:
        return Path(override).expanduser().resolve()
    if os.name == "nt" and os.environ.get("LOCALAPPDATA"):
        return Path(os.environ["LOCALAPPDATA"]) / "better-context-unity" / "roslyn"
    xdg = os.environ.get("XDG_CACHE_HOME")
    base = Path(xdg).expanduser() if xdg else Path.home() / ".cache"
    return base / "better-context-unity" / "roslyn"


def _convert_response(payload: dict[str, Any]) -> RoslynAnalysis:
    parsed: dict[str, ParseResult] = {}
    for path, file_data in payload.get("files", {}).items():
        chunks: list[ChunkResult] = []
        for symbol in file_data.get("symbols", []):
            metadata = {
                "qualified_name": symbol.get("qualifiedName", ""),
                "accessibility": symbol.get("accessibility", ""),
                "bases": symbol.get("bases", []),
                "unity_type": symbol.get("unityType"),
                "abstract": symbol.get("isAbstract", False),
                "is_abstract": symbol.get("isAbstract", False),
                "static": symbol.get("isStatic", False),
                "extension": symbol.get("isExtension", False),
                "return_type": symbol.get("returnType"),
                "analysis_engine": "roslyn",
            }
            chunks.append(
                ChunkResult(
                    id=symbol.get("id", ""),
                    type=symbol.get("kind", ""),
                    name=symbol.get("name", ""),
                    signature=symbol.get("signature", ""),
                    start_line=symbol.get("startLine", 1),
                    end_line=symbol.get("endLine", symbol.get("startLine", 1)),
                    parent=symbol.get("parentId"),
                    exported=symbol.get("isPublic", False),
                    docstring=symbol.get("documentation"),
                    metadata=metadata,
                    semantic_anchor=symbol.get("semanticAnchor"),
                )
            )
        imports = [
            ImportResult(
                module=item.get("module", ""),
                alias=item.get("alias"),
                line=item.get("line", 0),
            )
            for item in file_data.get("usings", [])
        ]
        exports = [
            ExportResult(name=chunk.name, type=chunk.type, line=chunk.start_line)
            for chunk in chunks
            if chunk.exported
        ]
        parsed[path.replace("\\", "/")] = ParseResult(
            chunks=chunks,
            imports=imports,
            exports=exports,
        )
    return RoslynAnalysis(
        parsed_files=parsed,
        dependencies=list(payload.get("dependencies", [])),
        calls=list(payload.get("calls", [])),
        diagnostics=list(payload.get("diagnostics", [])),
        engine=payload.get("engine", "roslyn"),
    )


__all__ = [
    "RoslynAnalysis",
    "RoslynUnavailableError",
    "analyze_csharp_project",
    "discover_project_references",
]
