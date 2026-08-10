"""Tests for manifest module."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from better_context.manifest import (
    MANIFEST_VERSION,
    ChunkEntry,
    ExportEntry,
    FileEntry,
    GraphData,
    ImportEntry,
    Manifest,
    ManifestDiff,
    ManifestMeta,
    ParseError,
    create_manifest_meta,
    dict_to_manifest,
    diff_manifests,
    generator_version,
    load_manifest,
    manifest_to_dict,
    save_manifest,
    validate_manifest,
)


class TestManifestMeta:
    """Tests for ManifestMeta dataclass."""

    def test_create_manifest_meta(self):
        """Test creating manifest metadata."""
        meta = create_manifest_meta(Path("/tmp/project"), "abc123")
        
        assert meta.version == MANIFEST_VERSION
        assert meta.generator == f"better-context-unity/{generator_version()}"
        assert "/tmp/project" in meta.root_path
        assert meta.config_hash == "abc123"
        assert meta.generated_at  # Should be non-empty ISO timestamp

    def test_unity_runtime_schema_version(self):
        assert MANIFEST_VERSION == "1.3.0"


class TestChunkEntry:
    """Tests for ChunkEntry dataclass."""

    def test_chunk_entry_defaults(self):
        """Test chunk entry with default values."""
        chunk = ChunkEntry(
            id="test.py:1:function:main",
            type="function",
            name="main",
            signature="def main():",
            start_line=1,
            end_line=10,
        )
        
        assert chunk.parent is None
        assert chunk.exported is False
        assert chunk.docstring is None
        assert chunk.metadata == {}

    def test_chunk_entry_full(self):
        """Test chunk entry with all fields."""
        chunk = ChunkEntry(
            id="test.py:1:class:MyClass",
            type="class",
            name="MyClass",
            signature="class MyClass:",
            start_line=1,
            end_line=50,
            parent=None,
            exported=True,
            docstring="A test class.",
            metadata={"decorators": ["@dataclass"]},
        )
        
        assert chunk.exported is True
        assert chunk.docstring == "A test class."
        assert chunk.metadata["decorators"] == ["@dataclass"]


class TestFileEntry:
    """Tests for FileEntry dataclass."""

    def test_file_entry_minimal(self):
        """Test file entry with minimal data."""
        entry = FileEntry(
            path="src/main.py",
            language="python",
            size_bytes=1024,
            hash="abc123def456",
        )
        
        assert entry.chunks == []
        assert entry.imports == []
        assert entry.exports == []

    def test_file_entry_with_chunks(self):
        """Test file entry with chunks."""
        chunk = ChunkEntry(
            id="src/main.py:1:function:main",
            type="function",
            name="main",
            signature="def main():",
            start_line=1,
            end_line=10,
        )
        
        entry = FileEntry(
            path="src/main.py",
            language="python",
            size_bytes=1024,
            hash="abc123def456",
            chunks=[chunk],
        )
        
        assert len(entry.chunks) == 1
        assert entry.chunks[0].name == "main"


class TestGraphData:
    """Tests for GraphData dataclass."""

    def test_graph_data_defaults(self):
        """Test graph data with defaults."""
        graph = GraphData()
        
        assert graph.nodes == []
        assert graph.edges == []
        assert graph.centrality == {}
        assert graph.layers == []
        assert graph.cycles == []

    def test_graph_data_with_values(self):
        """Test graph data with values."""
        graph = GraphData(
            nodes=["a.py", "b.py", "c.py"],
            edges=[("a.py", "b.py"), ("b.py", "c.py")],
            centrality={"a.py": 0.5, "b.py": 0.3, "c.py": 0.2},
            layers=[["c.py"], ["b.py"], ["a.py"]],
            cycles=[],
        )
        
        assert len(graph.nodes) == 3
        assert len(graph.edges) == 2
        assert graph.centrality["a.py"] == 0.5


class TestManifestSerialization:
    """Tests for manifest serialization."""

    def test_round_trip(self):
        """Test serializing and deserializing a manifest."""
        # Create a manifest
        meta = ManifestMeta(
            version=MANIFEST_VERSION,
            generated_at="2026-01-24T00:00:00+00:00",
            generator=f"better-context/{MANIFEST_VERSION}",
            root_path="/tmp/project",
            config_hash="abc123",
        )
        
        chunk = ChunkEntry(
            id="main.py:1:function:main",
            type="function",
            name="main",
            signature="def main():",
            start_line=1,
            end_line=10,
        )
        
        file_entry = FileEntry(
            path="main.py",
            language="python",
            size_bytes=256,
            hash="def456",
            chunks=[chunk],
            imports=[ImportEntry(module="os", symbols=[], line=1)],
            exports=[ExportEntry(name="main", type="function", line=1)],
        )
        
        graph = GraphData(
            nodes=["main.py"],
            edges=[],
            centrality={"main.py": 1.0},
        )
        
        manifest = Manifest(
            meta=meta,
            files=[file_entry],
            graph=graph,
            errors=[],
        )
        
        # Convert to dict and back
        data = manifest_to_dict(manifest)
        restored = dict_to_manifest(data)
        
        assert restored.meta.version == manifest.meta.version
        assert restored.meta.root_path == manifest.meta.root_path
        assert len(restored.files) == 1
        assert restored.files[0].path == "main.py"
        assert len(restored.files[0].chunks) == 1
        assert restored.files[0].chunks[0].name == "main"

    def test_save_and_load(self):
        """Test saving and loading a manifest file."""
        meta = create_manifest_meta(Path("/tmp/test"), "config-hash")
        manifest = Manifest(meta=meta, files=[], graph=GraphData(), errors=[])
        
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "manifest.json"
            save_manifest(manifest, path)
            
            assert path.exists()
            
            loaded = load_manifest(path)
            assert loaded.meta.version == MANIFEST_VERSION
            assert loaded.meta.config_hash == "config-hash"

    def test_unity_runtime_data_round_trip(self):
        """Compact project data and full per-file topology remain lossless."""
        meta = create_manifest_meta(Path("/tmp/unity"), "config-hash")
        runtime = {
            "path": "Assets/UI/Button.prefab",
            "kind": "prefab",
            "objects": [{"path": "Canvas/Button", "components": ["ButtonView"]}],
        }
        manifest = Manifest(
            meta=meta,
            files=[
                FileEntry(
                    path="Assets/UI/Button.prefab",
                    language="unity-yaml",
                    size_bytes=100,
                    hash="hash",
                    metadata={"unity_runtime": runtime},
                )
            ],
            project={
                "unity_runtime": {
                    "assets": [{"path": runtime["path"], "kind": "prefab"}],
                    "event_bindings": [],
                    "metrics": {"assets": 1},
                    "coverage": {"eligible": 1, "parsed": 1},
                }
            },
        )

        restored = dict_to_manifest(manifest_to_dict(manifest))

        assert restored.project["unity_runtime"]["metrics"]["assets"] == 1
        assert restored.files[0].metadata["unity_runtime"] == runtime


class TestManifestValidation:
    """Tests for manifest validation."""

    def test_valid_manifest(self):
        """Test validating a valid manifest."""
        meta = create_manifest_meta(Path("/tmp/test"), "hash")
        manifest = Manifest(meta=meta, files=[], graph=GraphData(), errors=[])
        
        errors = validate_manifest(manifest)
        assert errors == []

    def test_missing_version(self):
        """Test validation catches missing version."""
        meta = ManifestMeta(
            version="",
            generated_at="2026-01-24T00:00:00Z",
            generator="test",
            root_path="/tmp",
            config_hash="hash",
        )
        manifest = Manifest(meta=meta, files=[], graph=GraphData(), errors=[])
        
        errors = validate_manifest(manifest)
        assert any("version" in e.lower() for e in errors)

    def test_duplicate_file_paths(self):
        """Test validation catches duplicate file paths."""
        meta = create_manifest_meta(Path("/tmp"), "hash")
        file1 = FileEntry(path="same.py", language="python", size_bytes=100, hash="a")
        file2 = FileEntry(path="same.py", language="python", size_bytes=200, hash="b")
        manifest = Manifest(meta=meta, files=[file1, file2], graph=GraphData(), errors=[])
        
        errors = validate_manifest(manifest)
        assert any("duplicate" in e.lower() for e in errors)

    def test_invalid_chunk_lines(self):
        """Test validation catches invalid chunk line numbers."""
        meta = create_manifest_meta(Path("/tmp"), "hash")
        chunk = ChunkEntry(
            id="test:0:function:bad",
            type="function",
            name="bad",
            signature="def bad():",
            start_line=0,  # Invalid: should be >= 1
            end_line=10,
        )
        file_entry = FileEntry(path="test.py", language="python", size_bytes=100, hash="a", chunks=[chunk])
        manifest = Manifest(meta=meta, files=[file_entry], graph=GraphData(), errors=[])
        
        errors = validate_manifest(manifest)
        assert any("start_line" in e or "invalid" in e.lower() for e in errors)


class TestManifestDiff:
    """Tests for manifest diffing."""

    def test_diff_no_changes(self):
        """Test diff with no changes."""
        meta = create_manifest_meta(Path("/tmp"), "hash")
        file1 = FileEntry(path="a.py", language="python", size_bytes=100, hash="same")
        
        old = Manifest(meta=meta, files=[file1], graph=GraphData(), errors=[])
        new = Manifest(meta=meta, files=[file1], graph=GraphData(), errors=[])
        
        diff = diff_manifests(old, new)
        assert diff.added_files == []
        assert diff.removed_files == []
        assert diff.modified_files == []
        assert diff.unchanged_files == ["a.py"]

    def test_diff_added_file(self):
        """Test diff with added file."""
        meta = create_manifest_meta(Path("/tmp"), "hash")
        file1 = FileEntry(path="a.py", language="python", size_bytes=100, hash="a")
        file2 = FileEntry(path="b.py", language="python", size_bytes=200, hash="b")
        
        old = Manifest(meta=meta, files=[file1], graph=GraphData(), errors=[])
        new = Manifest(meta=meta, files=[file1, file2], graph=GraphData(), errors=[])
        
        diff = diff_manifests(old, new)
        assert diff.added_files == ["b.py"]
        assert diff.removed_files == []
        assert diff.unchanged_files == ["a.py"]

    def test_diff_removed_file(self):
        """Test diff with removed file."""
        meta = create_manifest_meta(Path("/tmp"), "hash")
        file1 = FileEntry(path="a.py", language="python", size_bytes=100, hash="a")
        file2 = FileEntry(path="b.py", language="python", size_bytes=200, hash="b")
        
        old = Manifest(meta=meta, files=[file1, file2], graph=GraphData(), errors=[])
        new = Manifest(meta=meta, files=[file1], graph=GraphData(), errors=[])
        
        diff = diff_manifests(old, new)
        assert diff.added_files == []
        assert diff.removed_files == ["b.py"]
        assert diff.unchanged_files == ["a.py"]

    def test_diff_modified_file(self):
        """Test diff with modified file."""
        meta = create_manifest_meta(Path("/tmp"), "hash")
        file_old = FileEntry(path="a.py", language="python", size_bytes=100, hash="old")
        file_new = FileEntry(path="a.py", language="python", size_bytes=150, hash="new")
        
        old = Manifest(meta=meta, files=[file_old], graph=GraphData(), errors=[])
        new = Manifest(meta=meta, files=[file_new], graph=GraphData(), errors=[])
        
        diff = diff_manifests(old, new)
        assert diff.modified_files == ["a.py"]
        assert diff.unchanged_files == []
