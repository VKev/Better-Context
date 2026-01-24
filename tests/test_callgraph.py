"""Tests for call graph analysis."""

import pytest
from dataclasses import dataclass, field
from typing import List, Dict, Any
from pathlib import Path
import tempfile
import os

# Mock types for testing
@dataclass
class MockChunk:
    id: str
    type: str
    name: str
    start_line: int = 1
    end_line: int = 10
    signature: str = ""
    parent: str = None
    exported: bool = False
    docstring: str = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class MockImport:
    module: str
    symbols: List[str] = field(default_factory=list)


@dataclass
class MockFileEntry:
    path: str
    language: str = "python"
    chunks: List[MockChunk] = field(default_factory=list)
    imports: List[MockImport] = field(default_factory=list)
    exports: List[Any] = field(default_factory=list)
    size_bytes: int = 0
    hash: str = ""


# Import module under test
from src.better_context.callgraph import (
    CallSite,
    CallGraph,
    KEYWORDS,
    CALL_PATTERNS,
    find_calls_in_source,
    extract_chunk_source,
    build_symbol_table,
    resolve_call,
    get_callers,
    get_callees,
    get_transitive_callers,
    get_transitive_callees,
    get_hot_functions,
    get_entry_points,
    get_leaf_functions,
    get_call_graph_stats,
    format_call_graph_summary,
)


class TestKeywords:
    """Tests for keyword sets."""
    
    def test_python_keywords_exist(self):
        assert 'if' in KEYWORDS['python']
        assert 'def' in KEYWORDS['python']
        assert 'class' in KEYWORDS['python']
        assert 'return' in KEYWORDS['python']
    
    def test_typescript_keywords_exist(self):
        assert 'if' in KEYWORDS['typescript']
        assert 'class' in KEYWORDS['typescript']
        assert 'interface' in KEYWORDS['typescript']
    
    def test_javascript_keywords_exist(self):
        assert 'function' in KEYWORDS['javascript']
        assert 'const' in KEYWORDS['javascript']
    
    def test_go_keywords_exist(self):
        assert 'func' in KEYWORDS['go']
        assert 'package' in KEYWORDS['go']


class TestCallPatterns:
    """Tests for call pattern regex."""
    
    def test_python_pattern_exists(self):
        assert 'python' in CALL_PATTERNS
    
    def test_typescript_pattern_exists(self):
        assert 'typescript' in CALL_PATTERNS
    
    def test_go_pattern_exists(self):
        assert 'go' in CALL_PATTERNS


class TestFindCallsInSource:
    """Tests for find_calls_in_source function."""
    
    def test_finds_simple_function_calls(self):
        source = """
def foo():
    bar()
    baz(x, y)
"""
        calls = find_calls_in_source(source, 'python')
        call_names = [c[0] for c in calls]
        
        assert 'bar' in call_names
        assert 'baz' in call_names
    
    def test_excludes_keywords(self):
        source = """
if condition:
    return result
for item in items:
    pass
"""
        calls = find_calls_in_source(source, 'python')
        call_names = [c[0] for c in calls]
        
        # Keywords should not be detected as calls
        assert 'if' not in call_names
        assert 'return' not in call_names
        assert 'for' not in call_names
    
    def test_finds_method_calls(self):
        source = """
obj.method()
self.do_something()
"""
        calls = find_calls_in_source(source, 'python')
        call_names = [c[0] for c in calls]
        
        assert 'method' in call_names
        assert 'do_something' in call_names
    
    def test_skips_comments(self):
        source = """
# foo()
// bar()
real_function()
"""
        calls = find_calls_in_source(source, 'python')
        call_names = [c[0] for c in calls]
        
        # Comment calls should not be found
        assert 'foo' not in call_names
        # But real function should be
        assert 'real_function' in call_names
    
    def test_typescript_calls(self):
        source = """
const result = fetchData<User>()
process(data)
"""
        calls = find_calls_in_source(source, 'typescript')
        call_names = [c[0] for c in calls]
        
        assert 'fetchData' in call_names
        assert 'process' in call_names
    
    def test_returns_line_numbers(self):
        source = """line0
function_a()
line2
function_b()
"""
        calls = find_calls_in_source(source, 'python')
        
        # Find function_a call
        func_a = next((c for c in calls if c[0] == 'function_a'), None)
        assert func_a is not None
        assert func_a[1] == 1  # Line 1 (0-indexed)
        
        # Find function_b call
        func_b = next((c for c in calls if c[0] == 'function_b'), None)
        assert func_b is not None
        assert func_b[1] == 3  # Line 3 (0-indexed)
    
    def test_unknown_language_returns_empty(self):
        source = "some_func()"
        calls = find_calls_in_source(source, 'unknown_lang')
        assert calls == []


class TestExtractChunkSource:
    """Tests for extract_chunk_source function."""
    
    def test_extracts_correct_lines(self):
        file_source = """line 1
line 2
line 3
line 4
line 5"""
        chunk = MockChunk(id="1", type="function", name="test", start_line=2, end_line=4)
        
        result = extract_chunk_source(file_source, chunk)
        
        assert "line 2" in result
        assert "line 3" in result
        assert "line 4" in result
        assert "line 1" not in result
        assert "line 5" not in result
    
    def test_handles_out_of_bounds(self):
        file_source = "only one line"
        chunk = MockChunk(id="1", type="function", name="test", start_line=1, end_line=100)
        
        result = extract_chunk_source(file_source, chunk)
        
        assert result == "only one line"


