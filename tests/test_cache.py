"""Tests for incremental caching system."""

import pytest
import tempfile
import time
from pathlib import Path
import json

from src.better_context.cache import (
    CACHE_VERSION,
    CacheEntry,
    CacheStats,
    IncrementalCache,
    get_default_cache_dir,
    create_cache,
    scan_with_cache,
    format_cache_stats,
    format_cache_info,
)


class TestCacheEntry:
    """Tests for CacheEntry dataclass."""
    
    def test_creation(self):
        entry = CacheEntry(
            hash="abc123",
            parse_result={"chunks": []},
            timestamp=1000.0,
            cache_version="1.0.0",
        )
        assert entry.hash == "abc123"
        assert entry.parse_result == {"chunks": []}
        assert entry.timestamp == 1000.0


class TestCacheStats:
    """Tests for CacheStats dataclass."""
    
    def test_hit_rate_calculation(self):
        stats = CacheStats(
            total_files=10,
            cache_hits=8,
            cache_misses=2,
        )
        assert stats.hit_rate == 80.0
    
    def test_hit_rate_empty(self):
        stats = CacheStats(total_files=0)
        assert stats.hit_rate == 100.0
    
    def test_files_lists(self):
        stats = CacheStats(
            total_files=3,
            cache_hits=2,
            cache_misses=1,
            files_cached=["a.py", "b.py"],
            files_parsed=["c.py"],
        )
        assert len(stats.files_cached) == 2
        assert len(stats.files_parsed) == 1


class TestIncrementalCache:
    """Tests for IncrementalCache class."""
    
    @pytest.fixture
    def cache_dir(self):
        """Create a temporary cache directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)
    
    def test_compute_hash(self):
        """Test hash computation."""
        hash1 = IncrementalCache.compute_hash("hello world")
        hash2 = IncrementalCache.compute_hash("hello world")
        hash3 = IncrementalCache.compute_hash("hello world!")
        
        assert hash1 == hash2
        assert hash1 != hash3
        assert len(hash1) == 16
    
    def test_set_and_get(self, cache_dir):
        """Test basic set and get operations."""
        cache = IncrementalCache(cache_dir)
        
        content_hash = cache.compute_hash("test content")
        cache.set("test.py", content_hash, {"chunks": [1, 2, 3]})
        
        result = cache.get("test.py", content_hash)
        assert result == {"chunks": [1, 2, 3]}
    
    def test_get_returns_none_for_missing(self, cache_dir):
        """Test get returns None for non-existent entry."""
        cache = IncrementalCache(cache_dir)
        
        result = cache.get("missing.py", "abc123")
        assert result is None
    
    def test_get_returns_none_for_stale_hash(self, cache_dir):
        """Test get returns None when hash doesn't match."""
        cache = IncrementalCache(cache_dir)
        
        cache.set("test.py", "hash1", {"data": 1})
        
        # Different hash = stale
        result = cache.get("test.py", "hash2")
        assert result is None
    
    def test_invalidate(self, cache_dir):
        """Test invalidating a cache entry."""
        cache = IncrementalCache(cache_dir)
        
        cache.set("test.py", "abc", {"data": 1})
        assert cache.size == 1
        
        removed = cache.invalidate("test.py")
        assert removed is True
        assert cache.size == 0
        
        # Invalidating non-existent returns False
        removed = cache.invalidate("missing.py")
        assert removed is False
    
    def test_invalidate_pattern(self, cache_dir):
        """Test invalidating entries by pattern."""
        cache = IncrementalCache(cache_dir)
        
        cache.set("src/a.py", "1", {})
        cache.set("src/b.py", "2", {})
        cache.set("tests/test_a.py", "3", {})
        
        count = cache.invalidate_pattern("src/*.py")
        assert count == 2
        assert cache.size == 1
    
    def test_clear(self, cache_dir):
        """Test clearing the cache."""
        cache = IncrementalCache(cache_dir)
        
        cache.set("a.py", "1", {})
        cache.set("b.py", "2", {})
        cache.commit()
        
        cache.clear()
        assert cache.size == 0
        assert not cache.cache_file.exists()
    
    def test_commit_persistence(self, cache_dir):
        """Test that commit persists cache to disk."""
        cache1 = IncrementalCache(cache_dir)
        cache1.set("test.py", "hash123", {"result": "data"})
        cache1.commit()
        
        # Load fresh cache from disk
        cache2 = IncrementalCache(cache_dir)
        result = cache2.get("test.py", "hash123")
        assert result == {"result": "data"}
    
    def test_prune_stale(self, cache_dir):
        """Test pruning entries for deleted files."""
        cache = IncrementalCache(cache_dir)
        
        cache.set("exists.py", "1", {})
        cache.set("deleted.py", "2", {})
        cache.set("also_deleted.py", "3", {})
        
        valid_paths = {"exists.py"}
        count = cache.prune_stale(valid_paths)
        
        assert count == 2
        assert cache.size == 1
        assert cache.get("exists.py", "1") is not None
    
    def test_size_property(self, cache_dir):
        """Test size property."""
        cache = IncrementalCache(cache_dir)
        
        assert cache.size == 0
        
        cache.set("a.py", "1", {})
        assert cache.size == 1
        
        cache.set("b.py", "2", {})
        assert cache.size == 2
    
    def test_get_info(self, cache_dir):
        """Test get_info method."""
        cache = IncrementalCache(cache_dir)
        cache.set("test.py", "abc", {})
        
        info = cache.get_info()
        
        assert info['version'] == CACHE_VERSION
        assert info['entries'] == 1
        assert 'age_seconds' in info
        assert 'cache_file' in info
    
    def test_version_mismatch_clears_cache(self, cache_dir):
        """Test that version mismatch creates fresh cache."""
        # Create cache with different version
        cache_file = cache_dir / "parse_cache.json"
        cache_dir.mkdir(parents=True, exist_ok=True)
        cache_file.write_text(json.dumps({
            'version': '0.0.0',  # Old version
            'entries': {'old.py': {'hash': 'x', 'parse_result': {}, 'timestamp': 0}},
        }))
        
        # Load cache - should ignore old version
        cache = IncrementalCache(cache_dir)
        assert cache.size == 0  # Old entries not loaded
    
    def test_corrupted_cache_creates_fresh(self, cache_dir):
        """Test that corrupted cache file creates fresh cache."""
        cache_file = cache_dir / "parse_cache.json"
        cache_dir.mkdir(parents=True, exist_ok=True)
        cache_file.write_text("{ corrupted json")
        
        cache = IncrementalCache(cache_dir)
        assert cache.size == 0


