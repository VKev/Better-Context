"""Semantic Anchors: Content-Addressable Chunk IDs for better-context.

This module implements content-addressable chunk identification based on
normalized AST structures. The key idea is that chunk IDs are derived from
the semantic content of the code, not its location. This means:

1. If a function moves files, its anchor stays valid
2. If whitespace/comments change, the anchor stays valid
3. If the actual logic changes, the anchor changes (as expected)

The anchor is computed as: sha256(normalized_AST_representation)[:16]

Usage:
    from better_context.semantic_anchor import compute_semantic_anchor
    
    anchor = compute_semantic_anchor(source_code, start_line, end_line, language)
    # Returns something like: "a3f2e8c9b1d4a5f7"
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any, Tuple


@dataclass
class SemanticAnchor:
    """A content-addressable identifier for a code chunk.
    
    Attributes:
        anchor_id: The content-based hash (16 hex chars)
        location_id: The traditional location-based ID (path:line:type:name)
        chunk_type: Type of chunk (function, class, method, etc.)
        name: Symbol name
        signature_hash: Hash of just the signature (for quick comparison)
    """
    anchor_id: str
    location_id: str
    chunk_type: str
    name: str
    signature_hash: Optional[str] = None


@dataclass
class AnchorMapping:
    """Mapping from semantic anchors to their current locations.
    
    This enables tracking code as it moves around the codebase.
    
    Attributes:
        anchor_to_location: Maps anchor_id -> (path, line) 
        location_to_anchor: Maps location_id -> anchor_id
        history: List of (anchor_id, old_location, new_location, timestamp) moves
    """
    anchor_to_location: Dict[str, Tuple[str, int]] = field(default_factory=dict)
    location_to_anchor: Dict[str, str] = field(default_factory=dict)
    history: List[Tuple[str, str, str, str]] = field(default_factory=list)


def normalize_python_code(source: str) -> str:
    """Normalize Python code for hashing.
    
    Removes/normalizes:
    - Comments (# and docstrings)
    - Whitespace (except structural indentation markers)
    - String literal contents (replaced with placeholder)
    - Numeric literal formats (1_000 -> 1000)
    
    Preserves:
    - Function/class structure
    - Variable names
    - Control flow
    - Type annotations
    
    Args:
        source: Python source code
        
    Returns:
        Normalized code string
    """
    lines = source.split('\n')
    result_lines = []
    in_docstring = False
    docstring_quote = None
    
    for line in lines:
        stripped = line.strip()
        
        # Skip empty lines
        if not stripped:
            continue
        
        # Handle docstrings
        if in_docstring:
            if docstring_quote in stripped:
                in_docstring = False
            continue
        
        # Check for docstring start
        if stripped.startswith('"""') or stripped.startswith("'''"):
            quote = stripped[:3]
            # Single-line docstring
            if stripped.count(quote) >= 2 and len(stripped) > 6:
                continue  # Skip the whole line
            else:
                in_docstring = True
                docstring_quote = quote
                continue
        
        # Skip pure comment lines
        if stripped.startswith('#'):
            continue
        
        # Remove inline comments
        code_part = stripped.split('#')[0].rstrip()
        if not code_part:
            continue
        
        # Normalize string literals (replace with placeholder)
        # This ensures changes to string contents don't change the anchor
        code_part = re.sub(r'f?["\'][^"\']*["\']', '"STR"', code_part)
        
        # Normalize numeric literals (remove underscores)
        code_part = re.sub(r'(\d)_(\d)', r'\1\2', code_part)
        
        # Normalize whitespace in the line
        code_part = ' '.join(code_part.split())
        
        # Track indentation level (using marker)
        indent_level = (len(line) - len(line.lstrip())) // 4
        result_lines.append(f"I{indent_level}:{code_part}")
    
    return '\n'.join(result_lines)


def normalize_javascript_code(source: str) -> str:
    """Normalize JavaScript/TypeScript code for hashing.
    
    Removes/normalizes:
    - Comments (// and /* */)
    - Whitespace
    - String literal contents
    
    Preserves:
    - Function/class structure
    - Variable names
    - Control flow
    - Type annotations (TypeScript)
    
    Args:
        source: JavaScript/TypeScript source code
        
    Returns:
        Normalized code string
    """
    lines = source.split('\n')
    result_lines = []
    in_block_comment = False
    
    for line in lines:
        stripped = line.strip()
        
        if not stripped:
            continue
        
        # Handle block comments
        if in_block_comment:
            if '*/' in stripped:
                in_block_comment = False
                # Get content after closing comment
                stripped = stripped[stripped.index('*/') + 2:].strip()
                if not stripped:
                    continue
            else:
                continue
        
        # Check for block comment start
        if '/*' in stripped:
            before = stripped[:stripped.index('/*')].strip()
            after_idx = stripped.find('*/', stripped.index('/*'))
            if after_idx >= 0:
                # Single-line block comment
                after = stripped[after_idx + 2:].strip()
                stripped = (before + ' ' + after).strip()
            else:
                in_block_comment = True
                stripped = before
            if not stripped:
                continue
        
        # Remove line comments
        if '//' in stripped:
            # Be careful with URLs (://)
            parts = stripped.split('//')
            code_parts = [parts[0]]
            for part in parts[1:]:
                # Check if this is a URL (preceded by :)
                if code_parts[-1].rstrip().endswith(':'):
                    code_parts.append('//' + part)
                else:
                    break  # Rest is comment
            stripped = ''.join(code_parts).rstrip()
        
        if not stripped:
            continue
        
        # Normalize string literals
        stripped = re.sub(r'`[^`]*`', '"STR"', stripped)  # Template literals
        stripped = re.sub(r'"[^"]*"', '"STR"', stripped)
        stripped = re.sub(r"'[^']*'", '"STR"', stripped)
        
        # Normalize whitespace
        stripped = ' '.join(stripped.split())
        
        # Track brace depth as structure indicator
        open_braces = stripped.count('{') - stripped.count('}')
        result_lines.append(f"B{open_braces}:{stripped}")
    
    return '\n'.join(result_lines)


def normalize_go_code(source: str) -> str:
    """Normalize Go code for hashing.
    
    Removes/normalizes:
    - Comments (// and /* */)
    - Whitespace
    - String literal contents
    
    Preserves:
    - Function/method structure
    - Variable names
    - Control flow
    
    Args:
        source: Go source code
        
    Returns:
        Normalized code string
    """
    # Go normalization is similar to JavaScript
    lines = source.split('\n')
    result_lines = []
    in_block_comment = False
    
    for line in lines:
        stripped = line.strip()
        
        if not stripped:
            continue
        
        # Handle block comments
        if in_block_comment:
            if '*/' in stripped:
                in_block_comment = False
                stripped = stripped[stripped.index('*/') + 2:].strip()
                if not stripped:
                    continue
            else:
                continue
        
        if '/*' in stripped:
            before = stripped[:stripped.index('/*')].strip()
            after_idx = stripped.find('*/', stripped.index('/*'))
            if after_idx >= 0:
                after = stripped[after_idx + 2:].strip()
                stripped = (before + ' ' + after).strip()
            else:
                in_block_comment = True
                stripped = before
            if not stripped:
                continue
        
        # Remove line comments
        if '//' in stripped:
            stripped = stripped[:stripped.index('//')].rstrip()
        
        if not stripped:
            continue
        
        # Normalize string literals
        stripped = re.sub(r'`[^`]*`', '"STR"', stripped)  # Raw strings
        stripped = re.sub(r'"[^"]*"', '"STR"', stripped)
        
        # Normalize whitespace
        stripped = ' '.join(stripped.split())
        
        result_lines.append(stripped)
    
    return '\n'.join(result_lines)


def normalize_code(source: str, language: str) -> str:
    """Normalize source code based on language.
    
    Args:
        source: Source code to normalize
        language: Language identifier
        
    Returns:
        Normalized code string
    """
    normalizers = {
        'python': normalize_python_code,
        'javascript': normalize_javascript_code,
        'typescript': normalize_javascript_code,  # Same normalizer
        'go': normalize_go_code,
    }
    
    normalizer = normalizers.get(language)
    if normalizer:
        return normalizer(source)
    
    # Fallback: basic normalization
    lines = source.split('\n')
    result = []
    for line in lines:
        stripped = line.strip()
        if stripped:
            result.append(stripped)
    return '\n'.join(result)


def compute_hash(content: str, length: int = 16) -> str:
    """Compute a truncated SHA-256 hash of content.
    
    Args:
        content: String to hash
        length: Number of hex characters to return (default 16)
        
    Returns:
        Hex string of specified length
    """
    return hashlib.sha256(content.encode('utf-8')).hexdigest()[:length]


def compute_semantic_anchor(
    source: str,
    start_line: int,
    end_line: int,
    language: str,
    name: Optional[str] = None,
    chunk_type: Optional[str] = None,
) -> str:
    """Compute a semantic anchor ID for a code chunk.
    
    The anchor is based on the normalized content of the chunk,
    making it stable across file moves, whitespace changes, and
    comment modifications.
    
    Args:
        source: Full source code of the file
        start_line: 1-based start line of the chunk
        end_line: 1-based end line of the chunk
        language: Language identifier
        name: Optional symbol name (included in hash for disambiguation)
        chunk_type: Optional chunk type (included in hash)
        
    Returns:
        16-character hex string anchor ID
    """
    lines = source.split('\n')
    
    # Extract chunk content (convert to 0-based indexing)
    chunk_lines = lines[start_line - 1:end_line]
    chunk_source = '\n'.join(chunk_lines)
    
    # Normalize the chunk
    normalized = normalize_code(chunk_source, language)
    
    # Include name and type for disambiguation (two functions with same
    # body but different names should have different anchors)
    if name:
        normalized = f"NAME:{name}\n{normalized}"
    if chunk_type:
        normalized = f"TYPE:{chunk_type}\n{normalized}"
    
    return compute_hash(normalized)


def compute_signature_anchor(signature: str, language: str) -> str:
    """Compute an anchor based on just the signature.
    
    Useful for quick identification when full source isn't needed.
    
    Args:
        signature: Function/class signature
        language: Language identifier
        
    Returns:
        8-character hex string
    """
    # Light normalization for signature
    normalized = ' '.join(signature.split())
    return compute_hash(normalized, length=8)


def generate_anchor_id(
    path: str,
    line: int,
    chunk_type: str,
    name: str,
    source: str,
    language: str,
) -> Tuple[str, str]:
    """Generate both location-based and semantic anchor IDs.
    
    This is the main entry point for generating chunk IDs. It returns
    both the traditional location-based ID and the new semantic anchor.
    
    Args:
        path: File path
        line: Start line number (1-based)
        chunk_type: Type of chunk
        name: Symbol name
        source: Full file source
        language: Language identifier
        
    Returns:
        Tuple of (semantic_anchor_id, location_id)
    """
    # Traditional location-based ID
    location_id = f"{path}:{line}:{chunk_type}:{name}"
    
    # For semantic anchor, we need the chunk content
    # This requires knowing the end line, which we don't have here
    # For now, we create a partial anchor from available info
    # The full anchor should be computed in the chunker with full context
    
    return (None, location_id)  # Anchor to be filled in by chunker


def update_anchor_mapping(
    mapping: AnchorMapping,
    anchor_id: str,
    path: str,
    line: int,
    location_id: str,
    timestamp: Optional[str] = None,
) -> None:
    """Update anchor mapping with new location information.
    
    If the anchor already exists at a different location, this records
    a move event in the history.
    
    Args:
        mapping: The anchor mapping to update
        anchor_id: Semantic anchor ID
        path: Current file path
        line: Current line number
        location_id: Full location-based ID
        timestamp: Optional ISO timestamp for the update
    """
    from datetime import datetime, timezone
    
    if timestamp is None:
        timestamp = datetime.now(timezone.utc).isoformat()
    
    # Check if this anchor exists at a different location
    if anchor_id in mapping.anchor_to_location:
        old_path, old_line = mapping.anchor_to_location[anchor_id]
        old_location_id = mapping.location_to_anchor.get(
            f"{old_path}:{old_line}", ""
        )
        
        if (old_path, old_line) != (path, line):
            # Record the move
            mapping.history.append((
                anchor_id,
                old_location_id,
                location_id,
                timestamp,
            ))
    
    # Update mappings
    mapping.anchor_to_location[anchor_id] = (path, line)
    mapping.location_to_anchor[location_id] = anchor_id


def resolve_anchor(
    mapping: AnchorMapping,
    anchor_id: str,
) -> Optional[Tuple[str, int]]:
    """Resolve a semantic anchor to its current location.
    
    Args:
        mapping: The anchor mapping
        anchor_id: Semantic anchor to resolve
        
    Returns:
        Tuple of (path, line) or None if not found
    """
    return mapping.anchor_to_location.get(anchor_id)


def anchor_mapping_to_dict(mapping: AnchorMapping) -> Dict[str, Any]:
    """Convert anchor mapping to JSON-serializable dict."""
    return {
        'anchor_to_location': {
            k: {'path': v[0], 'line': v[1]} 
            for k, v in mapping.anchor_to_location.items()
        },
        'location_to_anchor': mapping.location_to_anchor,
        'history': [
            {
                'anchor': h[0],
                'old_location': h[1],
                'new_location': h[2],
                'timestamp': h[3],
            }
            for h in mapping.history
        ],
    }


def dict_to_anchor_mapping(data: Dict[str, Any]) -> AnchorMapping:
    """Convert dict to AnchorMapping."""
    return AnchorMapping(
        anchor_to_location={
            k: (v['path'], v['line'])
            for k, v in data.get('anchor_to_location', {}).items()
        },
        location_to_anchor=data.get('location_to_anchor', {}),
        history=[
            (h['anchor'], h['old_location'], h['new_location'], h['timestamp'])
            for h in data.get('history', [])
        ],
    )


__all__ = [
    'SemanticAnchor',
    'AnchorMapping',
    'compute_semantic_anchor',
    'compute_signature_anchor',
    'compute_hash',
    'normalize_code',
    'normalize_python_code',
    'normalize_javascript_code',
    'normalize_go_code',
    'generate_anchor_id',
    'update_anchor_mapping',
    'resolve_anchor',
    'anchor_mapping_to_dict',
    'dict_to_anchor_mapping',
]
