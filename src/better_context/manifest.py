"""Manifest JSON schema and types for better-context.

The Manifest is the intermediate JSON format that serves as the contract between
scanning and generation phases. It decouples parsing from output generation.

Key design principles:
- Every field has a clear purpose
- IDs are stable and deterministic
- All positions use 1-based line numbers (human-friendly)
- Optional fields default to sensible values
- Timestamps in ISO 8601 format
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any
import json
from datetime import datetime, timezone

# Schema version - bump on breaking changes
MANIFEST_VERSION = "1.0.0"


@dataclass
class ManifestMeta:
    """Metadata about the manifest generation."""

    version: str  # Schema version (semver)
    generated_at: str  # ISO 8601 timestamp
    generator: str  # 'better-context/1.0.0'
    root_path: str  # Absolute path to analyzed root
    config_hash: str  # Hash of effective config (for cache invalidation)


@dataclass
class ChunkEntry:
    """A semantic code chunk (function, class, method, etc.)."""

    id: str  # Unique ID: 'path:line:type:name'
    type: str  # function, class, interface, type, method
    name: str  # Symbol name
    signature: str  # Full signature (for display)
    start_line: int  # 1-based start line
    end_line: int  # 1-based end line
    parent: str | None = None  # Parent chunk ID (for nested)
    exported: bool = False  # Is this exported?
    docstring: str | None = None  # Extracted docstring
    metadata: dict[str, Any] = field(default_factory=dict)  # Language-specific extras
    semantic_anchor: str | None = None  # Content-addressable ID (stable across moves)


@dataclass
class ImportEntry:
    """An import statement in a file."""

    module: str  # Imported module/file
    symbols: list[str] = field(default_factory=list)  # Imported symbols ([] = entire module)
    alias: str | None = None  # Import alias
    is_relative: bool = False  # Relative import?
    line: int = 0  # Line number


@dataclass
class ExportEntry:
    """An export statement/definition in a file."""

    name: str  # Exported symbol name
    type: str  # function, class, variable, type
    line: int = 0  # Line number
    is_default: bool = False  # Default export? (JS/TS)


@dataclass
class FileEntry:
    """A file in the analyzed codebase."""

    path: str  # Relative to root
    language: str  # Detected language
    size_bytes: int  # File size
    hash: str  # Content hash (SHA-256, first 16 chars)
    chunks: list[ChunkEntry] = field(default_factory=list)  # Code chunks in this file
    imports: list[ImportEntry] = field(default_factory=list)  # Import statements
    exports: list[ExportEntry] = field(default_factory=list)  # Export statements


@dataclass
class GraphData:
    """Dependency graph analysis results."""

    nodes: list[str] = field(default_factory=list)  # File paths
    edges: list[tuple[str, str]] = field(default_factory=list)  # (from_file, to_file)
    centrality: dict[str, float] = field(default_factory=dict)  # PageRank scores
    layers: list[list[str]] = field(default_factory=list)  # Topological layers
    cycles: list[list[str]] = field(default_factory=list)  # Detected cycles (SCCs > 1)


@dataclass
class ParseError:
    """A parse error encountered during analysis."""

    path: str  # File path
    error_type: str  # 'parse', 'encoding', 'resolution'
    message: str  # Error message
    line: int | None = None  # Line number if known


@dataclass
class Manifest:
    """The complete manifest containing all analysis results."""

    meta: ManifestMeta
    files: list[FileEntry] = field(default_factory=list)
    graph: GraphData = field(default_factory=GraphData)
    errors: list[ParseError] = field(default_factory=list)


def create_manifest_meta(root: Path, config_hash: str) -> ManifestMeta:
    """Create manifest metadata with current timestamp.

    Args:
        root: Project root directory
        config_hash: Hash of the effective configuration

    Returns:
        ManifestMeta with current timestamp
    """
    return ManifestMeta(
        version=MANIFEST_VERSION,
        generated_at=datetime.now(timezone.utc).isoformat(),
        generator=f"better-context-unity/{MANIFEST_VERSION}",
        root_path=root.resolve().as_posix(),
        config_hash=config_hash,
    )


def manifest_to_dict(manifest: Manifest) -> dict[str, Any]:
    """Convert manifest to JSON-serializable dict.

    Args:
        manifest: The manifest to convert

    Returns:
        JSON-serializable dictionary
    """

    def convert(obj: Any) -> Any:
        if hasattr(obj, "__dataclass_fields__"):
            return {k: convert(v) for k, v in asdict(obj).items()}
        if isinstance(obj, list):
            return [convert(item) for item in obj]
        if isinstance(obj, tuple):
            return list(obj)
        if isinstance(obj, dict):
            return {k: convert(v) for k, v in obj.items()}
        return obj

    return convert(manifest)


def save_manifest(manifest: Manifest, path: Path) -> None:
    """Save manifest to JSON file.

    Args:
        manifest: The manifest to save
        path: Output file path
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    data = manifest_to_dict(manifest)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def dict_to_manifest(data: dict[str, Any]) -> Manifest:
    """Convert dict from JSON to Manifest.

    Args:
        data: Dictionary from JSON

    Returns:
        Manifest object

    Raises:
        ValueError: If data is malformed
    """
    # Parse meta
    meta_data = data.get("meta", {})
    meta = ManifestMeta(
        version=meta_data.get("version", MANIFEST_VERSION),
        generated_at=meta_data.get("generated_at", ""),
        generator=meta_data.get("generator", ""),
        root_path=meta_data.get("root_path", ""),
        config_hash=meta_data.get("config_hash", ""),
    )

    # Parse files
    files = []
    for f in data.get("files", []):
        chunks = [
            ChunkEntry(
                id=c.get("id", ""),
                type=c.get("type", ""),
                name=c.get("name", ""),
                signature=c.get("signature", ""),
                start_line=c.get("start_line", 0),
                end_line=c.get("end_line", 0),
                parent=c.get("parent"),
                exported=c.get("exported", False),
                docstring=c.get("docstring"),
                metadata=c.get("metadata", {}),
                semantic_anchor=c.get("semantic_anchor"),
            )
            for c in f.get("chunks", [])
        ]
        imports = [
            ImportEntry(
                module=i.get("module", ""),
                symbols=i.get("symbols", []),
                alias=i.get("alias"),
                is_relative=i.get("is_relative", False),
                line=i.get("line", 0),
            )
            for i in f.get("imports", [])
        ]
        exports = [
            ExportEntry(
                name=e.get("name", ""),
                type=e.get("type", ""),
                line=e.get("line", 0),
                is_default=e.get("is_default", False),
            )
            for e in f.get("exports", [])
        ]
        files.append(
            FileEntry(
                path=f.get("path", ""),
                language=f.get("language", ""),
                size_bytes=f.get("size_bytes", 0),
                hash=f.get("hash", ""),
                chunks=chunks,
                imports=imports,
                exports=exports,
            )
        )

    # Parse graph
    graph_data = data.get("graph", {})
    graph = GraphData(
        nodes=graph_data.get("nodes", []),
        edges=[tuple(e) for e in graph_data.get("edges", [])],
        centrality=graph_data.get("centrality", {}),
        layers=graph_data.get("layers", []),
        cycles=graph_data.get("cycles", []),
    )

    # Parse errors
    errors = [
        ParseError(
            path=e.get("path", ""),
            error_type=e.get("error_type", ""),
            message=e.get("message", ""),
            line=e.get("line"),
        )
        for e in data.get("errors", [])
    ]

    return Manifest(meta=meta, files=files, graph=graph, errors=errors)


