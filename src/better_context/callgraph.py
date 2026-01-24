"""Call graph analysis.

Builds function-level call graphs showing which functions call which
other functions, enabling deeper code flow understanding beyond file
imports.

Features:
- Call site extraction from function bodies
- Symbol resolution to chunk IDs
- Forward and reverse call indices
- Hot path detection
- Impact analysis

Supports:
- Python: function calls, method calls
- TypeScript/JavaScript: function calls, method calls
- Go: function and method calls
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, List, Dict, Optional, Tuple, Set

if TYPE_CHECKING:
    from .manifest import FileEntry, Manifest, ChunkEntry


@dataclass
class CallSite:
    """A function call site."""
    
    caller_id: str       # Chunk ID of calling function
    callee_name: str     # Name of called function (may be unresolved)
    callee_id: Optional[str] = None  # Resolved chunk ID if known
    line: int = 0        # Line number where call occurs
    is_resolved: bool = False  # True if callee_id is valid


@dataclass
class CallGraph:
    """Function-level call graph."""
    
    call_sites: List[CallSite] = field(default_factory=list)
    forward: Dict[str, List[str]] = field(default_factory=dict)   # caller_id -> [callee_ids]
    reverse: Dict[str, List[str]] = field(default_factory=dict)   # callee_id -> [caller_ids]
    unresolved_calls: Dict[str, List[str]] = field(default_factory=dict)  # caller_id -> [unresolved names]


# Language keywords to exclude from call detection
KEYWORDS = {
    'python': {
        'if', 'else', 'elif', 'for', 'while', 'try', 'except', 'finally',
        'with', 'as', 'import', 'from', 'class', 'def', 'return', 'yield',
        'raise', 'assert', 'pass', 'break', 'continue', 'and', 'or', 'not',
        'in', 'is', 'lambda', 'global', 'nonlocal', 'True', 'False', 'None',
        'async', 'await', 'print', 'len', 'str', 'int', 'float', 'list',
        'dict', 'set', 'tuple', 'bool', 'type', 'range', 'enumerate', 'zip',
        'map', 'filter', 'sorted', 'reversed', 'any', 'all', 'sum', 'min',
        'max', 'abs', 'round', 'open', 'super', 'isinstance', 'issubclass',
        'hasattr', 'getattr', 'setattr', 'delattr', 'callable', 'iter', 'next',
    },
    'typescript': {
        'if', 'else', 'for', 'while', 'do', 'switch', 'case', 'break',
        'continue', 'return', 'throw', 'try', 'catch', 'finally', 'new',
        'typeof', 'instanceof', 'void', 'delete', 'in', 'of', 'as', 'is',
        'async', 'await', 'yield', 'class', 'interface', 'type', 'enum',
        'import', 'export', 'from', 'default', 'extends', 'implements',
        'public', 'private', 'protected', 'static', 'readonly', 'abstract',
        'true', 'false', 'null', 'undefined', 'this', 'super', 'console',
        'Array', 'Object', 'String', 'Number', 'Boolean', 'Promise', 'Map',
        'Set', 'Date', 'RegExp', 'Error', 'JSON', 'Math', 'require',
    },
    'javascript': {
        'if', 'else', 'for', 'while', 'do', 'switch', 'case', 'break',
        'continue', 'return', 'throw', 'try', 'catch', 'finally', 'new',
        'typeof', 'instanceof', 'void', 'delete', 'in', 'of', 'async',
        'await', 'yield', 'class', 'import', 'export', 'from', 'default',
        'extends', 'true', 'false', 'null', 'undefined', 'this', 'super',
        'console', 'Array', 'Object', 'String', 'Number', 'Boolean',
        'Promise', 'Map', 'Set', 'Date', 'RegExp', 'Error', 'JSON', 'Math',
        'require', 'function', 'var', 'let', 'const',
    },
    'go': {
        'if', 'else', 'for', 'switch', 'case', 'default', 'break',
        'continue', 'return', 'go', 'defer', 'select', 'chan', 'map',
        'struct', 'interface', 'package', 'import', 'func', 'var', 'const',
        'type', 'range', 'true', 'false', 'nil', 'make', 'new', 'append',
        'len', 'cap', 'copy', 'delete', 'close', 'panic', 'recover',
        'print', 'println', 'error', 'string', 'int', 'float64', 'bool',
    },
}

# Patterns for detecting function calls
# These are simplified regex patterns for the fallback mode
CALL_PATTERNS = {
    'python': re.compile(
        r'(?<![a-zA-Z_\.])([a-zA-Z_][a-zA-Z0-9_]*)\s*\(',
    ),
    'typescript': re.compile(
        r'(?<![a-zA-Z_\.])([a-zA-Z_$][a-zA-Z0-9_$]*)\s*(?:<[^>]+>)?\s*\(',
    ),
    'javascript': re.compile(
        r'(?<![a-zA-Z_\.])([a-zA-Z_$][a-zA-Z0-9_$]*)\s*\(',
    ),
    'go': re.compile(
        r'(?<![a-zA-Z_\.])([a-zA-Z_][a-zA-Z0-9_]*)\s*\(',
    ),
}

# Method call patterns (obj.method())
METHOD_CALL_PATTERNS = {
    'python': re.compile(
        r'\.([a-zA-Z_][a-zA-Z0-9_]*)\s*\(',
    ),
    'typescript': re.compile(
        r'\.([a-zA-Z_$][a-zA-Z0-9_$]*)\s*(?:<[^>]+>)?\s*\(',
    ),
    'javascript': re.compile(
        r'\.([a-zA-Z_$][a-zA-Z0-9_$]*)\s*\(',
    ),
    'go': re.compile(
        r'\.([a-zA-Z_][a-zA-Z0-9_]*)\s*\(',
    ),
}


def find_calls_in_source(
    source: str,
    language: str,
) -> List[Tuple[str, int]]:
    """Find function calls in source code.
    
    Args:
        source: Source code string
        language: Language identifier
    
    Returns:
        List of (function_name, line_offset) tuples
    """
    pattern = CALL_PATTERNS.get(language)
    method_pattern = METHOD_CALL_PATTERNS.get(language)
    keywords = KEYWORDS.get(language, set())
    
    if not pattern:
        return []
    
    calls = []
    lines = source.split('\n')
    
    for i, line in enumerate(lines):
        # Skip comments
        stripped = line.strip()
        if stripped.startswith('#') or stripped.startswith('//'):
            continue
        
        # Find function calls
        for match in pattern.finditer(line):
            name = match.group(1)
            # Filter out keywords and private functions
            if name not in keywords and not name.startswith('_'):
                calls.append((name, i))
        
        # Find method calls (if pattern exists)
        if method_pattern:
            for match in method_pattern.finditer(line):
                name = match.group(1)
                if name not in keywords:
                    calls.append((name, i))
    
    return calls


def extract_chunk_source(
    file_source: str,
    chunk: "ChunkEntry",
) -> str:
    """Extract source code for a specific chunk.
    
    Args:
        file_source: Full file source
        chunk: ChunkEntry with line range
    
    Returns:
        Source code for the chunk
    """
    lines = file_source.split('\n')
    start = max(0, chunk.start_line - 1)
    end = min(len(lines), chunk.end_line)
    return '\n'.join(lines[start:end])


def build_symbol_table(files: List["FileEntry"]) -> Dict[str, str]:
    """Build a mapping from symbol names to chunk IDs.
    
    Args:
        files: List of file entries
    
    Returns:
        Dict mapping names/qualified names to chunk IDs
    """
    table: Dict[str, str] = {}
    
    for file in files:
        for chunk in file.chunks:
            # Skip non-callable chunks
            if chunk.type not in ('function', 'method', 'class'):
                continue
            
            # Add by simple name (may be ambiguous)
            if chunk.name not in table:
                table[chunk.name] = chunk.id
            
            # Add by qualified name (file:name)
            qualified = f"{file.path}:{chunk.name}"
            table[qualified] = chunk.id
    
    return table


def resolve_call(
    call_name: str,
    current_file: "FileEntry",
    symbol_table: Dict[str, str],
) -> Optional[str]:
    """Resolve a function call to its chunk ID.
    
    Resolution order:
    1. Local (same file) lookup
    2. Imported symbols
    3. Global symbol table
    
    Args:
        call_name: Name of called function
        current_file: FileEntry containing the call
        symbol_table: Global symbol table
    
    Returns:
        Chunk ID if resolved, None otherwise
    """
    # 1. Try local (same file) first
    for chunk in current_file.chunks:
        if chunk.name == call_name:
            return chunk.id
    
    # 2. Try through imports
    for imp in current_file.imports:
        if call_name in imp.symbols or not imp.symbols:
            # Could be from this import
            qualified = f"{imp.module}:{call_name}"
            if qualified in symbol_table:
                return symbol_table[qualified]
    
    # 3. Try global lookup
    return symbol_table.get(call_name)


def build_call_graph(
    files: List["FileEntry"],
    root_path: Path,
) -> CallGraph:
    """Build a call graph from parsed files.
    
    Args:
        files: List of file entries with chunks
        root_path: Project root for reading source files
    
    Returns:
        CallGraph with edges and indices
    """
    call_graph = CallGraph()
    symbol_table = build_symbol_table(files)
    
    for file in files:
        # Read file source
        file_path = root_path / file.path
        try:
            file_source = file_path.read_text(encoding='utf-8')
        except (OSError, UnicodeDecodeError):
            continue
        
        for chunk in file.chunks:
            # Only analyze callable chunks
            if chunk.type not in ('function', 'method'):
                continue
            
            # Extract chunk source
            chunk_source = extract_chunk_source(file_source, chunk)
            
            # Find calls in this chunk
            calls = find_calls_in_source(chunk_source, file.language)
            
            for call_name, line_offset in calls:
                # Try to resolve the call
                callee_id = resolve_call(call_name, file, symbol_table)
                
                call_site = CallSite(
                    caller_id=chunk.id,
                    callee_name=call_name,
                    callee_id=callee_id,
                    line=chunk.start_line + line_offset,
                    is_resolved=callee_id is not None,
                )
                call_graph.call_sites.append(call_site)
    
    # Build forward and reverse indices
    forward: Dict[str, List[str]] = defaultdict(list)
    reverse: Dict[str, List[str]] = defaultdict(list)
    unresolved: Dict[str, List[str]] = defaultdict(list)
    
    for site in call_graph.call_sites:
        if site.is_resolved and site.callee_id:
            forward[site.caller_id].append(site.callee_id)
            reverse[site.callee_id].append(site.caller_id)
        else:
            unresolved[site.caller_id].append(site.callee_name)
    
    call_graph.forward = dict(forward)
    call_graph.reverse = dict(reverse)
    call_graph.unresolved_calls = dict(unresolved)
    
    return call_graph


def get_callers(call_graph: CallGraph, chunk_id: str) -> List[str]:
    """Get all functions that call a given function.
    
    Args:
        call_graph: CallGraph
        chunk_id: Target function's chunk ID
    
    Returns:
        List of caller chunk IDs
    """
    return call_graph.reverse.get(chunk_id, [])


def get_callees(call_graph: CallGraph, chunk_id: str) -> List[str]:
    """Get all functions called by a given function.
    
    Args:
        call_graph: CallGraph
        chunk_id: Calling function's chunk ID
    
    Returns:
        List of callee chunk IDs
    """
    return call_graph.forward.get(chunk_id, [])


def get_transitive_callers(
    call_graph: CallGraph,
    chunk_id: str,
    max_depth: int = 10,
) -> Set[str]:
    """Get all functions that directly or indirectly call a function.
    
    Args:
        call_graph: CallGraph
        chunk_id: Target function's chunk ID
        max_depth: Maximum recursion depth
    
    Returns:
        Set of all caller chunk IDs (transitive closure)
    """
    visited: Set[str] = set()
    stack = [(chunk_id, 0)]
    
    while stack:
        current, depth = stack.pop()
        if current in visited or depth > max_depth:
            continue
        visited.add(current)
        
        for caller in call_graph.reverse.get(current, []):
            if caller not in visited:
                stack.append((caller, depth + 1))
    
    visited.discard(chunk_id)  # Remove the starting node
    return visited


def get_transitive_callees(
    call_graph: CallGraph,
    chunk_id: str,
    max_depth: int = 10,
) -> Set[str]:
    """Get all functions directly or indirectly called by a function.
    
    Args:
        call_graph: CallGraph
        chunk_id: Calling function's chunk ID
        max_depth: Maximum recursion depth
    
    Returns:
        Set of all callee chunk IDs (transitive closure)
    """
    visited: Set[str] = set()
    stack = [(chunk_id, 0)]
    
    while stack:
        current, depth = stack.pop()
        if current in visited or depth > max_depth:
            continue
        visited.add(current)
        
        for callee in call_graph.forward.get(current, []):
            if callee not in visited:
                stack.append((callee, depth + 1))
    
    visited.discard(chunk_id)  # Remove the starting node
    return visited


def get_hot_functions(
    call_graph: CallGraph,
    limit: int = 10,
) -> List[Tuple[str, int]]:
    """Get the most-called functions.
    
    Args:
        call_graph: CallGraph
        limit: Maximum results
    
    Returns:
        List of (chunk_id, call_count) tuples sorted by count
    """
    call_counts: Dict[str, int] = defaultdict(int)
    
    for callers in call_graph.reverse.values():
        for _ in callers:
            pass
    
    for callee_id, callers in call_graph.reverse.items():
        call_counts[callee_id] = len(callers)
    
    sorted_funcs = sorted(call_counts.items(), key=lambda x: x[1], reverse=True)
    return sorted_funcs[:limit]


def get_entry_points(call_graph: CallGraph) -> List[str]:
    """Get functions that are never called (potential entry points).
    
    Args:
        call_graph: CallGraph
    
    Returns:
        List of chunk IDs with no callers
    """
    all_callees: Set[str] = set()
    for callees in call_graph.forward.values():
        all_callees.update(callees)
    
    all_callers = set(call_graph.forward.keys())
    return sorted(all_callers - all_callees)


def get_leaf_functions(call_graph: CallGraph) -> List[str]:
    """Get functions that don't call any other functions.
    
    Args:
        call_graph: CallGraph
    
    Returns:
        List of chunk IDs with no callees
    """
    all_callers = set(call_graph.forward.keys())
    all_callees: Set[str] = set()
    for callees in call_graph.forward.values():
        all_callees.update(callees)
    
    # Functions that are called but don't call others
    return sorted(all_callees - all_callers)


def get_call_graph_stats(call_graph: CallGraph) -> dict:
    """Get statistics about the call graph.
    
    Args:
        call_graph: CallGraph
    
    Returns:
        Statistics dict
    """
    total_calls = len(call_graph.call_sites)
    resolved_calls = sum(1 for s in call_graph.call_sites if s.is_resolved)
    unique_callers = len(call_graph.forward)
    unique_callees = len(call_graph.reverse)
    
    return {
        'total_call_sites': total_calls,
        'resolved_calls': resolved_calls,
        'unresolved_calls': total_calls - resolved_calls,
        'resolution_rate': resolved_calls / total_calls if total_calls > 0 else 1.0,
        'unique_callers': unique_callers,
        'unique_callees': unique_callees,
        'entry_points': len(get_entry_points(call_graph)),
        'leaf_functions': len(get_leaf_functions(call_graph)),
    }


def format_call_graph_summary(call_graph: CallGraph, limit: int = 10) -> str:
    """Format call graph as markdown summary.
    
    Args:
        call_graph: CallGraph
        limit: Max items per section
    
    Returns:
        Markdown string
    """
    stats = get_call_graph_stats(call_graph)
    hot_funcs = get_hot_functions(call_graph, limit)
    
    lines = [
        "## 📞 Call Graph Analysis\n",
        f"- Total call sites: {stats['total_call_sites']}",
        f"- Resolved: {stats['resolved_calls']} ({stats['resolution_rate']:.1%})",
        f"- Entry points: {stats['entry_points']}",
        f"- Leaf functions: {stats['leaf_functions']}",
        "",
        "### Most-Called Functions\n",
        "| Function | Call Count |",
        "|----------|------------|",
    ]
    
    for func_id, count in hot_funcs:
        lines.append(f"| `{func_id}` | {count} |")
    
    return '\n'.join(lines)


# Export public API
__all__ = [
    'CallSite',
    'CallGraph',
    'KEYWORDS',
    'CALL_PATTERNS',
    'METHOD_CALL_PATTERNS',
    'find_calls_in_source',
    'extract_chunk_source',
    'build_symbol_table',
    'resolve_call',
    'build_call_graph',
    'get_callers',
    'get_callees',
    'get_transitive_callers',
    'get_transitive_callees',
    'get_hot_functions',
    'get_entry_points',
    'get_leaf_functions',
    'get_call_graph_stats',
    'format_call_graph_summary',
]
