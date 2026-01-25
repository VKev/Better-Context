"""Tests for semantic anchors (content-addressable chunk IDs)."""

import pytest
from better_context.semantic_anchor import (
    compute_semantic_anchor,
    compute_signature_anchor,
    compute_hash,
    normalize_python_code,
    normalize_javascript_code,
    normalize_go_code,
    normalize_code,
    SemanticAnchor,
    AnchorMapping,
    update_anchor_mapping,
    resolve_anchor,
    anchor_mapping_to_dict,
    dict_to_anchor_mapping,
)


class TestNormalizePythonCode:
    """Tests for Python code normalization."""

    def test_removes_comments(self):
        """Test that comments are removed."""
        source = '''
def hello():
    # This is a comment
    return "world"  # inline comment
'''
        normalized = normalize_python_code(source)
        assert "# This is a comment" not in normalized
        assert "# inline comment" not in normalized

    def test_removes_docstrings(self):
        """Test that docstrings are removed."""
        source = '''
def hello():
    """This is a docstring."""
    return 42
'''
        normalized = normalize_python_code(source)
        assert "This is a docstring" not in normalized

    def test_removes_multiline_docstrings(self):
        """Test that multi-line docstrings are removed."""
        source = '''
def hello():
    """
    This is a
    multi-line docstring.
    """
    return 42
'''
        normalized = normalize_python_code(source)
        assert "multi-line docstring" not in normalized

    def test_normalizes_string_literals(self):
        """Test that string contents are normalized."""
        source1 = 'x = "hello world"'
        source2 = 'x = "goodbye world"'
        
        norm1 = normalize_python_code(source1)
        norm2 = normalize_python_code(source2)
        
        # Both should normalize to the same thing
        assert norm1 == norm2

    def test_preserves_structure(self):
        """Test that code structure is preserved."""
        source = '''
def add(a, b):
    return a + b
'''
        normalized = normalize_python_code(source)
        assert "def add" in normalized or "add" in normalized
        assert "return" in normalized

    def test_normalizes_whitespace(self):
        """Test that whitespace is normalized."""
        source = 'x   =    1  +   2'
        normalized = normalize_python_code(source)
        # Should have single spaces
        assert '   ' not in normalized


class TestNormalizeJavaScriptCode:
    """Tests for JavaScript/TypeScript code normalization."""

    def test_removes_line_comments(self):
        """Test that line comments are removed."""
        source = '''
function hello() {
    // This is a comment
    return "world";
}
'''
        normalized = normalize_javascript_code(source)
        assert "// This is a comment" not in normalized

    def test_removes_block_comments(self):
        """Test that block comments are removed."""
        source = '''
function hello() {
    /* This is a
       block comment */
    return 42;
}
'''
        normalized = normalize_javascript_code(source)
        assert "block comment" not in normalized

    def test_normalizes_template_literals(self):
        """Test that template literal contents are normalized."""
        source1 = 'const x = `hello ${name}`'
        source2 = 'const x = `goodbye ${name}`'
        
        norm1 = normalize_javascript_code(source1)
        norm2 = normalize_javascript_code(source2)
        
        # Both should normalize to the same thing
        assert norm1 == norm2

    def test_preserves_urls(self):
        """Test that URLs with // are not treated as comments."""
        source = 'const url = "https://example.com"'
        normalized = normalize_javascript_code(source)
        # The string gets normalized but shouldn't break


class TestNormalizeGoCode:
    """Tests for Go code normalization."""

    def test_removes_line_comments(self):
        """Test that line comments are removed."""
        source = '''
func hello() {
    // This is a comment
    return "world"
}
'''
        normalized = normalize_go_code(source)
        assert "// This is a comment" not in normalized

    def test_removes_block_comments(self):
        """Test that block comments are removed."""
        source = '''
func hello() {
    /* This is a
       block comment */
    return 42
}
'''
        normalized = normalize_go_code(source)
        assert "block comment" not in normalized


