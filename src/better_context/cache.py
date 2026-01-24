"""Incremental caching system for parse results.

Implements hash-based caching to avoid re-parsing unchanged files,
making subsequent scans fast.

Features:
- Content-hash based cache keys
- Persistent cache storage (JSON)
- Version-aware cache invalidation
- Cache statistics reporting
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Dict, Optional, Any, List, Tuple, TYPE_CHECKING

if TYPE_CHECKING:
    from .manifest import FileEntry


# Cache version - increment on format changes
CACHE_VERSION = "1.0.0"

# Default cache directory name
CACHE_DIR_NAME = ".better-context"
CACHE_FILE_NAME = "parse_cache.json"


@dataclass
class CacheEntry:
    """A cached parse result entry."""
    
    hash: str                     # Content hash (SHA-256, first 16 chars)
    parse_result: Dict[str, Any]  # Serialized parse result
    timestamp: float              # When cached (Unix timestamp)
    cache_version: str            # Cache format version


@dataclass
class CacheStats:
    """Statistics from a cache operation."""
    
    total_files: int = 0
    cache_hits: int = 0
    cache_misses: int = 0
    files_parsed: List[str] = field(default_factory=list)
    files_cached: List[str] = field(default_factory=list)
    
    @property
    def hit_rate(self) -> float:
        """Calculate cache hit rate as percentage."""
        if self.total_files == 0:
            return 100.0
        return (self.cache_hits / self.total_files) * 100


@dataclass
class Cache:
    """The cache structure stored on disk."""
    
    version: str
    created_at: float
    entries: Dict[str, CacheEntry] = field(default_factory=dict)


class IncrementalCache:
    """Hash-based cache for parse results.
    
    Caches parse results by content hash, allowing unchanged files
    to skip re-parsing on subsequent scans.
    
    Example:
        cache = IncrementalCache(Path('.better-context'))
        
        # Try to get cached result
        content_hash = cache.compute_hash(file_content)
        cached = cache.get('src/main.py', content_hash)
        
        if cached:
            result = cached  # Use cached result
        else:
            result = parse_file(...)  # Parse file
            cache.set('src/main.py', content_hash, result)
        
        cache.commit()  # Save to disk
    """
    
    def __init__(self, cache_dir: Path):
        """Initialize cache.
        
        Args:
            cache_dir: Directory to store cache files
        """
        self.cache_dir = cache_dir
        self.cache_file = cache_dir / CACHE_FILE_NAME
        self._cache = self._load_cache()
        self._modified = False
    
    def _load_cache(self) -> Cache:
        """Load cache from disk or create new."""
        if self.cache_file.exists():
            try:
                data = json.loads(self.cache_file.read_text(encoding='utf-8'))
                
                # Check version compatibility
                if data.get('version') == CACHE_VERSION:
                    entries = {}
                    for path, entry_data in data.get('entries', {}).items():
                        entries[path] = CacheEntry(
                            hash=entry_data['hash'],
                            parse_result=entry_data['parse_result'],
                            timestamp=entry_data['timestamp'],
                            cache_version=entry_data.get('cache_version', CACHE_VERSION),
                        )
                    return Cache(
                        version=CACHE_VERSION,
                        created_at=data.get('created_at', time.time()),
                        entries=entries,
                    )
            except (json.JSONDecodeError, KeyError, TypeError):
                pass
        
        return Cache(version=CACHE_VERSION, created_at=time.time())
    
    def _save_cache(self) -> None:
        """Persist cache to disk."""
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        
        data = {
            'version': self._cache.version,
            'created_at': self._cache.created_at,
            'entries': {
                path: {
                    'hash': entry.hash,
                    'parse_result': entry.parse_result,
                    'timestamp': entry.timestamp,
                    'cache_version': entry.cache_version,
                }
                for path, entry in self._cache.entries.items()
            }
        }
        
        self.cache_file.write_text(
            json.dumps(data, indent=2),
            encoding='utf-8',
        )
        self._modified = False
    
    @staticmethod
    def compute_hash(content: str) -> str:
        """Compute content hash.
        
        Uses SHA-256, truncated to 16 characters for readability.
        
        Args:
            content: File content to hash
        
        Returns:
            16-character hex hash
        """
        return hashlib.sha256(content.encode('utf-8')).hexdigest()[:16]
    
    def get(self, path: str, content_hash: str) -> Optional[Dict[str, Any]]:
        """Get cached parse result if hash matches.
        
        Args:
            path: File path (relative)
            content_hash: Hash of current file content
        
        Returns:
            Cached parse result dict or None if not cached/stale
        """
        entry = self._cache.entries.get(path)
        if entry and entry.hash == content_hash:
            return entry.parse_result
        return None
    
    def set(
        self,
        path: str,
        content_hash: str,
        parse_result: Dict[str, Any],
    ) -> None:
        """Cache a parse result.
        
        Args:
            path: File path (relative)
            content_hash: Hash of file content
            parse_result: Parse result to cache (must be JSON-serializable)
        """
        self._cache.entries[path] = CacheEntry(
            hash=content_hash,
            parse_result=parse_result,
            timestamp=time.time(),
            cache_version=CACHE_VERSION,
        )
        self._modified = True
    
    def invalidate(self, path: str) -> bool:
        """Remove entry from cache.
        
        Args:
            path: File path to invalidate
        
        Returns:
            True if entry was removed, False if not found
        """
        if path in self._cache.entries:
            del self._cache.entries[path]
            self._modified = True
            return True
        return False
    
    def invalidate_pattern(self, pattern: str) -> int:
        """Invalidate all entries matching a glob pattern.
        
        Args:
            pattern: Glob pattern (e.g., 'src/**/*.py')
        
        Returns:
            Number of entries invalidated
        """
        import fnmatch
        
        to_remove = [
            path for path in self._cache.entries
            if fnmatch.fnmatch(path, pattern)
        ]
        
        for path in to_remove:
            del self._cache.entries[path]
        
        if to_remove:
            self._modified = True
        
        return len(to_remove)
    
    def clear(self) -> None:
        """Clear entire cache."""
        self._cache.entries.clear()
        self._modified = True
        
        if self.cache_file.exists():
            self.cache_file.unlink()
    
    def commit(self) -> None:
        """Save cache to disk if modified."""
        if self._modified:
            self._save_cache()
    
    def prune_stale(self, valid_paths: set) -> int:
        """Remove entries for files that no longer exist.
        
        Args:
            valid_paths: Set of current file paths
        
        Returns:
            Number of entries removed
        """
        to_remove = [
            path for path in self._cache.entries
            if path not in valid_paths
        ]
        
        for path in to_remove:
            del self._cache.entries[path]
        
        if to_remove:
            self._modified = True
        
        return len(to_remove)
    
    @property
    def size(self) -> int:
        """Number of cached entries."""
        return len(self._cache.entries)
    
    @property
    def age_seconds(self) -> float:
        """Age of cache in seconds."""
        return time.time() - self._cache.created_at
    
    def get_info(self) -> Dict[str, Any]:
        """Get cache information.
        
        Returns:
            Dict with cache stats and info
        """
        return {
            'version': self._cache.version,
            'entries': self.size,
            'age_seconds': self.age_seconds,
            'cache_file': str(self.cache_file),
            'modified': self._modified,
        }


def get_default_cache_dir(project_root: Path) -> Path:
    """Get the default cache directory for a project.
    
    Args:
        project_root: Project root directory
    
    Returns:
        Path to cache directory
    """
    return project_root / CACHE_DIR_NAME


def create_cache(project_root: Path) -> IncrementalCache:
    """Create a cache for a project.
    
    Args:
        project_root: Project root directory
    
    Returns:
        IncrementalCache instance
    """
    return IncrementalCache(get_default_cache_dir(project_root))


def scan_with_cache(
    files: List[Tuple[str, str]],  # (path, content) pairs
    cache: IncrementalCache,
    parse_func: callable,
) -> Tuple[List[Dict[str, Any]], CacheStats]:
    """Scan files using cache.
    
    Args:
        files: List of (relative_path, content) tuples
        cache: IncrementalCache instance
        parse_func: Function to parse a file: (path, content) -> dict
    
    Returns:
        Tuple of (results, stats)
    """
    results = []
    stats = CacheStats(total_files=len(files))
    
    for path, content in files:
        content_hash = cache.compute_hash(content)
        
        # Try cache first
        cached = cache.get(path, content_hash)
        if cached is not None:
            results.append(cached)
            stats.cache_hits += 1
            stats.files_cached.append(path)
        else:
            # Parse and cache
            result = parse_func(path, content)
            cache.set(path, content_hash, result)
            results.append(result)
            stats.cache_misses += 1
            stats.files_parsed.append(path)
    
    return results, stats


def format_cache_stats(stats: CacheStats) -> str:
    """Format cache statistics for display.
    
    Args:
        stats: CacheStats instance
    
    Returns:
        Formatted string
    """
    lines = [
        f"Cache: {stats.cache_hits}/{stats.total_files} files ({stats.hit_rate:.1f}% hit rate)",
    ]
    
    if stats.files_parsed:
        lines.append(f"Re-parsed: {len(stats.files_parsed)} files")
        if len(stats.files_parsed) <= 5:
            for path in stats.files_parsed:
                lines.append(f"  - {path}")
    
    return '\n'.join(lines)


def format_cache_info(cache: IncrementalCache) -> str:
    """Format cache information for display.
    
    Args:
        cache: IncrementalCache instance
    
    Returns:
        Formatted string
    """
    info = cache.get_info()
    age_mins = info['age_seconds'] / 60
    
    return '\n'.join([
        f"Cache version: {info['version']}",
        f"Entries: {info['entries']}",
        f"Age: {age_mins:.1f} minutes",
        f"Location: {info['cache_file']}",
    ])


# Export public API
__all__ = [
    'CACHE_VERSION',
    'CACHE_DIR_NAME',
    'CacheEntry',
    'CacheStats',
    'Cache',
    'IncrementalCache',
    'get_default_cache_dir',
    'create_cache',
    'scan_with_cache',
    'format_cache_stats',
    'format_cache_info',
]
