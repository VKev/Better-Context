
"""
File scanning and binary detection for better-context.

Provides file discovery, binary detection, and inventory building.
Uses only stdlib for zero-dependency operation.
"""

from __future__ import annotations

import hashlib
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, List, Optional

from .ignore import load_ignore_patterns, should_ignore, should_ignore_dir

# Known binary file extensions (skip without reading)
BINARY_EXTENSIONS: frozenset[str] = frozenset({
    # Images
    '.png', '.jpg', '.jpeg', '.gif', '.bmp', '.ico', '.webp', '.svg',
    '.tiff', '.tif', '.psd', '.raw', '.heic', '.heif',
    # Documents
    '.pdf', '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx',
    '.odt', '.ods', '.odp',
    # Archives
    '.zip', '.tar', '.gz', '.rar', '.7z', '.bz2', '.xz', '.zst',
    '.tgz', '.tbz2', '.txz',
    # Executables
    '.exe', '.dll', '.so', '.dylib', '.bin', '.app',
    '.msi', '.dmg', '.deb', '.rpm',
    # Media
    '.mp3', '.mp4', '.avi', '.mov', '.wav', '.flac', '.ogg',
    '.mkv', '.webm', '.m4a', '.m4v', '.aac', '.wma', '.wmv',
    # Fonts
    '.ttf', '.otf', '.woff', '.woff2', '.eot',
    # Data
    '.db', '.sqlite', '.sqlite3', '.mdb',
    # Compiled
    '.pyc', '.pyo', '.class', '.o', '.obj', '.a', '.lib',
    '.beam', '.elc',
    # Other binary
    '.DS_Store', '.ico', '.cur',
})


# Default maximum file size (1MB)
DEFAULT_MAX_FILE_SIZE_KB = 1024
UNITY_STREAMED_ASSET_EXTENSIONS: frozenset[str] = frozenset(
    {
        ".anim",
        ".asset",
        ".controller",
        ".mat",
        ".overridecontroller",
        ".prefab",
        ".unity",
    }
)

INDEXED_BINARY_EXTENSIONS: frozenset[str] = frozenset(
    {
        ".aif",
        ".aiff",
        ".avi",
        ".bmp",
        ".exr",
        ".fbx",
        ".flac",
        ".gif",
        ".hdr",
        ".jpeg",
        ".jpg",
        ".mov",
        ".mp3",
        ".mp4",
        ".ogg",
        ".otf",
        ".png",
        ".psd",
        ".svg",
        ".tga",
        ".tif",
        ".tiff",
        ".ttf",
        ".wav",
        ".webm",
    }
)

@dataclass
class FileInfo:
    """Information about a single discovered file."""
    path: str                      # Relative path from root
    absolute_path: Path            # Absolute path
    size_bytes: int                # File size
    extension: str                 # e.g., '.py', '.ts'
    language: Optional[str]        # Detected language (set later)
    content_hash: str              # SHA-256 first 16 chars
    mtime: float                   # Modification time
    is_binary: bool                # Result of binary check


@dataclass
class FileInventory:
    """Result of scanning a repository."""
    root: Path
    files: List[FileInfo] = field(default_factory=list)
    skipped_binary: List[str] = field(default_factory=list)
    skipped_ignored: List[str] = field(default_factory=list)
    skipped_too_large: List[str] = field(default_factory=list)
    skipped_permission: List[str] = field(default_factory=list)
    skipped_read_error: List[str] = field(default_factory=list)
    scan_time_ms: int = 0


def is_binary_extension(path: Path) -> bool:
    """
    Check if file has a known binary extension.
    
    This is O(1) lookup - fast check before reading file.
    
    Args:
        path: File path
    
    Returns:
        True if extension indicates binary file
    """
    ext = path.suffix.lower()
    return ext in BINARY_EXTENSIONS