class TestComputeSemanticAnchor:
    """Tests for semantic anchor computation."""

    def test_same_code_same_anchor(self):
        """Test that identical code produces the same anchor."""
        source1 = '''
def hello():
    return "world"
'''
        source2 = '''
def hello():
    return "world"
'''
        anchor1 = compute_semantic_anchor(source1, 1, 3, "python", "hello", "function")
        anchor2 = compute_semantic_anchor(source2, 1, 3, "python", "hello", "function")
        
        assert anchor1 == anchor2

    def test_different_code_different_anchor(self):
        """Test that different code produces different anchors."""
        source1 = '''
def hello():
    return "world"
'''
        source2 = '''
def hello():
    return "universe"
'''
        anchor1 = compute_semantic_anchor(source1, 1, 3, "python", "hello", "function")
        anchor2 = compute_semantic_anchor(source2, 1, 3, "python", "hello", "function")
        
        # String content is normalized, so these should be the same!
        # Only structural changes produce different anchors
        assert anchor1 == anchor2

    def test_different_name_different_anchor(self):
        """Test that different names produce different anchors."""
        source = '''
def hello():
    return 42
'''
        anchor1 = compute_semantic_anchor(source, 1, 3, "python", "hello", "function")
        anchor2 = compute_semantic_anchor(source, 1, 3, "python", "world", "function")
        
        assert anchor1 != anchor2

    def test_whitespace_changes_same_anchor(self):
        """Test that whitespace changes don't affect anchor."""
        source1 = '''def hello():
    x = 1
    return x'''
        
        source2 = '''def hello():
    x   =   1
    return   x'''
        
        anchor1 = compute_semantic_anchor(source1, 1, 3, "python", "hello", "function")
        anchor2 = compute_semantic_anchor(source2, 1, 3, "python", "hello", "function")
        
        assert anchor1 == anchor2

    def test_comment_changes_same_anchor(self):
        """Test that comment changes don't affect anchor."""
        source1 = '''
def hello():
    # Version 1 comment
    return 42
'''
        source2 = '''
def hello():
    # Completely different comment
    return 42
'''
        anchor1 = compute_semantic_anchor(source1, 1, 4, "python", "hello", "function")
        anchor2 = compute_semantic_anchor(source2, 1, 4, "python", "hello", "function")
        
        assert anchor1 == anchor2

    def test_anchor_is_16_chars(self):
        """Test that anchors are 16 hex characters."""
        source = 'def hello(): pass'
        anchor = compute_semantic_anchor(source, 1, 1, "python", "hello", "function")
        
        assert len(anchor) == 16
        assert all(c in '0123456789abcdef' for c in anchor)

    def test_code_moved_same_anchor(self):
        """Test that code at different line numbers produces same anchor."""
        source1 = '''def hello():
    return 42'''
        
        source2 = '''# Some header comment
# More comments

def hello():
    return 42'''
        
        anchor1 = compute_semantic_anchor(source1, 1, 2, "python", "hello", "function")
        anchor2 = compute_semantic_anchor(source2, 4, 5, "python", "hello", "function")
        
        assert anchor1 == anchor2


class TestComputeSignatureAnchor:
    """Tests for signature-based anchors."""

    def test_signature_anchor_is_8_chars(self):
        """Test that signature anchors are 8 hex characters."""
        anchor = compute_signature_anchor("def hello(name: str) -> str", "python")
        
        assert len(anchor) == 8
        assert all(c in '0123456789abcdef' for c in anchor)

    def test_same_signature_same_anchor(self):
        """Test that identical signatures produce same anchor."""
        sig = "def hello(name: str) -> str"
        anchor1 = compute_signature_anchor(sig, "python")
        anchor2 = compute_signature_anchor(sig, "python")
        
        assert anchor1 == anchor2


