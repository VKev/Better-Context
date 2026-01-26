"""Dependencies primitive.

Analyzes dependencies and dependents for a specific file using the dependency graph.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..graph import DependencyGraph
from ..manifest import load_manifest
from ..languages import detect_language
from ..chunker import parse_file
from ..scanner import is_binary_extension, is_text_file
from .base import FileNotFoundPrimitiveError, ParseError


@dataclass
class DependencyInfo:
    """Information about a dependency."""
    path: str
    symbols: list[str]
    is_internal: bool = True
    is_stdlib: bool = False
    import_line: int | None = None
    
    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "symbols": self.symbols,
            "is_internal": self.is_internal,
            "is_stdlib": self.is_stdlib,
            "import_line": self.import_line,
        }


@dataclass
class DepsResult:
    """Result of dependencies analysis."""
    path: str
    dependencies: list[DependencyInfo]
    dependents: list[DependencyInfo]
    manifest_used: bool = False
    stats: dict[str, int] = None
    
    def to_dict(self) -> dict[str, object]:
        return {
            "path": self.path,
            "dependencies": [entry.to_dict() for entry in self.dependencies],
            "dependents": [entry.to_dict() for entry in self.dependents],
            "manifest_used": self.manifest_used,
            "stats": self.stats or {
                "dependency_count": len(self.dependencies),
                "dependent_count": len(self.dependents),
                "internal_deps": sum(1 for d in self.dependencies if d.is_internal),
                "external_deps": sum(1 for d in self.dependencies if not d.is_internal),
            },
        }


def get_deps(path: str | Path, graph: DependencyGraph | None = None) -> DepsResult:
    """Get dependencies and dependents for a file.
    
    If graph is provided, uses it. Otherwise attempts to load manifest or parse file.
    """
    if graph:
        return get_file_dependencies(path, graph)
        
    return _get_deps_standalone(str(path))


def get_file_dependencies(path: str | Path, graph: DependencyGraph) -> DepsResult:
    """Get dependencies and dependents for a file using a graph."""
    path_str = str(path)
    
    # Get outgoing dependencies (what this file imports)
    dependencies: list[DependencyInfo] = []
    
    # Use graph edge info if available
    if path_str in graph.edges:
        for dep_path in graph.edges[path_str]:
            # Try to find edge metadata for richer info
            edge_data = graph.edge_info.get((path_str, dep_path))
            
            dependencies.append(DependencyInfo(
                path=dep_path,
                symbols=edge_data.symbols if edge_data else [],
                is_internal=not (edge_data and edge_data.is_external),
                is_stdlib=False,  # Graph typically only stores internal edges or marked externals
                import_line=None  # Graph might not store line numbers
            ))
            
    # Get incoming dependents (what imports this file)
    dependents: list[DependencyInfo] = []
    for src, targets in graph.edges.items():
        if path_str in targets:
            edge_data = graph.edge_info.get((src, path_str))
            dependents.append(DependencyInfo(
                path=src,
                symbols=edge_data.symbols if edge_data else [],
                is_internal=True,
                is_stdlib=False,
                import_line=None
            ))
            
    dependencies.sort(key=lambda x: x.path)
    dependents.sort(key=lambda x: x.path)
    
    return DepsResult(
        path=path_str,
        dependencies=dependencies,
        dependents=dependents,
        manifest_used=True
    )


def _get_deps_standalone(path: str) -> DepsResult:
    file_path = Path(path)
    if not file_path.exists():
        raise FileNotFoundPrimitiveError(f"File not found: {path}")
    if file_path.is_dir():
        raise ParseError(f"Path is a directory: {path}")
    if is_binary_extension(file_path) or not is_text_file(file_path):
        raise ParseError(f"Binary file not supported: {path}")

    manifest_path = _find_manifest_path(file_path)
    if manifest_path:
        manifest = load_manifest(manifest_path)
        return _deps_from_manifest(file_path, manifest)

    return _deps_from_parse(file_path)


def _find_manifest_path(file_path: Path) -> Path | None:
    for parent in [file_path.parent, *file_path.parents]:
        candidate = parent / ".better-context" / "manifest.json"
        if candidate.exists():
            return candidate
    return None


from ..resolution import BaseResolver

def _deps_from_manifest(file_path: Path, manifest) -> DepsResult:
    root = Path(manifest.meta.root_path)
    try:
        rel_path = str(file_path.resolve().relative_to(root))
    except ValueError:
        rel_path = str(file_path)

    dependencies: list[DependencyInfo] = []
    dependents: list[DependencyInfo] = []

    # Manifest graph stores edges as list of tuples (from, to)
    # It might not store full edge metadata in the graph structure, 
    # but let's check what's available
    
    # The Manifest object has graph.edges as list[tuple[str, str]]
    # It doesn't seem to store the rich edge metadata like symbols or lines directly in graph.edges
    # However, manifest.files contains ImportEntry which has this data!
    
    # Strategy: 
    # 1. Use manifest.files to find the FileEntry for our path
    # 2. Iterate its imports to build dependencies (richer data)
    # 3. Use graph edges to find dependents (reverse lookup)
    
    target_file = next((f for f in manifest.files if f.path == rel_path), None)
    
    # Dependencies from FileEntry (richer)
    if target_file:
        for imp in target_file.imports:
            # We need to resolve where this import points to
            # But the manifest ImportEntry doesn't store the resolved path, just module name
            # So we might need to rely on the graph edges for resolution, 
            # or try to match them up.
            
            # Simple approach: Check if it looks external/stdlib using resolver logic
            resolver = BaseResolver()
            is_external = resolver._looks_external(imp.module)
            
            # For now, let's use the module name as path for externals, 
            # and try to find the resolved path for internals from graph edges
            resolved_path = imp.module
            
            # Check if this import corresponds to an edge in the graph
            # This is tricky because one file might import multiple things
            
            dependencies.append(DependencyInfo(
                path=imp.module, # This is the raw module string
                symbols=imp.symbols,
                is_internal=not is_external,
                is_stdlib=False, # TODO: refine this
                import_line=imp.line
            ))
    else:
        # Fallback to graph edges if file entry not found
        for from_path, to_path in manifest.graph.edges:
            if from_path == rel_path:
                dependencies.append(DependencyInfo(
                    path=to_path, 
                    symbols=[],
                    is_internal=True,
                    import_line=None
                ))

    # Dependents from graph (reverse lookup)
    for from_path, to_path in manifest.graph.edges:
        if to_path == rel_path:
            dependents.append(DependencyInfo(
                path=from_path, 
                symbols=[],
                is_internal=True,
                import_line=None
            ))

    return DepsResult(
        path=rel_path,
        dependencies=dependencies,
        dependents=dependents,
        manifest_used=True,
    )


from ..resolution import BaseResolver

def _deps_from_parse(file_path: Path) -> DepsResult:
    try:
        source = file_path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        source = file_path.read_text(encoding="latin-1")
    except OSError as exc:
        raise ParseError(str(exc)) from exc

    language = detect_language(file_path)
    if language is None:
        raise ParseError(f"Unsupported language for file: {file_path}")

    result = parse_file(str(file_path), source, language)
    if result.errors:
        # Check if errors is a list of strings or ParseError objects
        # ParseResult.errors is usually List[str]
        error_msg = "; ".join(str(e) for e in result.errors)
        raise ParseError(error_msg)

    resolver = BaseResolver()
    dependencies = []
    
    for entry in result.imports:
        # Check if external/stdlib
        # Note: primitive deps doesn't resolve fully without a project scan
        # but we can detect "looks external"
        is_external = resolver._looks_external(entry.module)
        is_stdlib = False # hard to know for sure without full context/stdlib list
        
        # In Python, we can check a known stdlib list if we wanted
        if language == 'python':
             if entry.module in resolver.EXTERNAL_PREFIXES['python']:
                 is_external = True
                 is_stdlib = True
        
        dependencies.append(DependencyInfo(
            path=entry.module, 
            symbols=list(entry.symbols),
            is_internal=not is_external,
            is_stdlib=is_stdlib,
            import_line=entry.line
        ))

    return DepsResult(
        path=str(file_path),
        dependencies=dependencies,
        dependents=[], # Can't know dependents without full scan
        manifest_used=False,
    )
