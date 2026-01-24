"""Language detection and adapter registry for better-context.

This module provides:
1. Language detection from file extensions
2. Shebang detection for extensionless files
3. Config-based extension overrides
4. Adapter registry for language-specific parsers
5. Base adapter interface and result types (from base.py)
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional, TYPE_CHECKING, Any

# Import base types for re-export
from .base import (
    ChunkResult,
    ImportResult,
    ExportResult,
    ParseResult,
    LanguageAdapter,
    generate_chunk_id,
    extract_first_line,
    extract_docstring_after_line,
)


# Extension to language mapping
# Organized by language family for clarity
EXTENSION_TO_LANGUAGE: Dict[str, str] = {
    # Python
    ".py": "python",
    ".pyi": "python",
    ".pyw": "python",
    
    # TypeScript/JavaScript
    ".ts": "typescript",
    ".tsx": "typescript",
    ".mts": "typescript",
    ".cts": "typescript",
    ".js": "javascript",
    ".jsx": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    
    # Go
    ".go": "go",
    
    # Rust
    ".rs": "rust",
    
    # Java/Kotlin
    ".java": "java",
    ".kt": "kotlin",
    ".kts": "kotlin",
    
    # Ruby
    ".rb": "ruby",
    ".rake": "ruby",
    
    # PHP
    ".php": "php",
    
    # C/C++
    ".c": "c",
    ".h": "c",
    ".cpp": "cpp",
    ".hpp": "cpp",
    ".cc": "cpp",
    ".cxx": "cpp",
    ".hxx": "cpp",
    
    # C#
    ".cs": "csharp",
    
    # Swift
    ".swift": "swift",
    
    # Shell
    ".sh": "shell",
    ".bash": "shell",
    ".zsh": "shell",
    
    # Data/Config formats
    ".json": "json",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".toml": "toml",
    ".xml": "xml",
    ".md": "markdown",
    ".markdown": "markdown",
    ".rst": "rst",
    
    # Web
    ".html": "html",
    ".htm": "html",
    ".css": "css",
    ".scss": "scss",
    ".sass": "sass",
    ".less": "less",
    ".vue": "vue",
    ".svelte": "svelte",
}

# Languages we have full parsing support for (adapters implemented)
SUPPORTED_LANGUAGES: List[str] = [
    "python",
    "typescript",
    "javascript",
    "go",
]

# Shebang patterns for extensionless file detection
SHEBANG_PATTERNS: Dict[str, str] = {
    "python": "python",
    "python3": "python",
    "node": "javascript",
    "nodejs": "javascript",
    "deno": "typescript",
    "bash": "shell",
    "sh": "shell",
    "zsh": "shell",
    "ruby": "ruby",
    "perl": "perl",
    "php": "php",
}


def detect_language(
    path: Path,
    config: Optional[Any] = None,
    source: Optional[str] = None
) -> Optional[str]:
    """Detect programming language from file path and optionally content.
    
    Detection order:
    1. Config overrides (if provided)
    2. Extension mapping
    3. Shebang detection (if source provided or file exists)
    
    Args:
        path: Path to the file
        config: Optional config with language_overrides dict
        source: Optional file content (for shebang detection without reading file)
        
    Returns:
        Language identifier string, or None if undetected
    """
    ext = path.suffix.lower()
    
    # 1. Check config overrides first
    if config is not None:
        overrides = getattr(config, "language_overrides", None)
        if overrides and ext in overrides:
            return overrides[ext]
    
    # 2. Check extension mapping
    if ext in EXTENSION_TO_LANGUAGE:
        return EXTENSION_TO_LANGUAGE[ext]
    
    # 3. Try shebang detection for extensionless files
    if not ext:
        return detect_from_shebang(path, source)
    
    return None


def detect_from_shebang(
    path: Path,
    source: Optional[str] = None
) -> Optional[str]:
    """Detect language from shebang line.
    
    Handles formats:
    - #!/usr/bin/python
    - #!/usr/bin/env python
    - #!/bin/bash
    
    Args:
        path: Path to the file (used if source not provided)
        source: Optional file content
        
    Returns:
        Language identifier or None
    """
    first_line: Optional[str] = None
    
    if source is not None:
        # Get first line from provided source
        newline_idx = source.find("\n")
        first_line = source[:newline_idx] if newline_idx != -1 else source
    elif path.exists():
        # Read first line from file
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                first_line = f.readline()
        except (OSError, IOError):
            return None
    
    if not first_line or not first_line.startswith("#!"):
        return None
    
    # Parse shebang: #!/usr/bin/env python3 or #!/usr/bin/python
    shebang = first_line[2:].strip()
    
    # Handle "env" style: /usr/bin/env python
    parts = shebang.split()
    if not parts:
        return None
    
    # Get the actual interpreter (last path component, ignoring env)
    interpreter = parts[-1] if "env" in parts[0] and len(parts) > 1 else parts[0]
    interpreter = interpreter.split("/")[-1]  # Get basename
    
    # Remove version numbers: python3.10 -> python3 -> python
    for pattern, lang in SHEBANG_PATTERNS.items():
        if interpreter.startswith(pattern):
            return lang
    
    return None


def is_supported_language(language: str) -> bool:
    """Check if a language has full parsing support.
    
    Args:
        language: Language identifier
        
    Returns:
        True if we have an adapter for this language
    """
    return language in SUPPORTED_LANGUAGES


def get_extensions_for_language(language: str) -> List[str]:
    """Get all file extensions associated with a language.
    
    Args:
        language: Language identifier
        
    Returns:
        List of extensions (including the dot)
    """
    return [ext for ext, lang in EXTENSION_TO_LANGUAGE.items() if lang == language]


def get_all_supported_extensions() -> List[str]:
    """Get all extensions for languages with full parsing support.
    
    Returns:
        List of extensions (including the dot)
    """
    extensions: List[str] = []
    for lang in SUPPORTED_LANGUAGES:
        extensions.extend(get_extensions_for_language(lang))
    return extensions


# Adapter registry (populated by language adapter modules)
# This will be filled in by base.py and individual adapter modules
_adapters: Dict[str, "LanguageAdapter"] = {}


def register_adapter(adapter: "LanguageAdapter") -> None:
    """Register a language adapter.
    
    Args:
        adapter: Adapter instance implementing LanguageAdapter protocol
    """
    _adapters[adapter.language] = adapter


def get_adapter(language: str) -> Optional["LanguageAdapter"]:
    """Get the adapter for a language.
    
    Args:
        language: Language identifier
        
    Returns:
        Adapter instance or None if not registered
    """
    return _adapters.get(language)


def get_adapter_for_file(
    path: Path,
    config: Optional[Any] = None,
    source: Optional[str] = None
) -> Optional["LanguageAdapter"]:
    """Get the appropriate adapter for a file.
    
    Convenience function combining detect_language and get_adapter.
    
    Args:
        path: Path to the file
        config: Optional config with language_overrides
        source: Optional file content
        
    Returns:
        Adapter instance or None
    """
    language = detect_language(path, config, source)
    if language is None:
        return None
    return get_adapter(language)


# Export public API
__all__ = [
    # Detection functions
    "detect_language",
    "detect_from_shebang",
    "is_supported_language",
    # Extension queries
    "get_extensions_for_language",
    "get_all_supported_extensions",
    # Adapter registry
    "register_adapter",
    "get_adapter",
    "get_adapter_for_file",
    # Constants
    "EXTENSION_TO_LANGUAGE",
    "SUPPORTED_LANGUAGES",
    "SHEBANG_PATTERNS",
    # Base types (from base.py)
    "ChunkResult",
    "ImportResult",
    "ExportResult",
    "ParseResult",
    "LanguageAdapter",
    "generate_chunk_id",
    "extract_first_line",
    "extract_docstring_after_line",
]


# ============================================================================
# Auto-register language adapters
# ============================================================================
# Import adapters at the end to avoid circular import issues.
# Each adapter module calls register_adapter() when imported.

def _load_adapters() -> None:
    """Load and register all available language adapters."""
    try:
        from . import typescript  # noqa: F401
    except ImportError:
        pass
    
    try:
        from . import python  # noqa: F401
    except ImportError:
        pass
    
    try:
        from . import go  # noqa: F401
    except ImportError:
        pass


# Load adapters on module import
_load_adapters()
