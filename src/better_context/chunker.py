"""Code chunking for better-context.

Provides dual-mode parsing: regex fallback (zero deps) + optional tree-sitter.

This module implements the regex-based chunker that works with zero external
dependencies. It finds function/class boundaries using pattern matching.

Semantic Anchors:
    Chunks now include a 'semantic_anchor' field - a content-addressable ID
    based on normalized AST. This ID stays stable when code moves files.
    See semantic_anchor.py for the implementation details.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Pattern, Any

from .languages.base import (
    ChunkResult,
    ImportResult,
    ExportResult,
    ParseResult,
    generate_chunk_id,
)
from .semantic_anchor import compute_semantic_anchor


# ============================================================================
# Language Pattern Definitions
# ============================================================================

@dataclass
class ChunkPattern:
    """Pattern definition for detecting code chunks."""
    pattern: Pattern[str]
    chunk_type: str
    name_group: int = 1  # Which regex group contains the name


# Python patterns
PYTHON_PATTERNS: List[ChunkPattern] = [
    ChunkPattern(
        re.compile(r'^(\s*)(async\s+)?def\s+(\w+)\s*\('),
        'function',
        name_group=3
    ),
    ChunkPattern(
        re.compile(r'^(\s*)class\s+(\w+)'),
        'class',
        name_group=2
    ),
]

# TypeScript patterns (also works for JavaScript with some extras)
TYPESCRIPT_PATTERNS: List[ChunkPattern] = [
    # Function declarations
    ChunkPattern(
        re.compile(r'^\s*(?:export\s+)?(?:async\s+)?function\s+(\w+)'),
        'function',
        name_group=1
    ),
    # Class declarations
    ChunkPattern(
        re.compile(r'^\s*(?:export\s+)?(?:abstract\s+)?class\s+(\w+)'),
        'class',
        name_group=1
    ),
    # Interface declarations (TypeScript only)
    ChunkPattern(
        re.compile(r'^\s*(?:export\s+)?interface\s+(\w+)'),
        'interface',
        name_group=1
    ),
    # Type alias declarations (TypeScript only)
    ChunkPattern(
        re.compile(r'^\s*(?:export\s+)?type\s+(\w+)\s*='),
        'type',
        name_group=1
    ),
    # Arrow function assigned to const/let/var
    ChunkPattern(
        re.compile(r'^\s*(?:export\s+)?(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s+)?(?:\([^)]*\)|[a-zA-Z_]\w*)\s*(?::\s*[^=]+)?\s*=>'),
        'function',
        name_group=1
    ),
    # Function expression assigned to const/let/var
    ChunkPattern(
        re.compile(r'^\s*(?:export\s+)?(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s+)?function'),
        'function',
        name_group=1
    ),
]

# JavaScript patterns (subset of TypeScript without interface/type)
JAVASCRIPT_PATTERNS: List[ChunkPattern] = [
    TYPESCRIPT_PATTERNS[0],  # function
    TYPESCRIPT_PATTERNS[1],  # class
    TYPESCRIPT_PATTERNS[4],  # arrow function
    TYPESCRIPT_PATTERNS[5],  # function expression
]

# Go patterns
GO_PATTERNS: List[ChunkPattern] = [
    # Regular function
    ChunkPattern(
        re.compile(r'^func\s+(\w+)\s*\('),
        'function',
        name_group=1
    ),
    # Method (with receiver)
    ChunkPattern(
        re.compile(r'^func\s+\(\w+\s+\*?(\w+)\)\s+(\w+)\s*\('),
        'method',
        name_group=2
    ),
    # Struct definition
    ChunkPattern(
        re.compile(r'^type\s+(\w+)\s+struct\s*\{'),
        'struct',
        name_group=1
    ),
    # Interface definition
    ChunkPattern(
        re.compile(r'^type\s+(\w+)\s+interface\s*\{'),
        'interface',
        name_group=1
    ),
]

# Language pattern registry
LANGUAGE_PATTERNS: Dict[str, List[ChunkPattern]] = {
    'python': PYTHON_PATTERNS,
    'typescript': TYPESCRIPT_PATTERNS,
    'javascript': JAVASCRIPT_PATTERNS,
    'go': GO_PATTERNS,
}


# ============================================================================
# Import Pattern Definitions
# ============================================================================

PYTHON_IMPORT_PATTERNS = [
    # import module
    re.compile(r'^import\s+(\w+(?:\.\w+)*)(?:\s+as\s+(\w+))?'),
    # from module import ...
    re.compile(r'^from\s+(\.{0,2}\w+(?:\.\w+)*)\s+import\s+(.+)'),
]

TYPESCRIPT_IMPORT_PATTERNS = [
    # import X from 'module'
    # import { X, Y } from 'module'
    # import * as X from 'module'
    # import 'module'
    re.compile(r'''import\s+(?:type\s+)?(?:(\w+)|(?:\{([^}]+)\})|(?:\*\s+as\s+(\w+)))?\s*(?:,\s*\{([^}]+)\})?\s*(?:from\s+)?['"]([^'"]+)['"]'''),
]

GO_IMPORT_PATTERNS = [
    # Single import: import "fmt"
    re.compile(r'^import\s+(?:(\w+)\s+)?["]([^"]+)["]'),
    # Group import line: "fmt" or alias "pkg"
    re.compile(r'^\s*(?:(\w+|\.)\s+)?["]([^"]+)["]'),
]


# ============================================================================
# Chunking Algorithm
# ============================================================================

@dataclass
class ChunkMarker:
    """Marker for a detected chunk start."""
    line: int  # 1-based line number
    name: str
    chunk_type: str
    indent: int
    is_exported: bool = False
    signature: str = ""


def detect_indent(line: str) -> int:
    """Get the indentation level of a line."""
    return len(line) - len(line.lstrip())


def is_python_exported(name: str, all_list: Optional[List[str]]) -> bool:
    """Check if a Python symbol is exported.
    
    Python exports are determined by:
    1. Presence in __all__ list
    2. Not starting with underscore (convention)
    """
    if all_list is not None:
        return name in all_list
    return not name.startswith('_')


def is_js_exported(line: str) -> bool:
    """Check if a JS/TS line has an export keyword."""
    return 'export' in line.split('//')[0]  # Ignore comments


def is_go_exported(name: str) -> bool:
    """Check if a Go symbol is exported (starts with capital letter)."""
    return name[0].isupper() if name else False


def extract_python_all(source: str) -> Optional[List[str]]:
    """Extract __all__ list from Python source."""
    match = re.search(r'__all__\s*=\s*\[([^\]]+)\]', source)
    if match:
        content = match.group(1)
        # Extract quoted strings
        return re.findall(r'["\'](\w+)["\']', content)
    return None


def find_python_block_end(lines: List[str], start_line: int, start_indent: int) -> int:
    """Find the end of a Python block by tracking indentation.
    
    Args:
        lines: All source lines (0-indexed)
        start_line: 1-based line number where block starts
        start_indent: Indentation level of the block definition
        
    Returns:
        1-based line number of the block end
    """
    # Skip the definition line and any continuation
    idx = start_line - 1  # Convert to 0-indexed
    
    # Skip to the first line of the body (might be on same line for simple funcs)
    # or handle multi-line signatures
    while idx < len(lines):
        line = lines[idx]
        if ':' in line and not line.strip().startswith('#'):
            break
        idx += 1
    
    # Find the end by tracking indentation
    idx += 1
    body_indent = None
    
    while idx < len(lines):
        line = lines[idx]
        stripped = line.strip()
        
        # Skip empty lines and comments
        if not stripped or stripped.startswith('#'):
            idx += 1
            continue
        
        current_indent = detect_indent(line)
        
        # Set body indent from first real line
        if body_indent is None:
            body_indent = current_indent
        
        # Block ends when we return to or below the start indent
        if current_indent <= start_indent:
            return idx  # Return 1-based
        
        idx += 1
    
    return len(lines)  # End of file


def find_brace_block_end(lines: List[str], start_line: int) -> int:
    """Find the end of a brace-delimited block.
    
    Used for C-like languages (JS/TS/Go).
    
    Args:
        lines: All source lines (0-indexed)
        start_line: 1-based line number where block starts
        
    Returns:
        1-based line number of the closing brace
    """
    brace_count = 0
    in_string = False
    string_char = None
    
    for idx in range(start_line - 1, len(lines)):
        line = lines[idx]
        i = 0
        
        while i < len(line):
            char = line[i]
            
            # Handle strings
            if char in '"\'`' and (i == 0 or line[i-1] != '\\'):
                if not in_string:
                    in_string = True
                    string_char = char
                elif char == string_char:
                    in_string = False
                    string_char = None
            
            # Handle braces outside strings
            if not in_string:
                if char == '{':
                    brace_count += 1
                elif char == '}':
                    brace_count -= 1
                    if brace_count == 0:
                        return idx + 1  # 1-based
            
            i += 1
    
    return len(lines)


def extract_signature(lines: List[str], line_num: int, language: str) -> str:
    """Extract the function/class signature from source.
    
    Args:
        lines: All source lines (0-indexed)
        line_num: 1-based line number
        language: Language identifier
        
    Returns:
        Signature string for display
    """
    if line_num < 1 or line_num > len(lines):
        return ""
    
    idx = line_num - 1
    first_line = lines[idx].strip()
    
    if language == 'python':
        # Handle multi-line signatures
        sig_lines = [first_line]
        while not sig_lines[-1].rstrip().endswith(':') and idx + 1 < len(lines):
            idx += 1
            sig_lines.append(lines[idx].strip())
        return ' '.join(sig_lines).rstrip(':')
    
    elif language in ('typescript', 'javascript'):
        # Usually single line for function signature
        # Strip the body if it starts on same line
        if '{' in first_line:
            return first_line[:first_line.index('{')].strip()
        return first_line
    
    elif language == 'go':
        # Go signatures end at opening brace
        if '{' in first_line:
            return first_line[:first_line.index('{')].strip()
        return first_line
    
    return first_line


def extract_docstring(lines: List[str], line_num: int, language: str) -> Optional[str]:
    """Extract docstring/doc comment for a definition.
    
    Args:
        lines: All source lines (0-indexed)
        line_num: 1-based line number of the definition
        language: Language identifier
        
    Returns:
        Docstring text or None
    """
    if language == 'python':
        # Python docstring comes after the def/class line
        idx = line_num  # 0-indexed line after def
        while idx < len(lines):
            line = lines[idx].strip()
            if line.startswith('"""') or line.startswith("'''"):
                quote = line[:3]
                if line.endswith(quote) and len(line) > 6:
                    return line[3:-3].strip()
                # Multi-line
                doc_lines = [line[3:]]
                idx += 1
                while idx < len(lines):
                    line = lines[idx]
                    if quote in line:
                        doc_lines.append(line[:line.index(quote)])
                        break
                    doc_lines.append(line.strip())
                    idx += 1
                return '\n'.join(doc_lines).strip()
            elif line and not line.startswith('#'):
                break
            idx += 1
    
    elif language in ('typescript', 'javascript'):
        # JSDoc comes before the definition
        if line_num >= 2:
            idx = line_num - 2  # 0-indexed, line before
            if idx >= 0 and lines[idx].strip().endswith('*/'):
                # Find start of JSDoc
                doc_lines = []
                while idx >= 0:
                    line = lines[idx]
                    doc_lines.insert(0, line)
                    if '/**' in line:
                        break
                    idx -= 1
                # Parse JSDoc
                text = '\n'.join(doc_lines)
                text = text.replace('/**', '').replace('*/', '')
                text = '\n'.join(
                    line.strip().lstrip('*').strip()
                    for line in text.split('\n')
                )
                return text.strip() or None
    
    elif language == 'go':
        # Go doc comments are // before the definition
        if line_num >= 2:
            doc_lines = []
            idx = line_num - 2  # 0-indexed, line before
            while idx >= 0:
                line = lines[idx].strip()
                if line.startswith('//'):
                    doc_lines.insert(0, line[2:].strip())
                    idx -= 1
                else:
                    break
            if doc_lines:
                return '\n'.join(doc_lines)
    
    return None


