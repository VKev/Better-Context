"""
Import/Export Intermediate Representation and Resolution.

Provides a stable, language-agnostic IR for imports and exports that
separates EXTRACTION from RESOLUTION.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Dict, Set, Tuple, Optional, Protocol


# ============================================================================
# RAW DATA STRUCTURES (from language adapters)
# ============================================================================

@dataclass
class RawImport:
    """
    What a language adapter extracts from source code.
    
    This is raw data - no resolution has been performed yet.
    """
    specifier: str              # The import string as written
    symbols: List[str] = field(default_factory=list)  # Imported symbols ([] = entire module)
    alias: Optional[str] = None # Import alias (e.g., 'import numpy as np')
    line: int = 0               # Line number
    is_type_only: bool = False  # For TypeScript 'import type'
    is_dynamic: bool = False    # For dynamic imports
    
    # Hints for resolution
    is_relative: bool = False   # Starts with './' or '../'
    is_absolute: bool = False   # Starts with '/' or drive letter
    is_package: bool = False    # Looks like external package


@dataclass
class RawExport:
    """
    What a language adapter extracts from source code for exports.
    """
    name: str                    # Exported symbol name
    type: str                    # function, class, variable, type
    line: int = 0                # Line number
    is_default: bool = False     # Default export (JS/TS)
    is_reexport: bool = False    # Re-export from another module
    source_module: Optional[str] = None  # For re-exports


# ============================================================================
# RESOLVED DATA STRUCTURES (after resolution)
# ============================================================================

@dataclass
class ResolvedEdge:
    """
    A resolved import relationship between two files.
    """
    from_file: str              # Importing file (relative path)
    to_file: Optional[str]      # Resolved target (None if external)
    specifier: str              # Original import specifier
    kind: str = 'import'        # 'import', 'reexport', 'type_import'
    confidence: float = 1.0     # 0.0-1.0 how sure we are
    symbols: List[str] = field(default_factory=list)  # What symbols are imported
    is_external: bool = False   # True if external package


@dataclass
class ResolutionResult:
    """
    Result of resolving all imports in a codebase.
    """
    edges: List[ResolvedEdge] = field(default_factory=list)
    unresolved: List[Tuple[str, RawImport]] = field(default_factory=list)  # (file, import) pairs
    external_packages: Set[str] = field(default_factory=set)


# ============================================================================
# CONFIDENCE LEVELS
# ============================================================================

class Confidence:
    """Standard confidence levels for resolution."""
    EXACT_MATCH = 1.0       # Direct file path match
    INDEX_FILE = 0.95       # Resolved to index.ts / __init__.py
    PATH_ALIAS = 0.9        # Resolved via tsconfig paths
    HEURISTIC = 0.7         # Best guess from patterns
    UNRESOLVED_INTERNAL = 0.3   # Looks internal but can't find
    EXTERNAL = 0.0          # External package


# ============================================================================
# FILE INDEX
# ============================================================================

def build_file_index(files: List[str]) -> Dict[str, str]:
    """
    Build mapping from various module names to file paths.
    
    A file may be reachable by multiple names, so we index it multiple ways.
    
    Args:
        files: List of relative file paths
    
    Returns:
        Dict mapping module identifiers to file paths
    """
    index: Dict[str, str] = {}
    
    for file_path in files:
        # Normalize separators
        path = file_path.replace(os.sep, '/')
        
        # Exact path
        index[path] = path
        
        # Without extension
        no_ext = os.path.splitext(path)[0]
        if no_ext not in index:
            index[no_ext] = path
        
        # Module notation (/ -> .)
        module_path = no_ext.replace('/', '.')
        if module_path not in index:
            index[module_path] = path
        
        # Basename only (for simple lookups) - but only if unique
        basename = os.path.basename(no_ext)
        if basename not in index:
            index[basename] = path
        
        # For Python: __init__.py files make directory importable
        if path.endswith('__init__.py'):
            dir_path = os.path.dirname(path)
            if dir_path and dir_path not in index:
                index[dir_path] = path
            dir_module = dir_path.replace('/', '.')
            if dir_module and dir_module not in index:
                index[dir_module] = path
        
        # For JS/TS: index.ts/index.js files make directory importable
        base = os.path.basename(no_ext)
        if base == 'index':
            dir_path = os.path.dirname(path)
            if dir_path and dir_path not in index:
                index[dir_path] = path
    
    return index


# ============================================================================
# RESOLVER PROTOCOL
# ============================================================================

class ImportResolver(Protocol):
    """
    Protocol for language-specific import resolution.
    
    Each language adapter should provide a resolver that understands
    its import semantics.
    """
    
    @property
    def language(self) -> str:
        """Return language identifier."""
        ...
    
    def resolve(
        self,
        raw_import: RawImport,
        from_file: str,
        file_index: Dict[str, str],
        project_root: Path,
    ) -> ResolvedEdge:
        """
        Resolve a single import to its target.
        
        Args:
            raw_import: The raw import data from the adapter
            from_file: The file containing this import
            file_index: Available files and their aliases
            project_root: Project root directory
        
        Returns:
            ResolvedEdge with confidence level
        """
        ...


# ============================================================================
# BASE RESOLVER IMPLEMENTATION
# ============================================================================

class BaseResolver:
    """
    Base resolver with common resolution logic.
    
    Can be used directly for simple cases or subclassed for
    language-specific behavior.
    """
    
    language: str = 'generic'
    
    # Common external package prefixes by language
    EXTERNAL_PREFIXES: Dict[str, Set[str]] = {
        'python': {'os', 'sys', 'json', 'typing', 're', 'pathlib', 'dataclasses'},
        'typescript': {'react', 'next', 'lodash', 'axios', 'express'},
        'javascript': {'react', 'next', 'lodash', 'axios', 'express'},
    }
    
    def resolve(
        self,
        raw_import: RawImport,
        from_file: str,
        file_index: Dict[str, str],
        project_root: Path,
    ) -> ResolvedEdge:
        """Resolve an import to its target file."""
        specifier = raw_import.specifier
        
        # Handle explicit external/package imports
        if raw_import.is_package:
            return ResolvedEdge(
                from_file=from_file,
                to_file=None,
                specifier=specifier,
                kind='type_import' if raw_import.is_type_only else 'import',
                confidence=Confidence.EXTERNAL,
                symbols=raw_import.symbols,
                is_external=True,
            )
        
        # Try to resolve
        resolved_path = None
        confidence = Confidence.UNRESOLVED_INTERNAL
        
        # Handle relative imports
        if raw_import.is_relative:
            resolved_path, confidence = self._resolve_relative(
                specifier, from_file, file_index
            )
        else:
            # Try direct lookup
            resolved_path, confidence = self._resolve_direct(
                specifier, file_index
            )
        
        # Determine if external
        is_external = resolved_path is None and self._looks_external(specifier)
        if is_external:
            confidence = Confidence.EXTERNAL
        
        return ResolvedEdge(
            from_file=from_file,
            to_file=resolved_path,
            specifier=specifier,
            kind='type_import' if raw_import.is_type_only else 'import',
            confidence=confidence,
            symbols=raw_import.symbols,
            is_external=is_external,
        )
    
    def _resolve_relative(
        self,
        specifier: str,
        from_file: str,
        file_index: Dict[str, str],
    ) -> Tuple[Optional[str], float]:
        """Resolve a relative import."""
        # Get directory of importing file
        from_dir = os.path.dirname(from_file)
        
        # Normalize the specifier
        spec = specifier.lstrip('./')
        
        # Count '..' for parent traversal
        parent_count = 0
        while specifier.startswith('..'):
            parent_count += 1
            specifier = specifier[3:] if specifier.startswith('../') else specifier[2:]
        
        # Navigate up directories
        parts = from_dir.split('/') if from_dir else []
        if parent_count > len(parts):
            return None, Confidence.UNRESOLVED_INTERNAL
        
        base = '/'.join(parts[:len(parts) - parent_count])
        if specifier.startswith('./'):
            specifier = specifier[2:]
        
        # Build candidate path
        if base:
            candidate = f"{base}/{specifier}"
        else:
            candidate = specifier
        
        candidate = candidate.replace(os.sep, '/')
        
        # Try various lookups
        if candidate in file_index:
            return file_index[candidate], Confidence.EXACT_MATCH
        
        # Try without extension
        no_ext = os.path.splitext(candidate)[0]
        if no_ext in file_index:
            return file_index[no_ext], Confidence.EXACT_MATCH
        
        # Try as directory (index file)
        if candidate in file_index:
            return file_index[candidate], Confidence.INDEX_FILE
        
        return None, Confidence.UNRESOLVED_INTERNAL
    
    def _resolve_direct(
        self,
        specifier: str,
        file_index: Dict[str, str],
    ) -> Tuple[Optional[str], float]:
        """Resolve a non-relative import."""
        # Normalize
        specifier = specifier.replace(os.sep, '/')
        
        # Direct lookup
        if specifier in file_index:
            return file_index[specifier], Confidence.EXACT_MATCH
        
        # Module notation lookup
        module_path = specifier.replace('.', '/')
        if module_path in file_index:
            return file_index[module_path], Confidence.EXACT_MATCH
        
        # Try first part as directory
        parts = specifier.split('.')
        if len(parts) > 1:
            first = parts[0]
            if first in file_index:
                return file_index[first], Confidence.HEURISTIC
        
        return None, Confidence.UNRESOLVED_INTERNAL
    
    def _looks_external(self, specifier: str) -> bool:
        """Check if a specifier looks like an external package."""
        # Relative imports are not external
        if specifier.startswith('.'):
            return False
        
        # Absolute paths are not external
        if specifier.startswith('/') or (len(specifier) > 1 and specifier[1] == ':'):
            return False
        
        # Get the package name (first part)
        parts = specifier.replace('/', '.').split('.')
        package = parts[0] if parts else specifier
        
        # Check known external packages
        for lang_externals in self.EXTERNAL_PREFIXES.values():
            if package in lang_externals:
                return True
        
        # Common patterns for external packages
        if package in {'@', 'node_modules'}:
            return True
        
        # Scoped packages (@org/package)
        if specifier.startswith('@'):
            return True
        
        return False


# ============================================================================
# RESOLUTION RUNNER
# ============================================================================

def resolve_all_imports(
    files: Dict[str, List[RawImport]],
    file_paths: List[str],
    project_root: Path,
    resolver: Optional[ImportResolver] = None,
) -> ResolutionResult:
    """
    Resolve all imports in a codebase.
    
    Args:
        files: Dict mapping file paths to their RawImport lists
        file_paths: All available file paths
        project_root: Project root directory
        resolver: Optional custom resolver (defaults to BaseResolver)
    
    Returns:
        ResolutionResult with all edges and diagnostics
    """
    if resolver is None:
        resolver = BaseResolver()
    
    file_index = build_file_index(file_paths)
    result = ResolutionResult()
    
    for from_file, imports in files.items():
        for raw_import in imports:
            edge = resolver.resolve(
                raw_import,
                from_file,
                file_index,
                project_root,
            )
            
            result.edges.append(edge)
            
            # Track external packages
            if edge.is_external and edge.specifier:
                # Get package name from specifier
                parts = edge.specifier.replace('/', '.').split('.')
                package = parts[0]
                if package.startswith('@') and len(parts) > 1:
                    package = f"{parts[0]}/{parts[1]}"
                result.external_packages.add(package)
            
            # Track unresolved
            elif edge.to_file is None and not edge.is_external:
                result.unresolved.append((from_file, raw_import))
    
    return result


def get_internal_edges(result: ResolutionResult) -> List[ResolvedEdge]:
    """Get only internal (non-external) edges."""
    return [e for e in result.edges if not e.is_external and e.to_file is not None]


def get_external_packages(result: ResolutionResult) -> List[str]:
    """Get sorted list of external packages."""
    return sorted(result.external_packages)


def get_resolution_stats(result: ResolutionResult) -> dict:
    """Get statistics about resolution results."""
    internal = [e for e in result.edges if not e.is_external]
    external = [e for e in result.edges if e.is_external]
    resolved = [e for e in internal if e.to_file is not None]
    
    return {
        'total_imports': len(result.edges),
        'internal_imports': len(internal),
        'external_imports': len(external),
        'resolved': len(resolved),
        'unresolved': len(result.unresolved),
        'external_packages': len(result.external_packages),
        'resolution_rate': len(resolved) / len(internal) if internal else 1.0,
    }
