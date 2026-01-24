"""TypeScript and JavaScript language adapters for better-context.

Provides parsing adapters for TypeScript (.ts, .tsx) and JavaScript (.js, .jsx)
with shared base functionality for ECMAScript-family languages.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, List, Optional, Pattern

from .base import (
    ChunkResult,
    ImportResult,
    ExportResult,
    ParseResult,
    generate_chunk_id,
)
from . import register_adapter


# ============================================================================
# Patterns for TypeScript/JavaScript
# ============================================================================

@dataclass
class TSChunkPattern:
    """Pattern for detecting TypeScript/JS code chunks."""
    pattern: Pattern[str]
    chunk_type: str
    name_group: int = 1


# Shared patterns for both TypeScript and JavaScript
ECMASCRIPT_PATTERNS: List[TSChunkPattern] = [
    # Function declarations: function foo() or async function foo()
    TSChunkPattern(
        re.compile(r'^\s*(?:export\s+)?(?:async\s+)?function\s+(\w+)'),
        'function',
        name_group=1
    ),
    # Class declarations
    TSChunkPattern(
        re.compile(r'^\s*(?:export\s+)?(?:abstract\s+)?class\s+(\w+)'),
        'class',
        name_group=1
    ),
    # Arrow function assigned to const/let/var
    TSChunkPattern(
        re.compile(
            r'^\s*(?:export\s+)?(?:const|let|var)\s+(\w+)\s*'
            r'(?::\s*[^=]+)?\s*=\s*(?:async\s+)?'
            r'(?:\([^)]*\)|[a-zA-Z_]\w*)\s*(?::\s*[^=]+)?\s*=>'
        ),
        'function',
        name_group=1
    ),
    # Function expression: const foo = function() {}
    TSChunkPattern(
        re.compile(
            r'^\s*(?:export\s+)?(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s+)?function'
        ),
        'function',
        name_group=1
    ),
]

# TypeScript-only patterns
TYPESCRIPT_ONLY_PATTERNS: List[TSChunkPattern] = [
    # Interface declarations
    TSChunkPattern(
        re.compile(r'^\s*(?:export\s+)?interface\s+(\w+)'),
        'interface',
        name_group=1
    ),
    # Type alias declarations
    TSChunkPattern(
        re.compile(r'^\s*(?:export\s+)?type\s+(\w+)\s*(?:<[^>]+>)?\s*='),
        'type',
        name_group=1
    ),
    # Enum declarations
    TSChunkPattern(
        re.compile(r'^\s*(?:export\s+)?(?:const\s+)?enum\s+(\w+)'),
        'enum',
        name_group=1
    ),
]


# ============================================================================
# Import/Export Patterns
# ============================================================================

# Import patterns (work for both TS and JS)
IMPORT_PATTERNS = [
    # import X from 'module'
    re.compile(r'''import\s+(\w+)\s+from\s+['"]([^'"]+)['"]'''),
    # import { X, Y } from 'module'
    re.compile(r'''import\s+\{([^}]+)\}\s+from\s+['"]([^'"]+)['"]'''),
    # import * as X from 'module'
    re.compile(r'''import\s+\*\s+as\s+(\w+)\s+from\s+['"]([^'"]+)['"]'''),
    # import 'module' (side effect)
    re.compile(r'''import\s+['"]([^'"]+)['"]'''),
    # import X, { Y, Z } from 'module' (combined default + named)
    re.compile(r'''import\s+(\w+)\s*,\s*\{([^}]+)\}\s+from\s+['"]([^'"]+)['"]'''),
    # import type { X } from 'module' (TypeScript)
    re.compile(r'''import\s+type\s+\{([^}]+)\}\s+from\s+['"]([^'"]+)['"]'''),
]

# Export patterns
EXPORT_DEFAULT_PATTERN = re.compile(r'''export\s+default\s+(?:function|class)?\s*(\w*)''')
EXPORT_NAMED_PATTERN = re.compile(r'''export\s+\{([^}]+)\}''')
EXPORT_FROM_PATTERN = re.compile(r'''export\s+(?:\{([^}]+)\}|\*)\s+from\s+['"]([^'"]+)['"]''')


# ============================================================================
# Helper Functions
# ============================================================================

def is_exported(line: str) -> bool:
    """Check if a line starts with an export keyword."""
    stripped = line.strip()
    return stripped.startswith('export ') or stripped.startswith('export{')


def find_brace_block_end(lines: List[str], start_idx: int) -> int:
    """Find the end of a brace-delimited block.
    
    Args:
        lines: All source lines (0-indexed)
        start_idx: 0-indexed line where to start looking
        
    Returns:
        0-indexed line number of the closing brace
    """
    brace_count = 0
    in_string = False
    string_char: Optional[str] = None
    in_template = False
    
    for idx in range(start_idx, len(lines)):
        line = lines[idx]
        i = 0
        
        while i < len(line):
            char = line[i]
            prev_char = line[i-1] if i > 0 else ''
            
            # Handle escape sequences
            if prev_char == '\\':
                i += 1
                continue
            
            # Handle template literals
            if char == '`':
                in_template = not in_template
                i += 1
                continue
            
            # Skip template literal content
            if in_template:
                i += 1
                continue
            
            # Handle regular strings
            if char in '"\'':
                if not in_string:
                    in_string = True
                    string_char = char
                elif char == string_char:
                    in_string = False
                    string_char = None
                i += 1
                continue
            
            # Skip string content
            if in_string:
                i += 1
                continue
            
            # Handle single-line comments
            if char == '/' and i + 1 < len(line):
                next_char = line[i + 1]
                if next_char == '/':
                    break  # Rest of line is comment
                elif next_char == '*':
                    # Skip block comment
                    # TODO: Handle multi-line block comments properly
                    i += 2
                    continue
            
            # Count braces
            if char == '{':
                brace_count += 1
            elif char == '}':
                brace_count -= 1
                if brace_count == 0:
                    return idx
            
            i += 1
    
    return len(lines) - 1


def extract_signature(lines: List[str], line_num: int) -> str:
    """Extract the function/class signature.
    
    Args:
        lines: All source lines (0-indexed)
        line_num: 1-based line number
        
    Returns:
        Signature string
    """
    if line_num < 1 or line_num > len(lines):
        return ""
    
    line = lines[line_num - 1].strip()
    
    # If the line contains an opening brace, extract up to it
    if '{' in line:
        return line[:line.index('{')].strip()
    
    # Otherwise return the full line
    return line


def extract_jsdoc(lines: List[str], def_line: int) -> Optional[str]:
    """Extract JSDoc comment above a definition.
    
    Args:
        lines: All source lines (0-indexed)
        def_line: 1-based line number of the definition
        
    Returns:
        JSDoc content or None
    """
    if def_line < 2:
        return None
    
    idx = def_line - 2  # 0-indexed, line before definition
    
    # Check if previous line ends a block comment
    if idx >= 0 and '*/' in lines[idx]:
        # Find the start of the JSDoc
        doc_lines = []
        while idx >= 0:
            line = lines[idx]
            doc_lines.insert(0, line)
            if '/**' in line or '/*' in line:
                break
            idx -= 1
        
        # Parse the JSDoc
        text = '\n'.join(doc_lines)
        # Remove comment markers
        text = re.sub(r'/\*\*?', '', text)
        text = re.sub(r'\*/', '', text)
        # Remove leading asterisks
        text = '\n'.join(
            re.sub(r'^\s*\*\s?', '', line)
            for line in text.split('\n')
        )
        return text.strip() or None
    
    return None


def detect_react_component(lines: List[str], start_line: int, end_line: int) -> bool:
    """Check if a function contains JSX (likely a React component).
    
    Args:
        lines: Source lines (0-indexed)
        start_line: 1-based start line
        end_line: 1-based end line
        
    Returns:
        True if JSX is detected
    """
    for i in range(start_line - 1, min(end_line, len(lines))):
        line = lines[i]
        # Simple JSX detection: look for < followed by capital letter or common tags
        if re.search(r'<[A-Z][a-zA-Z]*|<div|<span|<button|<input|<form', line):
            return True
        # Also check for React fragments
        if '<>' in line or '</>' in line:
            return True
    return False


# ============================================================================
# TypeScript Adapter
# ============================================================================

class TypeScriptAdapter:
    """Language adapter for TypeScript files."""
    
    @property
    def language(self) -> str:
        return 'typescript'
    
    @property
    def extensions(self) -> List[str]:
        return ['.ts', '.tsx', '.mts', '.cts']
    
    def supports_ast(self) -> bool:
        """Check if tree-sitter is available for TypeScript."""
        try:
            import tree_sitter_typescript  # noqa
            return True
        except ImportError:
            return False
    
    def parse_file(self, path: str, source: str) -> ParseResult:
        """Parse TypeScript source code.
        
        Args:
            path: File path for ID generation
            source: Source code content
            
        Returns:
            ParseResult with chunks, imports, exports
        """
        lines = source.split('\n')
        chunks: List[ChunkResult] = []
        imports: List[ImportResult] = []
        exports: List[ExportResult] = []
        errors: List[str] = []
        
        # All patterns for TypeScript
        all_patterns = ECMASCRIPT_PATTERNS + TYPESCRIPT_ONLY_PATTERNS
        
        # Pass 1: Extract chunks
        for i, line in enumerate(lines):
            line_num = i + 1
            
            for pat in all_patterns:
                match = pat.pattern.match(line)
                if match:
                    name = match.group(pat.name_group)
                    exported = is_exported(line)
                    
                    # Find end of block
                    end_idx = find_brace_block_end(lines, i)
                    end_line = end_idx + 1
                    
                    # Extract signature and docstring
                    signature = extract_signature(lines, line_num)
                    docstring = extract_jsdoc(lines, line_num)
                    
                    # Build metadata
                    metadata: Dict[str, bool] = {}
                    if 'async' in line:
                        metadata['is_async'] = True
                    if 'abstract' in line:
                        metadata['is_abstract'] = True
                    
                    # Check for React component (TSX)
                    if path.endswith('.tsx') and pat.chunk_type == 'function':
                        if detect_react_component(lines, line_num, end_line):
                            metadata['is_component'] = True
                    
                    chunk = ChunkResult(
                        id=generate_chunk_id(path, line_num, pat.chunk_type, name),
                        type=pat.chunk_type,
                        name=name,
                        signature=signature,
                        start_line=line_num,
                        end_line=end_line,
                        exported=exported,
                        docstring=docstring,
                        metadata=metadata,
                    )
                    chunks.append(chunk)
                    
                    # Track as export if exported
                    if exported:
                        exports.append(ExportResult(
                            name=name,
                            type=pat.chunk_type,
                            line=line_num,
                        ))
                    
                    break  # Only first matching pattern
        
        # Pass 2: Extract imports
        imports = self._extract_imports(lines)
        
        # Pass 3: Extract additional exports (export { ... })
        exports.extend(self._extract_named_exports(lines))
        
        return ParseResult(
            chunks=chunks,
            imports=imports,
            exports=exports,
            errors=errors,
        )
    
    def _extract_imports(self, lines: List[str]) -> List[ImportResult]:
        """Extract import statements from source lines."""
        imports: List[ImportResult] = []
        
        for i, line in enumerate(lines):
            line_num = i + 1
            stripped = line.strip()
            
            if not stripped.startswith('import'):
                continue
            
            # import X from 'module'
            match = re.search(r'''import\s+(\w+)\s+from\s+['"]([^'"]+)['"]''', stripped)
            if match:
                imports.append(ImportResult(
                    module=match.group(2),
                    symbols=[match.group(1)],
                    is_relative=match.group(2).startswith('.'),
                    line=line_num,
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
                    line=line_num,
                ))
                continue
            
            # import * as X from 'module'
            match = re.search(r'''import\s+\*\s+as\s+(\w+)\s+from\s+['"]([^'"]+)['"]''', stripped)
            if match:
                imports.append(ImportResult(
                    module=match.group(2),
                    alias=match.group(1),
                    is_relative=match.group(2).startswith('.'),
                    line=line_num,
                ))
                continue
            
            # import type { X } from 'module'
            match = re.search(r'''import\s+type\s+\{([^}]+)\}\s+from\s+['"]([^'"]+)['"]''', stripped)
            if match:
                symbols = [s.strip().split(' as ')[0].strip() 
                          for s in match.group(1).split(',')]
                imports.append(ImportResult(
                    module=match.group(2),
                    symbols=symbols,
                    is_relative=match.group(2).startswith('.'),
                    line=line_num,
                    is_type_only=True,
                ))
                continue
            
            # import 'module' (side effect only)
            match = re.search(r'''import\s+['"]([^'"]+)['"]''', stripped)
            if match:
                imports.append(ImportResult(
                    module=match.group(1),
                    is_relative=match.group(1).startswith('.'),
                    line=line_num,
                ))
        
        return imports
    
    def _extract_named_exports(self, lines: List[str]) -> List[ExportResult]:
        """Extract 'export { ... }' style exports."""
        exports: List[ExportResult] = []
        
        for i, line in enumerate(lines):
            line_num = i + 1
            stripped = line.strip()
            
            # export { X, Y, Z }
            match = re.search(r'''export\s+\{([^}]+)\}(?:\s+from)?''', stripped)
            if match and 'from' not in stripped:
                symbols = [s.strip().split(' as ')[0].strip() 
                          for s in match.group(1).split(',')]
                for sym in symbols:
                    exports.append(ExportResult(
                        name=sym,
                        type='unknown',  # Would need to look up
                        line=line_num,
                    ))
            
            # export default X
            match = re.search(r'''export\s+default\s+(\w+)''', stripped)
            if match:
                exports.append(ExportResult(
                    name=match.group(1),
                    type='unknown',
                    line=line_num,
                    is_default=True,
                ))
        
        return exports


# ============================================================================
# JavaScript Adapter
# ============================================================================

class JavaScriptAdapter:
    """Language adapter for JavaScript files."""
    
    @property
    def language(self) -> str:
        return 'javascript'
    
    @property
    def extensions(self) -> List[str]:
        return ['.js', '.jsx', '.mjs', '.cjs']
    
    def supports_ast(self) -> bool:
        """Check if tree-sitter is available for JavaScript."""
        try:
            import tree_sitter_javascript  # noqa
            return True
        except ImportError:
            return False
    
    def parse_file(self, path: str, source: str) -> ParseResult:
        """Parse JavaScript source code.
        
        Uses the same logic as TypeScript but without TS-specific patterns.
        """
        lines = source.split('\n')
        chunks: List[ChunkResult] = []
        imports: List[ImportResult] = []
        exports: List[ExportResult] = []
        errors: List[str] = []
        
        # JavaScript only uses ECMAScript patterns (no interface/type/enum)
        
        for i, line in enumerate(lines):
            line_num = i + 1
            
            for pat in ECMASCRIPT_PATTERNS:
                match = pat.pattern.match(line)
                if match:
                    name = match.group(pat.name_group)
                    exported = is_exported(line)
                    
                    end_idx = find_brace_block_end(lines, i)
                    end_line = end_idx + 1
                    
                    signature = extract_signature(lines, line_num)
                    docstring = extract_jsdoc(lines, line_num)
                    
                    metadata: Dict[str, bool] = {}
                    if 'async' in line:
                        metadata['is_async'] = True
                    
                    # Check for React component (JSX)
                    if path.endswith('.jsx') and pat.chunk_type == 'function':
                        if detect_react_component(lines, line_num, end_line):
                            metadata['is_component'] = True
                    
                    chunk = ChunkResult(
                        id=generate_chunk_id(path, line_num, pat.chunk_type, name),
                        type=pat.chunk_type,
                        name=name,
                        signature=signature,
                        start_line=line_num,
                        end_line=end_line,
                        exported=exported,
                        docstring=docstring,
                        metadata=metadata,
                    )
                    chunks.append(chunk)
                    
                    if exported:
                        exports.append(ExportResult(
                            name=name,
                            type=pat.chunk_type,
                            line=line_num,
                        ))
                    
                    break
        
        # Use TypeScript adapter's import extraction (same format)
        ts_adapter = TypeScriptAdapter()
        imports = ts_adapter._extract_imports(lines)
        exports.extend(ts_adapter._extract_named_exports(lines))
        
        return ParseResult(
            chunks=chunks,
            imports=imports,
            exports=exports,
            errors=errors,
        )


# ============================================================================
# Register Adapters
# ============================================================================

# Create singleton instances
_typescript_adapter = TypeScriptAdapter()
_javascript_adapter = JavaScriptAdapter()

# Register with the adapter registry
register_adapter(_typescript_adapter)
register_adapter(_javascript_adapter)


# Export public API
__all__ = [
    'TypeScriptAdapter',
    'JavaScriptAdapter',
]