def chunk_file_regex(
    path: str,
    source: str,
    language: str,
    max_lines: int = 150,
) -> ParseResult:
    """Parse source code using regex patterns.
    
    This is the zero-dependency fallback parser. It uses regular expressions
    to find function/class boundaries.
    
    Args:
        path: File path (for ID generation)
        source: File contents
        language: Language identifier
        max_lines: Maximum lines per chunk (for splitting large ones)
        
    Returns:
        ParseResult containing chunks, imports, exports, and errors
    """
    patterns = LANGUAGE_PATTERNS.get(language, [])
    if not patterns:
        return ParseResult(errors=[f"No patterns defined for language: {language}"])
    
    lines = source.split('\n')
    chunks: List[ChunkResult] = []
    imports: List[ImportResult] = []
    exports: List[ExportResult] = []
    errors: List[str] = []
    
    # Extract __all__ for Python export detection
    python_all = extract_python_all(source) if language == 'python' else None
    
    # Pass 1: Find all chunk markers
    markers: List[ChunkMarker] = []
    
    for i, line in enumerate(lines):
        line_num = i + 1  # 1-based
        
        for chunk_pattern in patterns:
            match = chunk_pattern.pattern.match(line)
            if match:
                name = match.group(chunk_pattern.name_group)
                indent = detect_indent(line)
                
                # Determine if exported
                if language == 'python':
                    is_exported = is_python_exported(name, python_all)
                elif language in ('typescript', 'javascript'):
                    is_exported = is_js_exported(line)
                elif language == 'go':
                    is_exported = is_go_exported(name)
                else:
                    is_exported = True
                
                markers.append(ChunkMarker(
                    line=line_num,
                    name=name,
                    chunk_type=chunk_pattern.chunk_type,
                    indent=indent,
                    is_exported=is_exported,
                    signature=extract_signature(lines, line_num, language),
                ))
                break  # Only match first pattern per line
    
    # Pass 2: Determine chunk boundaries
    for i, marker in enumerate(markers):
        # Find end line
        if language == 'python':
            end_line = find_python_block_end(lines, marker.line, marker.indent)
        else:
            end_line = find_brace_block_end(lines, marker.line)
        
        # Clamp to not exceed next marker
        if i + 1 < len(markers):
            next_start = markers[i + 1].line
            if end_line >= next_start:
                end_line = next_start - 1
        
        # Clamp to file bounds
        end_line = min(end_line, len(lines))
        
        # Extract docstring
        docstring = extract_docstring(lines, marker.line, language)
        
        # Compute semantic anchor (content-addressable ID)
        semantic_anchor = compute_semantic_anchor(
            source=source,
            start_line=marker.line,
            end_line=end_line,
            language=language,
            name=marker.name,
            chunk_type=marker.chunk_type,
        )
        
        # Create chunk
        chunk = ChunkResult(
            id=generate_chunk_id(path, marker.line, marker.chunk_type, marker.name),
            type=marker.chunk_type,
            name=marker.name,
            signature=marker.signature,
            start_line=marker.line,
            end_line=end_line,
            parent=None,  # Regex mode doesn't track nesting well
            exported=marker.is_exported,
            docstring=docstring,
            metadata={
                'indent': marker.indent,
            },
            semantic_anchor=semantic_anchor,
        )
        chunks.append(chunk)
        
        # Also record as export if exported
        if marker.is_exported:
            exports.append(ExportResult(
                name=marker.name,
                type=marker.chunk_type,
                line=marker.line,
                is_default=False,
            ))
    
    # Pass 3: Extract imports
    imports = extract_imports_regex(lines, language)
    
    return ParseResult(
        chunks=chunks,
        imports=imports,
        exports=exports,
        errors=errors,
    )