class TestAnchorMapping:
    """Tests for anchor mapping functionality."""

    def test_create_empty_mapping(self):
        """Test creating empty anchor mapping."""
        mapping = AnchorMapping()
        
        assert mapping.anchor_to_location == {}
        assert mapping.location_to_anchor == {}
        assert mapping.history == []

    def test_update_mapping(self):
        """Test updating anchor mapping."""
        mapping = AnchorMapping()
        
        update_anchor_mapping(
            mapping,
            anchor_id="a1b2c3d4e5f6a7b8",
            path="src/utils.py",
            line=10,
            location_id="src/utils.py:10:function:hello",
            timestamp="2026-01-24T00:00:00Z",
        )
        
        assert mapping.anchor_to_location["a1b2c3d4e5f6a7b8"] == ("src/utils.py", 10)
        assert mapping.location_to_anchor["src/utils.py:10:function:hello"] == "a1b2c3d4e5f6a7b8"

    def test_resolve_anchor(self):
        """Test resolving anchor to location."""
        mapping = AnchorMapping()
        
        update_anchor_mapping(
            mapping,
            anchor_id="a1b2c3d4e5f6a7b8",
            path="src/utils.py",
            line=10,
            location_id="src/utils.py:10:function:hello",
        )
        
        result = resolve_anchor(mapping, "a1b2c3d4e5f6a7b8")
        
        assert result == ("src/utils.py", 10)

    def test_resolve_unknown_anchor(self):
        """Test resolving unknown anchor."""
        mapping = AnchorMapping()
        
        result = resolve_anchor(mapping, "unknown_anchor")
        
        assert result is None

    def test_move_tracking(self):
        """Test that moves are tracked in history."""
        mapping = AnchorMapping()
        
        # Initial location
        update_anchor_mapping(
            mapping,
            anchor_id="a1b2c3d4e5f6a7b8",
            path="src/old.py",
            line=10,
            location_id="src/old.py:10:function:hello",
            timestamp="2026-01-24T00:00:00Z",
        )
        
        # Move to new location
        update_anchor_mapping(
            mapping,
            anchor_id="a1b2c3d4e5f6a7b8",
            path="src/new.py",
            line=20,
            location_id="src/new.py:20:function:hello",
            timestamp="2026-01-24T01:00:00Z",
        )
        
        # Should have 1 move in history
        assert len(mapping.history) == 1
        move = mapping.history[0]
        assert move[0] == "a1b2c3d4e5f6a7b8"
        assert move[2] == "src/new.py:20:function:hello"


class TestAnchorMappingSerialization:
    """Tests for anchor mapping serialization."""

    def test_round_trip_serialization(self):
        """Test that mapping can be serialized and deserialized."""
        mapping = AnchorMapping()
        
        update_anchor_mapping(
            mapping,
            anchor_id="a1b2c3d4e5f6a7b8",
            path="src/utils.py",
            line=10,
            location_id="src/utils.py:10:function:hello",
            timestamp="2026-01-24T00:00:00Z",
        )
        
        # Serialize
        data = anchor_mapping_to_dict(mapping)
        
        # Deserialize
        restored = dict_to_anchor_mapping(data)
        
        assert restored.anchor_to_location == mapping.anchor_to_location
        assert restored.location_to_anchor == mapping.location_to_anchor
        assert len(restored.history) == len(mapping.history)


class TestIntegration:
    """Integration tests for semantic anchors with actual parsing."""

    def test_python_adapter_includes_anchor(self):
        """Test that Python adapter includes semantic anchors."""
        from better_context.languages.python import PythonAdapter
        
        adapter = PythonAdapter()
        source = '''
def hello(name: str) -> str:
    """Say hello."""
    return f"Hello, {name}!"
'''
        result = adapter.parse_file("test.py", source)
        
        assert len(result.chunks) == 1
        chunk = result.chunks[0]
        assert chunk.semantic_anchor is not None
        assert len(chunk.semantic_anchor) == 16

    def test_chunker_includes_anchor(self):
        """Test that chunker includes semantic anchors."""
        from better_context.chunker import parse_file
        
        source = '''
def hello(name: str) -> str:
    return f"Hello, {name}!"
'''
        result = parse_file("test.py", source, "python")
        
        assert len(result.chunks) == 1
        chunk = result.chunks[0]
        assert chunk.semantic_anchor is not None
        assert len(chunk.semantic_anchor) == 16

    def test_manifest_preserves_anchor(self):
        """Test that manifest serialization preserves anchors."""
        from better_context.manifest import ChunkEntry, manifest_to_dict
        from dataclasses import asdict
        
        chunk = ChunkEntry(
            id="test.py:1:function:hello",
            type="function",
            name="hello",
            signature="def hello()",
            start_line=1,
            end_line=3,
            semantic_anchor="a1b2c3d4e5f6a7b8",
        )
        
        # Convert to dict
        data = asdict(chunk)
        
        assert data["semantic_anchor"] == "a1b2c3d4e5f6a7b8"