def is_text_file(path: Path, sample_size: int = 2048) -> bool:
    """
    Check if file is text by looking for null bytes.
    
    Binary files almost always contain null bytes in the first few KB.
    Text files (including UTF-8) do not contain null bytes.
    
    Args:
        path: File path
        sample_size: Number of bytes to read (default 2048)
    
    Returns:
        True if file appears to be text, False if binary or unreadable
    """
    try:
        with open(path, 'rb') as f:
            chunk = f.read(sample_size)
        
        # Empty files are treated as text (safe to process)
        if not chunk:
            return True
        
        # Check for null bytes
        if b'\x00' in chunk:
            # Exception: UTF-16/UTF-32 files may have nulls
            # Check for BOM at start
            if chunk.startswith((
                b'\xff\xfe',      # UTF-16 LE
                b'\xfe\xff',      # UTF-16 BE
                b'\xff\xfe\x00\x00',  # UTF-32 LE
                b'\x00\x00\xfe\xff',  # UTF-32 BE
            )):
                return True  # It's a valid Unicode file
            return False
        
        return True
        
    except OSError:
        return False


def is_streamed_unity_asset(path: Path, sample_size: int = 2048) -> bool:
    """Return whether an asset uses Unity's inspectable streamed-YAML format."""
    if path.suffix.lower() not in UNITY_STREAMED_ASSET_EXTENSIONS:
        return False
    try:
        with path.open("rb") as stream:
            prefix = stream.read(sample_size)
    except OSError:
        return False
    if b"\x00" in prefix:
        return False
    prefix = prefix.removeprefix(b"\xef\xbb\xbf").lstrip()
    return prefix.startswith(b"%YAML") or prefix.startswith(b"--- !u!")


def detect_encoding(path: Path) -> Optional[str]:
    """
    Attempt to detect file encoding.
    
    Tries common encodings in order of likelihood.
    
    Args:
        path: File path
    
    Returns:
        Encoding name if detected, None if unknown
    """
    # Check for BOM first
    try:
        with open(path, 'rb') as f:
            bom = f.read(4)
        
        if bom.startswith(b'\xef\xbb\xbf'):
            return 'utf-8-sig'
        if bom.startswith(b'\xff\xfe\x00\x00'):
            return 'utf-32-le'
        if bom.startswith(b'\x00\x00\xfe\xff'):
            return 'utf-32-be'
        if bom.startswith(b'\xff\xfe'):
            return 'utf-16-le'
        if bom.startswith(b'\xfe\xff'):
            return 'utf-16-be'
    except OSError:
        return None
    
    # Try common encodings
    encodings = ['utf-8', 'latin-1', 'cp1252', 'iso-8859-1']
    
    for encoding in encodings:
        try:
            with open(path, 'r', encoding=encoding) as f:
                f.read(1024)  # Read a sample
            return encoding
        except (OSError, UnicodeDecodeError):
            continue
    
    return None


def can_process_file(path: Path, sample_size: int = 2048) -> bool:
    """
    Check if a file can be processed (is text and readable).
    
    Combines extension check and null-byte detection.
    
    Args:
        path: File path
        sample_size: Bytes to read for null-byte check
    
    Returns:
        True if file can be processed as text
    """
    # Fast path: known binary extension
    if is_binary_extension(path):
        return False
    
    # Slow path: read and check for null bytes
    return is_text_file(path, sample_size)


def compute_file_hash(path: Path, max_bytes: int = 65536) -> str:
    """
    Compute a content hash for a file.
    
    Uses first 64KB by default. Pass a negative limit for a streaming full-file
    hash when late-file changes must participate in staleness checks.
    
    Args:
        path: File path
        max_bytes: Maximum bytes to read for hash
    
    Returns:
        First 16 characters of SHA-256 hash
    """
    try:
        digest = hashlib.sha256()
        with open(path, 'rb') as f:
            if max_bytes < 0:
                while chunk := f.read(1024 * 1024):
                    digest.update(chunk)
            else:
                digest.update(f.read(max_bytes))
        return digest.hexdigest()[:16]
    except OSError:
        return '0' * 16


