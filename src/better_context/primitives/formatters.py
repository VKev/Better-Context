"""Output formatters for CLI commands."""

from __future__ import annotations

import json
from typing import Any, List, Dict
from pathlib import Path

from .tree import TreeResult
from .overview import OverviewResult
from .scripts import ScriptsResult
from .entries import EntriesResult
from .file_info import FileInfoResult
from .deps import DepsResult


def format_json(data: Any) -> str:
    """Format data as JSON."""
    if hasattr(data, "to_dict"):
        data = data.to_dict()
    return json.dumps(data, indent=2)


def format_tree_human(result: TreeResult) -> str:
    """Format tree result for human reading."""
    # Simple list for now
    lines = [f"Project Root: {result.root}"]
    lines.append(f"Total Files: {result.total_files}")
    lines.append(f"Total Directories: {result.total_dirs}")
    lines.append("")
    
    # We can do better than a flat list if we sort by path
    # But for "human" output, maybe just the top level structure?
    # Or rely on `tree` command style output if possible.
    # Given the flat structure in result, we can just list paths.
    
    for d in result.directories:
        path = d.path or "."
        lines.append(f"{path}/ ({d.file_count} files)")
        
    return "\n".join(lines)


def format_tree_markdown(result: TreeResult) -> str:
    """Format tree result as Markdown."""
    lines = [f"# Project: {Path(result.root).name}"]
    lines.append("")
    lines.append(f"- **Root**: `{result.root}`")
    lines.append(f"- **Files**: {result.total_files}")
    lines.append(f"- **Directories**: {result.total_dirs}")
    lines.append("")
    lines.append("## Directory Structure")
    lines.append("")
    lines.append("| Directory | Files | Extensions |")
    lines.append("|-----------|-------|------------|")
    
    for d in result.directories:
        path = d.path or "."
        exts = ", ".join(f"{k}: {v}" for k, v in d.extensions.items())
        lines.append(f"| `{path}/` | {d.file_count} | {exts} |")
        
    return "\n".join(lines)


def format_overview_human(result: OverviewResult) -> str:
    """Format overview result for human reading."""
    lines = [
        f"Project: {result.project_name}",
        f"Language: {result.primary_language or 'Unknown'}",
    ]
    if result.package_manager:
        lines.append(f"Package Manager: {result.package_manager}")
    if result.frameworks:
        lines.append(f"Frameworks: {', '.join(result.frameworks)}")
    
    lines.append(f"Type: {result.workspace_type}")
    if result.source_dirs:
        lines.append(f"Source: {', '.join(result.source_dirs)}")
    if result.test_dirs:
        lines.append(f"Tests: {', '.join(result.test_dirs)}")
        
    return "\n".join(lines)


def format_overview_markdown(result: OverviewResult) -> str:
    """Format overview result as Markdown."""
    lines = ["# Project Overview"]
    lines.append("")
    lines.append(f"- **Project Name**: {result.project_name}")
    lines.append(f"- **Primary Language**: {result.primary_language or 'Unknown'}")
    if result.package_manager:
        lines.append(f"- **Package Manager**: {result.package_manager}")
    if result.frameworks:
        lines.append(f"- **Frameworks**: {', '.join(result.frameworks)}")
    
    lines.append(f"- **Workspace Type**: {result.workspace_type}")
    if result.source_dirs:
        lines.append(f"- **Source Directories**: `{', '.join(result.source_dirs)}`")
    if result.test_dirs:
        lines.append(f"- **Test Directories**: `{', '.join(result.test_dirs)}`")
        
    return "\n".join(lines)


def format_scripts_human(result: ScriptsResult) -> str:
    """Format scripts result for human reading."""
    lines = []
    if result.golden_commands:
        lines.append("Golden Commands:")
        for name, cmd in result.golden_commands.items():
            lines.append(f"  {name}: {cmd}")
        lines.append("")
        
    if result.scripts:
        lines.append("Scripts:")
        for s in result.scripts:
            lines.append(f"  {s['name']} ({s['source']}): {s['run_as']}")
            
    return "\n".join(lines)


