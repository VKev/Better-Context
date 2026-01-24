"""
.ctxignore pattern matching for better-context.

Implements gitignore-style pattern matching to exclude files from analysis.
Uses only stdlib for zero-dependency operation.
"""

from __future__ import annotations

import fnmatch
import os
from pathlib import Path
from typing import List, Optional

# Default patterns always applied (before user .ctxignore)
DEFAULT_IGNORES: List[str] = [
    # Version control
    '.git/',
    '.svn/',
    '.hg/',
    
    # Dependencies
    'node_modules/',
    'vendor/',
    'venv/',
    '.venv/',
    '__pycache__/',
    '.pytest_cache/',
    '.mypy_cache/',
    '.ruff_cache/',
    
    # Build outputs
    'dist/',
    'build/',
    'target/',
    '.next/',
    'out/',
    '.nuxt/',
    '.output/',
    
    # IDE/Editor
    '.idea/',
    '.vscode/',
    '*.swp',
    '*.swo',
    '*~',
    
    # Our own output
    '.better-context/',
    
    # Common lock files (usually not needed for analysis)
    'package-lock.json',
    'yarn.lock',
    'pnpm-lock.yaml',
    'poetry.lock',
    'Cargo.lock',
]


def load_ignore_patterns(root: Path, filename: str = '.ctxignore') -> List[str]:
    """
    Load ignore patterns from .ctxignore file and combine with defaults.
    
    Args:
        root: Project root directory
        filename: Name of ignore file (default: .ctxignore)
    
    Returns:
        Combined list of patterns (defaults + user patterns)
    """
    patterns = list(DEFAULT_IGNORES)
    
    ignore_file = root / filename
    if ignore_file.exists():
        try:
            content = ignore_file.read_text(encoding='utf-8')
            user_patterns = parse_ignore_file(content)
            patterns.extend(user_patterns)
        except (OSError, UnicodeDecodeError):
            pass  # Ignore read errors, continue with defaults
    
    return patterns


def parse_ignore_file(content: str) -> List[str]:
    """
    Parse .ctxignore file content into a list of patterns.
    
    Syntax:
        - Lines starting with # are comments
        - Empty lines are ignored
        - Lines starting with ! are negation patterns
        - Trailing / indicates directory-only match
        - * matches anything except /
        - ** matches anything including /
    
    Args:
        content: Raw content of .ctxignore file
    
    Returns:
        List of patterns (preserving order, including negations)
    """
    patterns = []
    for line in content.splitlines():
        line = line.strip()
        
        # Skip empty lines and comments
        if not line or line.startswith('#'):
            continue
        
        patterns.append(line)
    
    return patterns


def _normalize_path(path: str) -> str:
    """Normalize path separators to forward slashes."""
    # Replace OS-specific separators with forward slashes
    normalized = path.replace(os.sep, '/')
    
    # Remove leading "./" but preserve other leading dots (like ".git")
    if normalized.startswith('./'):
        normalized = normalized[2:]
    
    return normalized