class TestBuildSymbolTable:
    """Tests for build_symbol_table function."""
    
    def test_builds_table_from_files(self):
        files = [
            MockFileEntry(
                path="utils.py",
                chunks=[
                    MockChunk(id="utils.py:1:function:helper", type="function", name="helper"),
                    MockChunk(id="utils.py:10:class:Util", type="class", name="Util"),
                ]
            ),
            MockFileEntry(
                path="main.py",
                chunks=[
                    MockChunk(id="main.py:1:function:main", type="function", name="main"),
                ]
            ),
        ]
        
        table = build_symbol_table(files)
        
        # Simple name lookup
        assert "helper" in table
        assert "Util" in table
        assert "main" in table
        
        # Qualified name lookup
        assert "utils.py:helper" in table
        assert "main.py:main" in table
    
    def test_skips_non_callable_chunks(self):
        files = [
            MockFileEntry(
                path="types.py",
                chunks=[
                    MockChunk(id="1", type="interface", name="IUser"),
                    MockChunk(id="2", type="type", name="UserType"),
                ]
            ),
        ]
        
        table = build_symbol_table(files)
        
        assert "IUser" not in table
        assert "UserType" not in table


class TestResolveCall:
    """Tests for resolve_call function."""
    
    def test_resolves_local_call(self):
        current_file = MockFileEntry(
            path="main.py",
            chunks=[
                MockChunk(id="main.py:1:function:foo", type="function", name="foo"),
                MockChunk(id="main.py:10:function:bar", type="function", name="bar"),
            ]
        )
        symbol_table = {"foo": "main.py:1:function:foo"}
        
        result = resolve_call("foo", current_file, symbol_table)
        
        assert result == "main.py:1:function:foo"
    
    def test_resolves_imported_call(self):
        current_file = MockFileEntry(
            path="main.py",
            chunks=[],
            imports=[MockImport(module="utils", symbols=["helper"])]
        )
        symbol_table = {"utils:helper": "utils.py:1:function:helper"}
        
        result = resolve_call("helper", current_file, symbol_table)
        
        assert result == "utils.py:1:function:helper"
    
    def test_resolves_global_call(self):
        current_file = MockFileEntry(path="main.py", chunks=[])
        symbol_table = {"global_func": "lib.py:1:function:global_func"}
        
        result = resolve_call("global_func", current_file, symbol_table)
        
        assert result == "lib.py:1:function:global_func"
    
    def test_returns_none_for_unresolved(self):
        current_file = MockFileEntry(path="main.py", chunks=[])
        symbol_table = {}
        
        result = resolve_call("unknown_func", current_file, symbol_table)
        
        assert result is None


class TestCallGraphOperations:
    """Tests for call graph query operations."""
    
    def setup_method(self):
        """Create a sample call graph for testing."""
        self.graph = CallGraph(
            call_sites=[
                CallSite(caller_id="a", callee_name="b", callee_id="b", is_resolved=True),
                CallSite(caller_id="a", callee_name="c", callee_id="c", is_resolved=True),
                CallSite(caller_id="b", callee_name="d", callee_id="d", is_resolved=True),
                CallSite(caller_id="c", callee_name="d", callee_id="d", is_resolved=True),
                CallSite(caller_id="x", callee_name="unknown", is_resolved=False),
            ],
            forward={"a": ["b", "c"], "b": ["d"], "c": ["d"]},
            reverse={"b": ["a"], "c": ["a"], "d": ["b", "c"]},
            unresolved_calls={"x": ["unknown"]},
        )
    
    def test_get_callers(self):
        callers = get_callers(self.graph, "d")
        assert set(callers) == {"b", "c"}
    
    def test_get_callees(self):
        callees = get_callees(self.graph, "a")
        assert set(callees) == {"b", "c"}
    
    def test_get_transitive_callers(self):
        # d is called by b and c, which are called by a
        callers = get_transitive_callers(self.graph, "d")
        assert "a" in callers
        assert "b" in callers
        assert "c" in callers
    
    def test_get_transitive_callees(self):
        # a calls b and c, which call d
        callees = get_transitive_callees(self.graph, "a")
        assert "b" in callees
        assert "c" in callees
        assert "d" in callees
    
    def test_get_hot_functions(self):
        hot = get_hot_functions(self.graph, limit=2)
        # d has most callers (2)
        assert hot[0][0] == "d"
        assert hot[0][1] == 2
    
    def test_get_entry_points(self):
        entry_points = get_entry_points(self.graph)
        # a is not called by anyone
        assert "a" in entry_points
    
    def test_get_leaf_functions(self):
        leaves = get_leaf_functions(self.graph)
        # d doesn't call anything
        assert "d" in leaves


class TestGetCallGraphStats:
    """Tests for get_call_graph_stats function."""
    
    def test_stats_calculation(self):
        graph = CallGraph(
            call_sites=[
                CallSite(caller_id="a", callee_name="b", callee_id="b", is_resolved=True),
                CallSite(caller_id="a", callee_name="x", is_resolved=False),
            ],
            forward={"a": ["b"]},
            reverse={"b": ["a"]},
        )
        
        stats = get_call_graph_stats(graph)
        
        assert stats['total_call_sites'] == 2
        assert stats['resolved_calls'] == 1
        assert stats['unresolved_calls'] == 1
        assert stats['resolution_rate'] == 0.5


class TestFormatCallGraphSummary:
    """Tests for format_call_graph_summary function."""
    
    def test_formats_markdown(self):
        graph = CallGraph(
            call_sites=[
                CallSite(caller_id="a", callee_name="b", callee_id="b", is_resolved=True),
            ],
            forward={"a": ["b"]},
            reverse={"b": ["a"]},
        )
        
        summary = format_call_graph_summary(graph)
        
        assert "Call Graph" in summary
        assert "Total call sites" in summary