def extract_imports_regex(lines: List[str], language: str) -> List[ImportResult]:
    """Extract import statements using regex.
    
    Args:
        lines: Source lines (0-indexed)
        language: Language identifier
        
    Returns:
        List of ImportResult
    """
    imports: List[ImportResult] = []
    
    if language == 'python':
        for i, line in enumerate(lines):
            stripped = line.strip()
            
            # import module
            match = re.match(r'^import\s+(\w+(?:\.\w+)*)(?:\s+as\s+(\w+))?', stripped)
            if match:
                imports.append(ImportResult(
                    module=match.group(1),
                    symbols=[],
                    alias=match.group(2),
                    is_relative=False,
                    line=i + 1,
                ))
                continue
            
            # from module import ...
            match = re.match(r'^from\s+(\.+)?(\w+(?:\.\w+)*)\s+import\s+(.+)', stripped)
            if match:
                prefix = match.group(1) or ''
                module = match.group(2)
                symbols_str = match.group(3)
                
                # Parse symbols
                symbols = []
                for sym in symbols_str.split(','):
                    sym = sym.strip()
                    if ' as ' in sym:
                        sym = sym.split(' as ')[0].strip()
                    if sym and sym != '*':
                        symbols.append(sym)
                
                imports.append(ImportResult(
                    module=prefix + module,
                    symbols=symbols,
                    is_relative=bool(prefix),
                    line=i + 1,
                ))
    
    elif language in ('typescript', 'javascript'):
        for i, line in enumerate(lines):
            stripped = line.strip()
            if not stripped.startswith('import'):
                continue
            
            # Try to match import statement
            # import X from 'module'
            match = re.search(r'''import\s+(\w+)\s+from\s+['"]([^'"]+)['"]''', stripped)
            if match:
                imports.append(ImportResult(
                    module=match.group(2),
                    symbols=[match.group(1)],
                    is_relative=match.group(2).startswith('.'),
                    line=i + 1,
                ))
                continue
            
            # import { X, Y } from 'module'
            match = re.search(r'''import\s+\{([^}]+)\}\s+from\s+['"]([^'"]+)['"]''', stripped)
            if match:
                symbols = [s.strip().split(' as ')[0].strip() 
                          for s in match.group(1).split(',')]
                imports.append(ImportResult(
                    module=match.group(2),
                    symbols=symbols,
                    is_relative=match.group(2).startswith('.'),
                    line=i + 1,
                ))
                continue
            
            # import * as X from 'module'
            match = re.search(r'''import\s+\*\s+as\s+(\w+)\s+from\s+['"]([^'"]+)['"]''', stripped)
            if match:
                imports.append(ImportResult(
                    module=match.group(2),
                    symbols=[],
                    alias=match.group(1),
                    is_relative=match.group(2).startswith('.'),
                    line=i + 1,
                ))
                continue
            
            # import 'module' (side effect)
            match = re.search(r'''import\s+['"]([^'"]+)['"]''', stripped)
            if match:
                imports.append(ImportResult(
                    module=match.group(1),
                    symbols=[],
                    is_relative=match.group(1).startswith('.'),
                    line=i + 1,
                ))
    
    elif language == 'go':
        in_import_block = False
        
        for i, line in enumerate(lines):
            stripped = line.strip()
            
            # Single import
            match = re.match(r'^import\s+(?:(\w+)\s+)?["]([^"]+)["]', stripped)
            if match:
                imports.append(ImportResult(
                    module=match.group(2),
                    symbols=[],
                    alias=match.group(1),
                    is_relative=False,
                    line=i + 1,
                ))
                continue
            
            # Import block start
            if stripped == 'import (':
                in_import_block = True
                continue
            
            # Import block end
            if in_import_block and stripped == ')':
                in_import_block = False
                continue
            
            # Import block line
            if in_import_block:
                match = re.match(r'^\s*(?:(\w+|\.)\s+)?["]([^"]+)["]', stripped)
                if match:
                    imports.append(ImportResult(
                        module=match.group(2),
                        symbols=[],
                        alias=match.group(1) if match.group(1) != '.' else None,
                        is_relative=False,
                        line=i + 1,
                    ))
    
    return imports


# ============================================================================
# Public API
# ============================================================================

def parse_file(
    path: str,
    source: str,
    language: str,
    use_ast: bool = False,
) -> ParseResult:
    """Parse a source file and extract chunks, imports, exports.
    
    Args:
        path: File path (for ID generation)
        source: File contents
        language: Language identifier
        use_ast: If True, try tree-sitter (falls back to regex if unavailable)
        
    Returns:
        ParseResult containing chunks, imports, exports, and errors
    """
    # For now, always use regex (tree-sitter support to be added later)
    return chunk_file_regex(path, source, language)


__all__ = [
    'chunk_file_regex',
    'parse_file',
    'extract_imports_regex',
    'LANGUAGE_PATTERNS',
]
