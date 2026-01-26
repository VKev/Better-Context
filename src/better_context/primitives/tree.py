from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os

from ..ignore import load_ignore_patterns, should_ignore, should_ignore_dir
from .base import timed


@dataclass
class DirectorySummary:
    path: str
    file_count: int
    extensions: dict[str, int]

    def to_dict(self) -> dict[str, object]:
        return {
            "path": self.path,
            "file_count": self.file_count,
            "extensions": self.extensions,
        }


@dataclass
class TreeResult:
    root: str
    directories: list[DirectorySummary]
    total_files: int
    total_dirs: int

    def to_dict(self) -> dict[str, object]:
        return {
            "root": self.root,
            "directories": [entry.to_dict() for entry in self.directories],
            "total_files": self.total_files,
            "total_dirs": self.total_dirs,
        }


def analyze_tree(root: Path, max_depth: int = 2) -> TreeResult:
    """Alias for get_tree."""
    return get_tree(root, depth=max_depth)

def get_tree(root: Path, depth: int = 2) -> TreeResult:
    return _get_tree(root, depth)


def get_tree_with_timing(root: Path, depth: int = 2) -> tuple[TreeResult, float]:
    return timed(_get_tree)(root, depth)


def _get_tree(root: Path, depth: int = 2) -> TreeResult:
    root = root.resolve()
    root_str = str(root)
    ignore_patterns = load_ignore_patterns(root)

    directories: list[DirectorySummary] = []
    total_files = 0
    total_dirs = 0

    for dirpath, dirnames, filenames in _walk(root, depth, ignore_patterns):
        if dirpath == root_str:
            relative_dir = ""
        else:
            relative_dir = os.path.relpath(dirpath, root_str)
            if os.sep != "/":
                relative_dir = relative_dir.replace(os.sep, "/")
        
        if relative_dir == ".":
            relative_dir = ""

        file_count = 0
        extensions: dict[str, int] = {}

        for filename in filenames:
            if relative_dir:
                rel_path = f"{relative_dir}/{filename}"
            else:
                rel_path = filename

            if should_ignore(rel_path, ignore_patterns):
                continue
            
            file_count += 1
            total_files += 1
            
            # Extension extraction (simple string split for speed)
            _, ext = os.path.splitext(filename)
            ext = ext.lower()
            extensions[ext] = extensions.get(ext, 0) + 1

        total_dirs += 1
        directories.append(
            DirectorySummary(
                path=relative_dir,
                file_count=file_count,
                extensions=extensions,
            )
        )

    return TreeResult(
        root=str(root),
        directories=directories,
        total_files=total_files,
        total_dirs=total_dirs,
    )


def _walk(
    root: Path, depth: int, ignore_patterns: list[str]
) -> list[tuple[str, list[str], list[str]]]:
    results: list[tuple[str, list[str], list[str]]] = []
    root_str = str(root)
    
    for dirpath, dirnames, filenames in os.walk(root):
        if dirpath == root_str:
            rel_dir = ""
            current_depth = 0
        else:
            # Optimize relative path calculation
            rel_path = os.path.relpath(dirpath, root_str)
            current_depth = rel_path.count(os.sep) + 1
            rel_dir = rel_path.replace(os.sep, "/") if os.sep != "/" else rel_path

        if depth >= 0 and current_depth > depth:
            dirnames[:] = []
            continue

        # Filter directories in-place using string paths
        filtered_dirnames = []
        for name in dirnames:
            if rel_dir:
                child_rel = f"{rel_dir}/{name}"
            else:
                child_rel = name
            
            # Using should_ignore_dir checks if basename matches patterns (fast)
            # OR if full relative path matches patterns
            if not should_ignore_dir(child_rel, ignore_patterns):
                 filtered_dirnames.append(name)
        
        dirnames[:] = filtered_dirnames
        results.append((dirpath, dirnames, filenames))

    return results