def _match_pattern(path: str, pattern: str, is_dir: bool = False) -> bool:
    """
    Match a single pattern against a path.
    
    Args:
        path: Relative path (normalized to forward slashes)
        pattern: Single pattern to match
        is_dir: Whether the path is a directory
    
    Returns:
        True if pattern matches the path
    """
    # Handle directory-only patterns (e.g., "node_modules/")
    # These should match the directory itself AND any files inside
    if pattern.endswith('/'):
        dir_pattern = pattern.rstrip('/')
        
        # Check if path starts with this directory
        if path == dir_pattern:
            # Exact match - only if it's actually a directory
            return is_dir
        if path.startswith(dir_pattern + '/'):
            # Path is inside this directory - always match
            return True
        
        # Also check if any path component matches
        path_parts = path.split('/')
        if dir_pattern in path_parts:
            # Path contains this directory as a component
            idx = path_parts.index(dir_pattern)
            # If there's more after it, it's inside the dir
            if idx < len(path_parts) - 1:
                return True
            # If it's the last component, only match if it's a dir
            return is_dir
        
        return False
    
    # Normalize the pattern
    pattern = pattern.lstrip('./')
    
    # Handle ** (matches any path including nested)
    if '**' in pattern:
        # Convert ** to regex-compatible fnmatch
        # **/ at start means "anywhere in path"
        if pattern.startswith('**/'):
            # Match in any subdirectory
            suffix = pattern[3:]
            # Check if it matches at root or any subdir
            if fnmatch.fnmatch(path, suffix):
                return True
            if fnmatch.fnmatch(path, '*/' + suffix):
                return True
            # Match recursively
            parts = path.split('/')
            for i in range(len(parts)):
                subpath = '/'.join(parts[i:])
                if fnmatch.fnmatch(subpath, suffix):
                    return True
            return False
        
        # ** in middle of pattern
        # Simple approach: try matching with any number of path segments
        parts = pattern.split('**')
        if len(parts) == 2:
            prefix, suffix = parts
            prefix = prefix.rstrip('/')
            suffix = suffix.lstrip('/')
            
            # Path must match prefix at start and suffix at end
            if prefix:
                if not path.startswith(prefix) and not fnmatch.fnmatch(path.split('/')[0], prefix):
                    return False
            if suffix:
                if not fnmatch.fnmatch(path, '*' + suffix) and not fnmatch.fnmatch(path.split('/')[-1], suffix):
                    return False
            return True
    
    # Handle patterns without path separator (match anywhere)
    if '/' not in pattern:
        # Match against any component of the path
        if fnmatch.fnmatch(path, pattern):
            return True
        # Also try matching against just the filename
        basename = path.rsplit('/', 1)[-1]
        if fnmatch.fnmatch(basename, pattern):
            return True
        # Match as directory name anywhere in path
        for part in path.split('/'):
            if fnmatch.fnmatch(part, pattern):
                return True
        return False
    
    # Pattern with path separator - match from root
    return fnmatch.fnmatch(path, pattern)


def should_ignore(
    rel_path: str,
    patterns: List[str],
    is_dir: bool = False
) -> bool:
    """
    Determine if a path should be ignored based on patterns.
    
    Patterns are processed in order. Later patterns can override earlier ones.
    Negation patterns (starting with !) re-include previously excluded files.
    
    Args:
        rel_path: Relative path from project root
        patterns: List of patterns (from load_ignore_patterns)
        is_dir: Whether the path is a directory
    
    Returns:
        True if path should be ignored
    """
    # Normalize the path
    path = _normalize_path(rel_path)
    if is_dir and not path.endswith('/'):
        path_for_dir_check = path + '/'
    else:
        path_for_dir_check = path
    
    ignored = False
    
    for pattern in patterns:
        if not pattern:
            continue
            
        if pattern.startswith('!'):
            # Negation pattern - re-include if it matches
            neg_pattern = pattern[1:]
            if _match_pattern(path, neg_pattern, is_dir):
                ignored = False
            # Also check with trailing slash for directories
            if is_dir and _match_pattern(path_for_dir_check, neg_pattern, is_dir):
                ignored = False
        else:
            # Normal pattern - exclude if it matches
            if _match_pattern(path, pattern, is_dir):
                ignored = True
            # Also check with trailing slash for directories
            if is_dir and _match_pattern(path_for_dir_check, pattern, is_dir):
                ignored = True
    
    return ignored


def should_ignore_dir(rel_path: str, patterns: List[str]) -> bool:
    """
    Convenience function to check if a directory should be ignored.
    
    Args:
        rel_path: Relative path from project root
        patterns: List of patterns
    
    Returns:
        True if directory should be ignored
    """
    return should_ignore(rel_path, patterns, is_dir=True)


def filter_paths(
    paths: List[str],
    patterns: List[str],
    is_dir_fn: Optional[callable] = None
) -> List[str]:
    """
    Filter a list of paths, removing those that match ignore patterns.
    
    Args:
        paths: List of relative paths
        patterns: List of patterns
        is_dir_fn: Optional function to check if path is directory
    
    Returns:
        Filtered list of paths (non-ignored only)
    """
    result = []
    for path in paths:
        is_dir = is_dir_fn(path) if is_dir_fn else path.endswith('/')
        if not should_ignore(path, patterns, is_dir):
            result.append(path)
    return result
