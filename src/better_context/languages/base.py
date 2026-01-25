"""Base language adapter interface for better-context.

This module defines:
1. The Protocol/interface that all language adapters must implement
2. Result dataclasses for parse outputs (chunks, imports, exports)
3. Common utilities shared by all adapters
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any, TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Protocol
else:
    # For runtime, use Protocol from typing_extensions for Python 3.9 compat
    try:
        from typing import Protocol
    except ImportError:
        from typing_extensions import Protocol


@dataclass
class ChunkResult:
    """Represents a semantic code unit (function, class, method, etc.).
    
    Attributes:
        id: Unique identifier in format 'path:line:type:name'
        type: Chunk type (function, class, method, interface, type, variable)
        name: Symbol name
        signature: Full signature for display
        start_line: 1-based start line number
        end_line: 1-based end line number
        parent: Parent chunk ID (for nested constructs like methods in class)
        exported: Whether this symbol is exported/public
        docstring: Extracted docstring/doc comment if present
        metadata: Language-specific extras (decorators, async, static, etc.)
        semantic_anchor: Content-addressable ID based on normalized AST.
            This stays stable when code moves files. Format: 16-char hex string.
            See semantic_anchor.py for details.
    """
    id: str
    type: str
    name: str
    signature: str
    start_line: int
    end_line: int
    parent: Optional[str] = None
    exported: bool = False
    docstring: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    semantic_anchor: Optional[str] = None
    
    @property
    def char_count(self) -> int:
        """Estimate character count from line count (rough estimate)."""
        # Approximate 40 chars per line
        return (self.end_line - self.start_line + 1) * 40
    
    @property
    def line_count(self) -> int:
        """Number of lines in this chunk."""
        return self.end_line - self.start_line + 1


@dataclass
class ImportResult:
    """Represents an import statement.
    
    Attributes:
        module: Imported module/path (e.g., 'os', './utils', '@pkg/lib')
        symbols: List of imported symbols (empty means import entire module)
        alias: Import alias (e.g., 'np' for 'import numpy as np')
        is_relative: True for relative imports (./utils, ../models)
        line: Line number where import appears
        is_type_only: True for TypeScript 'import type' statements
        is_dynamic: True for dynamic imports (import())
    """
    module: str
    symbols: List[str] = field(default_factory=list)
    alias: Optional[str] = None
    is_relative: bool = False
    line: int = 0
    is_type_only: bool = False
    is_dynamic: bool = False


@dataclass
class ExportResult:
    """Represents an export statement.
    
    Attributes:
        name: Exported symbol name
        type: Symbol type (function, class, variable, type, interface)
        line: Line number where export appears
        is_default: True for default exports (JS/TS)
        is_reexport: True if re-exporting from another module
        source_module: Source module for re-exports
    """
    name: str
    type: str
    line: int = 0
    is_default: bool = False
    is_reexport: bool = False
    source_module: Optional[str] = None


@dataclass
class ParseResult:
    """Result of parsing a source file.
    
    Attributes:
        chunks: List of code chunks (functions, classes, etc.)
        imports: List of import statements
        exports: List of export statements
        errors: List of non-fatal parse errors (for diagnostics)
    """
    chunks: List[ChunkResult] = field(default_factory=list)
    imports: List[ImportResult] = field(default_factory=list)
    exports: List[ExportResult] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    
    @property
    def has_errors(self) -> bool:
        """Check if there were any parse errors."""
        return len(self.errors) > 0
    
    def get_chunks_by_type(self, chunk_type: str) -> List[ChunkResult]:
        """Get all chunks of a specific type."""
        return [c for c in self.chunks if c.type == chunk_type]
    
    def get_exported_chunks(self) -> List[ChunkResult]:
        """Get all exported/public chunks."""
        return [c for c in self.chunks if c.exported]


class LanguageAdapter(Protocol):
    """Protocol for language-specific parsing adapters.
    
    All language adapters must implement this interface.
    Use Protocol for structural typing (duck typing with type hints).
    
    Example implementation:
        class PythonAdapter:
            @property
            def language(self) -> str:
                return 'python'
            
            @property
            def extensions(self) -> List[str]:
                return ['.py', '.pyi', '.pyw']
            
            def parse_file(self, path: str, source: str) -> ParseResult:
                # Implementation here
                ...
            
            def supports_ast(self) -> bool:
                return False  # or True if tree-sitter available
    """
    
    @property
    def language(self) -> str:
        """Return language identifier (e.g., 'python', 'typescript').
        
        This should match the keys in EXTENSION_TO_LANGUAGE.
        """
        ...
    
    @property
    def extensions(self) -> List[str]:
        """Return list of supported file extensions (including the dot).
        
        Example: ['.py', '.pyi', '.pyw']
        """
        ...
    
    def parse_file(self, path: str, source: str) -> ParseResult:
        """Parse source code and extract chunks, imports, exports.
        
        Args:
            path: File path (used for generating chunk IDs)
            source: File contents as string
            
        Returns:
            ParseResult containing chunks, imports, exports, and any errors
        
        Notes:
            - This should not raise exceptions for parse errors
            - Instead, add error messages to ParseResult.errors
            - Always return a ParseResult, even if empty
        """
        ...
    
    def supports_ast(self) -> bool:
        """Return True if tree-sitter AST parsing is available.
        
        Returns:
            True if the adapter can use tree-sitter for enhanced parsing,
            False if only regex-based parsing is available.
        """
        ...


def generate_chunk_id(path: str, line: int, chunk_type: str, name: str) -> str:
    """Generate a stable, unique chunk ID.
    
    Format: 'path:line:type:name'
    
    Args:
        path: Relative file path
        line: 1-based line number
        chunk_type: Chunk type (function, class, etc.)
        name: Symbol name
        
    Returns:
        Unique identifier string
    """
    return f"{path}:{line}:{chunk_type}:{name}"


def extract_first_line(source: str, start_line: int) -> str:
    """Extract a single line from source by line number (1-based).
    
    Args:
        source: Full source code
        start_line: 1-based line number
        
    Returns:
        The line content (stripped of trailing newline)
    """
    lines = source.split("\n")
    if 1 <= start_line <= len(lines):
        return lines[start_line - 1]
    return ""


def extract_docstring_after_line(
    source: str,
    start_line: int,
    language: str
) -> Optional[str]:
    """Extract docstring/doc comment after a definition line.
    
    Args:
        source: Full source code
        start_line: Line number of the definition (1-based)
        language: Language identifier for syntax-specific handling
        
    Returns:
        Docstring content or None if not found
    """
    lines = source.split("\n")
    if start_line >= len(lines):
        return None
    
    # Look at the line after the definition
    next_line_idx = start_line  # 0-based index of line after start_line
    if next_line_idx >= len(lines):
        return None
    
    next_line = lines[next_line_idx].strip()
    
    if language == "python":
        # Python docstrings: triple quotes
        if next_line.startswith('"""') or next_line.startswith("'''"):
            quote = next_line[:3]
            # Check for single-line docstring
            if next_line.endswith(quote) and len(next_line) > 6:
                return next_line[3:-3].strip()
            # Multi-line docstring
            docstring_lines = [next_line[3:]]
            for line in lines[next_line_idx + 1:]:
                if quote in line:
                    docstring_lines.append(line[:line.index(quote)])
                    break
                docstring_lines.append(line)
            return "\n".join(docstring_lines).strip()
    
    elif language in ("typescript", "javascript"):
        # Check for JSDoc comment above the definition
        if start_line >= 2:
            prev_line = lines[start_line - 2].strip()  # -2 because 1-based and we want line before
            if prev_line.endswith("*/"):
                # Find start of JSDoc
                doc_lines = []
                for i in range(start_line - 2, -1, -1):
                    line = lines[i]
                    doc_lines.insert(0, line)
                    if "/**" in line:
                        break
                # Parse JSDoc
                doc_text = "\n".join(doc_lines)
                # Strip comment markers
                doc_text = doc_text.replace("/**", "").replace("*/", "")
                doc_text = "\n".join(
                    line.strip().lstrip("*").strip() 
                    for line in doc_text.split("\n")
                )
                return doc_text.strip() or None
    
    elif language == "go":
        # Go doc comments are // comments above the definition
        if start_line >= 2:
            doc_lines = []
            for i in range(start_line - 2, -1, -1):
                line = lines[i].strip()
                if line.startswith("//"):
                    doc_lines.insert(0, line[2:].strip())
                else:
                    break
            if doc_lines:
                return "\n".join(doc_lines)
    
    return None


# Export public API
__all__ = [
    # Dataclasses
    "ChunkResult",
    "ImportResult",
    "ExportResult",
    "ParseResult",
    # Protocol
    "LanguageAdapter",
    # Utilities
    "generate_chunk_id",
    "extract_first_line",
    "extract_docstring_after_line",
]