class TestScanWithCache:
    """Tests for scan_with_cache function."""
    
    @pytest.fixture
    def cache(self):
        """Create a cache in temp directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield IncrementalCache(Path(tmpdir))
    
    def test_caches_parsed_results(self, cache):
        """Test that parsed results are cached."""
        parse_count = [0]
        
        def mock_parse(path, content):
            parse_count[0] += 1
            return {"path": path, "size": len(content)}
        
        files = [
            ("a.py", "content a"),
            ("b.py", "content b"),
        ]
        
        # First scan - all misses
        results1, stats1 = scan_with_cache(files, cache, mock_parse)
        assert len(results1) == 2
        assert stats1.cache_misses == 2
        assert stats1.cache_hits == 0
        assert parse_count[0] == 2
        
        # Second scan - all hits
        results2, stats2 = scan_with_cache(files, cache, mock_parse)
        assert len(results2) == 2
        assert stats2.cache_hits == 2
        assert stats2.cache_misses == 0
        assert parse_count[0] == 2  # No new parses
    
    def test_detects_changed_files(self, cache):
        """Test that changed files are re-parsed."""
        parse_count = [0]
        
        def mock_parse(path, content):
            parse_count[0] += 1
            return {"content": content}
        
        # Initial scan
        files1 = [("test.py", "original")]
        results1, stats1 = scan_with_cache(files1, cache, mock_parse)
        assert parse_count[0] == 1
        
        # Changed content
        files2 = [("test.py", "modified")]
        results2, stats2 = scan_with_cache(files2, cache, mock_parse)
        assert parse_count[0] == 2  # Re-parsed
        assert stats2.cache_misses == 1


class TestFormatFunctions:
    """Tests for formatting functions."""
    
    def test_format_cache_stats(self):
        """Test format_cache_stats function."""
        stats = CacheStats(
            total_files=10,
            cache_hits=8,
            cache_misses=2,
            files_parsed=["new.py", "changed.py"],
        )
        
        result = format_cache_stats(stats)
        
        assert "80.0%" in result
        assert "8/10" in result
        assert "Re-parsed" in result
    
    def test_format_cache_info(self):
        """Test format_cache_info function."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache = IncrementalCache(Path(tmpdir))
            cache.set("test.py", "abc", {})
            
            result = format_cache_info(cache)
            
            assert CACHE_VERSION in result
            assert "1" in result  # Entry count


class TestGetDefaultCacheDir:
    """Tests for get_default_cache_dir function."""
    
    def test_returns_better_context_dir(self):
        """Test that default cache dir is .better-context."""
        project_root = Path("/home/user/project")
        result = get_default_cache_dir(project_root)
        
        assert result == project_root / ".better-context"


class TestCreateCache:
    """Tests for create_cache function."""
    
    def test_creates_cache_instance(self):
        """Test that create_cache returns IncrementalCache."""
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            cache = create_cache(project_root)
            
            assert isinstance(cache, IncrementalCache)
            assert cache.cache_dir == project_root / ".better-context"