def walk_repository(
    root: Path,
    ignore_patterns: Optional[List[str]] = None,

    max_file_size_kb: int = DEFAULT_MAX_FILE_SIZE_KB,
    follow_symlinks: bool = False,
    language_detector: Optional[Callable[[Path], Optional[str]]] = None,
) -> FileInventory:
    """
    Walk repository and build file inventory.
    
    Handles:
    - Symlink policy (skip by default, avoid cycles)
    - Permission errors (log and continue)
    - Max file size limits
    - Ignore patterns
    - Binary detection
    
    Args:
        root: Project root directory
        ignore_patterns: List of patterns (if None, loads from .ctxignore)
        max_file_size_kb: Maximum file size in KB (default 1024)
        follow_symlinks: Whether to follow symlinks (default False)
        language_detector: Optional function to detect language from path
    
    Returns:
        FileInventory with discovered files and skip statistics
    """
    start_time = time.time()
    root = Path(root).resolve()
    
    # Load patterns if not provided
    if ignore_patterns is None:
        ignore_patterns = load_ignore_patterns(root)
    
    inventory = FileInventory(root=root)
    max_file_size_bytes = max_file_size_kb * 1024
    
    for dirpath, dirnames, filenames in os.walk(root, followlinks=follow_symlinks):
        dir_path = Path(dirpath)
        rel_dir = dir_path.relative_to(root).as_posix()
        
        # Normalize "." to empty for root
        if rel_dir == '.':
            rel_dir = ''
        
        # Filter directories in-place to skip ignored ones
        # This prevents descending into ignored directories
        filtered_dirs = []
        for d in dirnames:
            if rel_dir:
                dir_rel_path = f"{rel_dir}/{d}"
            else:
                dir_rel_path = d
            
            if should_ignore_dir(dir_rel_path, ignore_patterns):
                inventory.skipped_ignored.append(dir_rel_path + '/')
            else:
                filtered_dirs.append(d)
        
        dirnames[:] = filtered_dirs
        
        # Process files
        for filename in sorted(filenames):  # Sort for determinism
            abs_path = dir_path / filename
            
            if rel_dir:
                rel_path = f"{rel_dir}/{filename}"
            else:
                rel_path = filename
            
            # Check ignore patterns
            if should_ignore(rel_path, ignore_patterns, is_dir=False):
                inventory.skipped_ignored.append(rel_path)
                continue
            
            # Get file stats
            try:
                stat = abs_path.stat()
            except PermissionError:
                inventory.skipped_permission.append(rel_path)
                continue
            except OSError:
                inventory.skipped_read_error.append(rel_path)
                continue
            
            # Check file size
            indexed_binary = abs_path.suffix.lower() in INDEXED_BINARY_EXTENSIONS
            oversized_streamed_unity = stat.st_size > max_file_size_bytes and (
                is_streamed_unity_asset(abs_path) or indexed_binary
            )
            if stat.st_size > max_file_size_bytes and not oversized_streamed_unity:
                inventory.skipped_too_large.append(rel_path)
                continue
            
            # Check binary
            binary = is_binary_extension(abs_path) or not is_text_file(abs_path)
            if binary and not indexed_binary:
                inventory.skipped_binary.append(rel_path)
                continue
            
            # Detect language (if detector provided)
            language = None
            if language_detector:
                try:
                    language = language_detector(abs_path)
                except Exception:
                    pass
            
            # Compute hash
            content_hash = compute_file_hash(
                abs_path,
                -1 if abs_path.suffix.lower() == ".fbx" else 65536,
            )
            
            # Add to inventory
            inventory.files.append(FileInfo(
                path=rel_path,
                absolute_path=abs_path,
                size_bytes=stat.st_size,
                extension=abs_path.suffix.lower(),
                language=language,
                content_hash=content_hash,
                mtime=stat.st_mtime,
                is_binary=binary,
            ))
    
    # Sort files for deterministic output
    inventory.files.sort(key=lambda f: f.path)
    
    inventory.scan_time_ms = int((time.time() - start_time) * 1000)
    
    return inventory


def get_inventory_summary(inventory: FileInventory) -> dict:
    """
    Get a summary of the inventory for reporting.
    
    Args:
        inventory: FileInventory to summarize
    
    Returns:
        Dict with summary statistics
    """
    # Count by extension
    ext_counts: dict[str, int] = {}
    total_bytes = 0
    
    for f in inventory.files:
        ext = f.extension or '(no ext)'
        ext_counts[ext] = ext_counts.get(ext, 0) + 1
        total_bytes += f.size_bytes
    
    return {
        'total_files': len(inventory.files),
        'total_bytes': total_bytes,
        'by_extension': ext_counts,
        'skipped': {
            'binary': len(inventory.skipped_binary),
            'ignored': len(inventory.skipped_ignored),
            'too_large': len(inventory.skipped_too_large),
            'permission': len(inventory.skipped_permission),
            'read_error': len(inventory.skipped_read_error),
        },
        'scan_time_ms': inventory.scan_time_ms,
    }