def format_scripts_markdown(result: ScriptsResult) -> str:
    """Format scripts result as Markdown."""
    lines = ["# Scripts"]
    
    if result.golden_commands:
        lines.append("")
        lines.append("## Golden Commands")
        lines.append("")
        lines.append("| Action | Command |")
        lines.append("|--------|---------|")
        for name, cmd in result.golden_commands.items():
            lines.append(f"| {name} | `{cmd}` |")
            
    if result.scripts:
        lines.append("")
        lines.append("## Available Scripts")
        lines.append("")
        lines.append("| Name | Command | Source |")
        lines.append("|------|---------|--------|")
        for s in result.scripts:
            lines.append(f"| {s['name']} | `{s['run_as']}` | {s['source']} |")
            
    return "\n".join(lines)


def format_entries_human(result: EntriesResult) -> str:
    """Format entries result for human reading."""
    lines = ["Entry Points:"]
    for entry in result.entry_points:
        name_str = f" ({entry.name})" if entry.name else ""
        lines.append(f"  - {entry.path} [{entry.type}]{name_str}")
    return "\n".join(lines)


def format_entries_markdown(result: EntriesResult) -> str:
    """Format entries result as Markdown."""
    lines = ["# Entry Points"]
    lines.append("")
    lines.append("| Path | Type | Language | Name |")
    lines.append("|------|------|----------|------|")
    for entry in result.entry_points:
        name = entry.name or "-"
        lines.append(f"| `{entry.path}` | {entry.type} | {entry.language} | {name} |")
    return "\n".join(lines)


def format_file_info_human(result: FileInfoResult) -> str:
    """Format file info result for human reading."""
    lines = [
        f"File: {result.path}",
        f"Language: {result.language}",
        f"Size: {result.size_bytes} bytes",
        f"Chunks: {len(result.chunks)}",
        f"Imports: {len(result.imports)}",
        f"Exports: {len(result.exports)}",
    ]
    
    if result.exports:
        lines.append("\nExports:")
        for exp in result.exports:
            lines.append(f"  - {exp['name']} ({exp['type']})")
            
    return "\n".join(lines)


def format_file_info_markdown(result: FileInfoResult) -> str:
    """Format file info result as Markdown."""
    lines = [f"# File: {result.path}"]
    lines.append("")
    lines.append(f"- **Language**: {result.language}")
    lines.append(f"- **Size**: {result.size_bytes} bytes")
    lines.append(f"- **Chunks**: {len(result.chunks)}")
    lines.append(f"- **Imports**: {len(result.imports)}")
    lines.append(f"- **Exports**: {len(result.exports)}")
    
    if result.exports:
        lines.append("")
        lines.append("## Exports")
        lines.append("")
        lines.append("| Name | Type | Line |")
        lines.append("|------|------|------|")
        for exp in result.exports:
            lines.append(f"| `{exp['name']}` | {exp['type']} | {exp.get('line', '-')} |")
            
    if result.chunks:
        lines.append("")
        lines.append("## Chunks")
        lines.append("")
        lines.append("| Name | Type | Lines |")
        lines.append("|------|------|-------|")
        for chunk in result.chunks:
            # Handle FileChunk object or dict
            if hasattr(chunk, 'name'):
                name = chunk.name
                ctype = chunk.type
                lines_range = f"{chunk.lines[0]}-{chunk.lines[1]}"
            else:
                name = chunk.get('name')
                ctype = chunk.get('type')
                lines_range = f"{chunk.get('lines', [0,0])[0]}-{chunk.get('lines', [0,0])[1]}"
            lines.append(f"| `{name}` | {ctype} | {lines_range} |")
            
    return "\n".join(lines)


def format_deps_human(result: DepsResult) -> str:
    """Format deps result for human reading."""
    lines = [f"Dependencies for {result.path}:"]
    
    lines.append("\nImports (Dependencies):")
    if not result.dependencies:
        lines.append("  (None)")
    for dep in result.dependencies:
        lines.append(f"  -> {dep.path}")
        
    lines.append("\nImported By (Dependents):")
    if not result.dependents:
        lines.append("  (None)")
    for dep in result.dependents:
        lines.append(f"  <- {dep.path}")
        
    return "\n".join(lines)


def format_deps_markdown(result: DepsResult) -> str:
    """Format deps result as Markdown."""
    lines = [f"# Dependencies: `{result.path}`"]
    
    lines.append("")
    lines.append("## Imports (Dependencies)")
    if not result.dependencies:
        lines.append("_None_")
    else:
        for dep in result.dependencies:
            lines.append(f"- `{dep.path}`")
            
    lines.append("")
    lines.append("## Imported By (Dependents)")
    if not result.dependents:
        lines.append("_None_")
    else:
        for dep in result.dependents:
            lines.append(f"- `{dep.path}`")
            
    return "\n".join(lines)
