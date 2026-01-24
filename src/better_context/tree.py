"""Directory tree builder for better-context.

Builds a reusable directory tree structure from the file inventory.
Used by templates, stats, and graph grouping.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from .scanner import FileInventory, FileInfo


@dataclass
class DirectoryNode:
    """A node in the directory tree structure."""

    name: str
    path: str
    files: List[str] = field(default_factory=list)
    subdirs: List["DirectoryNode"] = field(default_factory=list)
    file_count: int = 0
    language_breakdown: Dict[str, int] = field(default_factory=dict)

    def get_total_files(self) -> int:
        """Get total file count including subdirectories."""
        total = len(self.files)
        for subdir in self.subdirs:
            total += subdir.get_total_files()
        return total


def build_directory_tree(inventory: "FileInventory") -> DirectoryNode:
    """Build tree structure from flat file list.

    Args:
        inventory: FileInventory from walk_repository

    Returns:
        Root DirectoryNode with full tree structure
    """
    root_name = inventory.root.name if hasattr(inventory.root, "name") else "."

    root = DirectoryNode(
        name=root_name,
        path=".",
    )

    nodes: Dict[str, DirectoryNode] = {".": root}

    for file_info in sorted(inventory.files, key=lambda f: f.path):
        dir_path = os.path.dirname(file_info.path) or "."

        _ensure_path_exists(nodes, dir_path, root)

        node = nodes[dir_path]
        node.files.append(file_info.path)

        if file_info.language:
            node.language_breakdown[file_info.language] = (
                node.language_breakdown.get(file_info.language, 0) + 1
            )

    _calculate_recursive_counts(root)

    return root


def _ensure_path_exists(
    nodes: Dict[str, DirectoryNode],
    path: str,
    root: DirectoryNode,
) -> None:
    """Ensure all directories in path exist in tree."""
    if path in nodes or path == ".":
        return

    path = path.replace("\\", "/")
    parts = path.split("/")

    current_path = "."
    parent = root

    for part in parts:
        if not part or part == ".":
            continue

        if current_path == ".":
            current_path = part
        else:
            current_path = f"{current_path}/{part}"

        if current_path not in nodes:
            new_node = DirectoryNode(
                name=part,
                path=current_path,
            )
            nodes[current_path] = new_node
            parent.subdirs.append(new_node)

        parent = nodes[current_path]


def _calculate_recursive_counts(node: DirectoryNode) -> int:
    """Calculate recursive file counts for all nodes.

    Returns the total file count for this node and all descendants.
    """
    count = len(node.files)

    for subdir in node.subdirs:
        count += _calculate_recursive_counts(subdir)

    node.file_count = count
    return count


def render_tree_ascii(
    node: DirectoryNode,
    prefix: str = "",
    include_files: bool = True,
    max_depth: int = -1,
    current_depth: int = 0,
) -> str:
    """Render tree as ASCII art for AGENTS.md.

    Args:
        node: Directory node to render
        prefix: Current line prefix for indentation
        include_files: Whether to include files (not just directories)
        max_depth: Maximum depth to render (-1 for unlimited)
        current_depth: Current recursion depth

    Returns:
        ASCII representation of the tree
    """
    if max_depth >= 0 and current_depth > max_depth:
        return ""

    lines: List[str] = []

    if current_depth == 0:
        lines.append(f"{node.name}/")
    else:
        lines.append(f"{node.name}/")

    subdirs = sorted(node.subdirs, key=lambda d: d.name)
    files = sorted([os.path.basename(f) for f in node.files]) if include_files else []

    items = [(True, d) for d in subdirs] + [(False, f) for f in files]

    for i, (is_dir, item) in enumerate(items):
        is_last = i == len(items) - 1
        connector = "└── " if is_last else "├── "
        child_prefix = prefix + ("    " if is_last else "│   ")

        if is_dir:
            subdir = item
            lines.append(f"{prefix}{connector}{subdir.name}/")
            if max_depth < 0 or current_depth + 1 < max_depth:
                subtree = render_tree_ascii(
                    subdir,
                    child_prefix,
                    include_files,
                    max_depth,
                    current_depth + 1,
                )
                if subtree:
                    lines.extend(subtree.split("\n")[1:])
        else:
            lines.append(f"{prefix}{connector}{item}")

    return "\n".join(lines)


def render_tree_simple(node: DirectoryNode, max_depth: int = 3) -> str:
    """Render a simple directory-only tree view.

    Args:
        node: Directory node to render
        max_depth: Maximum depth to show

    Returns:
        Simple tree view string
    """
    return render_tree_ascii(node, include_files=False, max_depth=max_depth)


def get_directory_summary(node: DirectoryNode) -> Dict[str, any]:
    """Get summary statistics for a directory.

    Args:
        node: Directory node to summarize

    Returns:
        Dictionary with summary stats
    """
    languages: Dict[str, int] = {}

    def collect_languages(n: DirectoryNode) -> None:
        for lang, count in n.language_breakdown.items():
            languages[lang] = languages.get(lang, 0) + count
        for subdir in n.subdirs:
            collect_languages(subdir)

    collect_languages(node)

    return {
        "path": node.path,
        "total_files": node.file_count,
        "direct_files": len(node.files),
        "subdirectories": len(node.subdirs),
        "languages": languages,
    }


def build_directory_tree_string(file_paths: List[str], max_depth: int = 4) -> str:
    """Build a directory tree string from a list of file paths.
    
    This is a standalone function that doesn't require FileInventory.
    
    Args:
        file_paths: List of relative file paths
        max_depth: Maximum depth to show
    
    Returns:
        ASCII tree representation
    """
    if not file_paths:
        return ""
    
    # Build tree structure
    tree: Dict[str, any] = {}
    
    for path in sorted(file_paths):
        parts = path.replace("\\", "/").split("/")
        current = tree
        for part in parts[:-1]:
            if part not in current:
                current[part] = {}
            current = current[part]
        # Mark files with None
        current[parts[-1]] = None
    
    # Render tree
    lines: List[str] = []
    
    def render(node: Dict[str, any], prefix: str = "", depth: int = 0) -> None:
        if max_depth >= 0 and depth > max_depth:
            return
        
        items = sorted(node.items(), key=lambda x: (x[1] is not None, x[0]))
        
        for i, (name, subtree) in enumerate(items):
            is_last = i == len(items) - 1
            connector = "└── " if is_last else "├── "
            child_prefix = prefix + ("    " if is_last else "│   ")
            
            if subtree is None:
                # It's a file
                lines.append(f"{prefix}{connector}{name}")
            else:
                # It's a directory
                lines.append(f"{prefix}{connector}{name}/")
                render(subtree, child_prefix, depth + 1)
    
    render(tree)
    return "\n".join(lines)
