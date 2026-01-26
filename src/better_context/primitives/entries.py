"""Entries primitive.

Detects entry points in the codebase (CLI commands, main scripts, etc.).
"""

from __future__ import annotations

try:
    import tomllib
except ImportError:
    try:
        import tomli as tomllib
    except ImportError:
        tomllib = None  # Handle gracefully or raise error if needed

import json
from dataclasses import dataclass
from pathlib import Path
from typing import List, Dict, Any, Optional


@dataclass
class EntryPoint:
    """Information about an entry point."""
    path: str
    type: str  # "cli", "script", "app", "lambda", etc.
    language: str
    name: Optional[str] = None  # e.g. command name for CLI


@dataclass
class EntriesResult:
    """Result of entry point analysis."""
    entry_points: List[EntryPoint]

    def to_dict(self) -> dict[str, object]:
        return {
            "entry_points": [
                {
                    "path": e.path,
                    "type": e.type,
                    "language": e.language,
                    "name": e.name
                }
                for e in self.entry_points
            ]
        }

def get_entries(root: Path) -> EntriesResult:
    """Alias for analyze_entry_points."""
    return analyze_entry_points(root)

def analyze_entry_points(root: Path) -> EntriesResult:
    """Analyze codebase for entry points.
    
    Args:
        root: Root directory to analyze
        
    Returns:
        EntriesResult containing detected entry points
    """
    root = root.resolve()
    entry_points: List[EntryPoint] = []
    
    # 1. Check Python package entry points (pyproject.toml)
    pyproject = root / "pyproject.toml"
    if pyproject.exists():
        try:
            content = tomllib.loads(pyproject.read_text(encoding="utf-8"))
            
            # [project.scripts]
            if "project" in content and "scripts" in content["project"]:
                for name, target in content["project"]["scripts"].items():
                    # target format: "package.module:function"
                    module_path = target.split(":")[0].replace(".", "/") + ".py"
                    
                    # Verify file exists
                    full_path = root / "src" / module_path
                    if not full_path.exists():
                        full_path = root / module_path
                    
                    if full_path.exists():
                        rel_path = str(full_path.relative_to(root))
                        entry_points.append(EntryPoint(
                            path=rel_path,
                            type="cli",
                            language="python",
                            name=name
                        ))
                        
            # [tool.poetry.scripts]
            if "tool" in content and "poetry" in content["tool"] and "scripts" in content["tool"]["poetry"]:
                for name, target in content["tool"]["poetry"]["scripts"].items():
                    module_path = target.split(":")[0].replace(".", "/") + ".py"
                    # Try to resolve (simplified)
                    # For a robust solution we'd check configured packages source
                    
                    # Heuristic check for common locations
                    candidates = [
                        root / "src" / module_path,
                        root / module_path,
                    ]
                    
                    for cand in candidates:
                        if cand.exists():
                            entry_points.append(EntryPoint(
                                path=str(cand.relative_to(root)),
                                type="cli",
                                language="python",
                                name=name
                            ))
                            break
                            
        except Exception:
            pass
            
    # 2. Check Node.js bin scripts (package.json)
    pkg_json = root / "package.json"
    if pkg_json.exists():
        try:
            content = json.loads(pkg_json.read_text(encoding="utf-8"))
            
            if "bin" in content:
                bins = content["bin"]
                if isinstance(bins, str):
                    # Single bin
                    path = str(Path(bins))
                    entry_points.append(EntryPoint(
                        path=path,
                        type="cli",
                        language="javascript", # or typescript, could infer from ext
                        name=content.get("name")
                    ))
                elif isinstance(bins, dict):
                    # Multiple bins
                    for name, path in bins.items():
                        entry_points.append(EntryPoint(
                            path=str(Path(path)),
                            type="cli",
                            language="javascript", # infer
                            name=name
                        ))
                        
            if "main" in content:
                entry_points.append(EntryPoint(
                    path=content["main"],
                    type="library", # or main script
                    language="javascript",
                    name="main"
                ))
                
        except Exception:
            pass
            
    # 3. Heuristic file detection
    # Common entry point patterns
    patterns = [
        ("main.py", "script"),
        ("app.py", "app"),
        ("cli.py", "cli"),
        ("index.js", "app"),
        ("index.ts", "app"),
        ("server.js", "server"),
        ("main.go", "app"),
    ]
    
    # Check top level
    for filename, type_hint in patterns:
        path = root / filename
        if path.exists():
            # Avoid duplicates if detected via config
            rel = str(path.relative_to(root))
            if not any(e.path == rel for e in entry_points):
                entry_points.append(EntryPoint(
                    path=rel,
                    type=type_hint,
                    language=Path(filename).suffix.lstrip("."),
                    name=None
                ))
                
    # Check src/ top level
    src_dir = root / "src"
    if src_dir.exists():
        for filename, type_hint in patterns:
            path = src_dir / filename
            if path.exists():
                rel = str(path.relative_to(root))
                if not any(e.path == rel for e in entry_points):
                    entry_points.append(EntryPoint(
                        path=rel,
                        type=type_hint,
                        language=Path(filename).suffix.lstrip("."),
                        name=None
                    ))

    # Format result
    # Return objects, not dicts
    entries_objects = [
        e for e in sorted(entry_points, key=lambda x: x.path)
    ]
    
    return EntriesResult(
        entry_points=entries_objects
    )