def load_manifest(path: Path) -> Manifest:
    """Load manifest from JSON file.

    Args:
        path: Path to manifest file

    Returns:
        Loaded manifest

    Raises:
        FileNotFoundError: If file doesn't exist
        ValueError: If JSON is malformed
    """
    data = json.loads(path.read_text(encoding="utf-8"))
    return dict_to_manifest(data)


def validate_manifest(manifest: Manifest) -> list[str]:
    """Validate manifest structure and content.

    Args:
        manifest: Manifest to validate

    Returns:
        List of error messages (empty if valid)
    """
    errors = []

    # Check version
    if not manifest.meta.version:
        errors.append("Missing manifest version")
    elif manifest.meta.version != MANIFEST_VERSION:
        errors.append(f"Version mismatch: expected {MANIFEST_VERSION}, got {manifest.meta.version}")

    # Check required meta fields
    if not manifest.meta.root_path:
        errors.append("Missing root_path in meta")
    if not manifest.meta.generated_at:
        errors.append("Missing generated_at in meta")

    # Validate files
    seen_paths = set()
    for f in manifest.files:
        if not f.path:
            errors.append("File entry missing path")
        elif f.path in seen_paths:
            errors.append(f"Duplicate file path: {f.path}")
        else:
            seen_paths.add(f.path)

        # Validate chunks
        for chunk in f.chunks:
            if not chunk.id:
                errors.append(f"Chunk in {f.path} missing id")
            if chunk.start_line < 1:
                errors.append(f"Chunk {chunk.id} has invalid start_line")
            if chunk.end_line < chunk.start_line:
                errors.append(f"Chunk {chunk.id} has end_line < start_line")

    # Validate graph
    graph_nodes = set(manifest.graph.nodes)
    for from_file, to_file in manifest.graph.edges:
        if from_file not in graph_nodes:
            errors.append(f"Edge from unknown node: {from_file}")
        if to_file not in graph_nodes:
            errors.append(f"Edge to unknown node: {to_file}")

    return errors


@dataclass
class ManifestDiff:
    """Difference between two manifests."""

    added_files: list[str] = field(default_factory=list)
    removed_files: list[str] = field(default_factory=list)
    modified_files: list[str] = field(default_factory=list)
    unchanged_files: list[str] = field(default_factory=list)


def diff_manifests(old: Manifest, new: Manifest) -> ManifestDiff:
    """Compute difference between two manifests.

    Useful for incremental updates - only re-process modified files.

    Args:
        old: Previous manifest
        new: Current manifest

    Returns:
        ManifestDiff describing changes
    """
    old_files = {f.path: f.hash for f in old.files}
    new_files = {f.path: f.hash for f in new.files}

    added = [p for p in new_files if p not in old_files]
    removed = [p for p in old_files if p not in new_files]

    modified = []
    unchanged = []
    for path in set(old_files) & set(new_files):
        if old_files[path] != new_files[path]:
            modified.append(path)
        else:
            unchanged.append(path)

    return ManifestDiff(
        added_files=sorted(added),
        removed_files=sorted(removed),
        modified_files=sorted(modified),
        unchanged_files=sorted(unchanged),
    )
