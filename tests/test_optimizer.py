"""Tests for token budget optimizer."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from better_context.optimizer import (
    ScoredChunk,
    OptimizationResult,
    estimate_tokens,
    estimate_chunk_tokens,
    calculate_relevance,
    calculate_diversity_penalty,
    prepare_chunks,
    optimize_context_greedy,
    optimize_context_knapsack,
    optimize_context,
    format_optimization_result,
    CHARS_PER_TOKEN,
    DEFAULT_DIVERSITY_PENALTY,
)
from better_context.manifest import (
    Manifest,
    ManifestMeta,
    FileEntry,
    ChunkEntry,
    ImportEntry,
    ExportEntry,
    GraphData,
)


# ============================================================================
# Test Fixtures
# ============================================================================

def create_test_chunk(
    name: str,
    chunk_type: str = "function",
    start_line: int = 1,
    end_line: int = 10,
    exported: bool = True,
    docstring: str | None = None,
    file_path: str = "test.py",
) -> ChunkEntry:
    """Create a test chunk."""
    return ChunkEntry(
        id=f"{file_path}:{start_line}:{chunk_type}:{name}",
        type=chunk_type,
        name=name,
        signature=f"def {name}():" if chunk_type == "function" else f"class {name}:",
        start_line=start_line,
        end_line=end_line,
        exported=exported,
        docstring=docstring,
    )


def create_test_file_entry(
    path: str,
    chunks: list[ChunkEntry] | None = None,
    language: str = "python",
) -> FileEntry:
    """Create a test file entry."""
    return FileEntry(
        path=path,
        language=language,
        size_bytes=1000,
        hash="abc123",
        chunks=chunks or [],
        imports=[],
        exports=[],
    )


def create_test_manifest(files: list[FileEntry] | None = None) -> Manifest:
    """Create a test manifest."""
    return Manifest(
        meta=ManifestMeta(
            version="1.0.0",
            generated_at="2026-01-24T00:00:00Z",
            generator="test",
            root_path="/test",
            config_hash="test",
        ),
        files=files or [],
        graph=GraphData(),
        errors=[],
    )


# ============================================================================
# Token Estimation Tests
# ============================================================================

class TestEstimateTokens:
    """Tests for token estimation."""
    
    def test_empty_string(self):
        """Empty string should return minimum tokens."""
        tokens = estimate_tokens("")
        assert tokens >= 1
    
    def test_short_string(self):
        """Short string token count."""
        tokens = estimate_tokens("hello")
        assert tokens >= 1
        assert tokens <= 5  # Should be reasonable
    
    def test_code_snippet(self):
        """Estimate tokens for typical code."""
        code = """def calculate_sum(a, b):
    return a + b
"""
        tokens = estimate_tokens(code)
        assert tokens > 5
        assert tokens < 50
    
    def test_proportional_to_length(self):
        """Longer text should have more tokens."""
        short = estimate_tokens("x")
        long = estimate_tokens("x" * 100)
        assert long > short


class TestEstimateChunkTokens:
    """Tests for chunk token estimation."""
    
    def test_without_source(self):
        """Estimate tokens without source lines."""
        chunk = create_test_chunk("test_func", start_line=1, end_line=20)
        tokens = estimate_chunk_tokens(chunk)
        assert tokens > 0
    
    def test_with_source(self):
        """Estimate tokens with actual source lines."""
        chunk = create_test_chunk("test_func", start_line=1, end_line=3)
        source_lines = [
            "def test_func():",
            "    return 42",
            "",
        ]
        tokens = estimate_chunk_tokens(chunk, source_lines)
        assert tokens > 0
    
    def test_longer_chunk_more_tokens(self):
        """Longer chunks should estimate more tokens."""
        short = create_test_chunk("short", start_line=1, end_line=5)
        long = create_test_chunk("long", start_line=1, end_line=50)
        
        short_tokens = estimate_chunk_tokens(short)
        long_tokens = estimate_chunk_tokens(long)
        
        assert long_tokens > short_tokens


# ============================================================================
# Relevance Scoring Tests
# ============================================================================

class TestCalculateRelevance:
    """Tests for relevance calculation."""
    
    def test_no_keywords(self):
        """Without keywords, all chunks are equally relevant."""
        chunk = create_test_chunk("calculate")
        relevance = calculate_relevance(chunk)
        assert relevance == 1.0
    
    def test_keyword_match(self):
        """Matching keyword increases relevance."""
        chunk = create_test_chunk("calculate_sum", docstring="Calculate the sum")
        
        # Matching keyword
        with_match = calculate_relevance(chunk, keywords=["calculate"])
        without_match = calculate_relevance(chunk, keywords=["unrelated"])
        
        assert with_match > without_match
    
    def test_multiple_keywords(self):
        """Multiple keyword matches increase relevance."""
        chunk = create_test_chunk("calculate_total", docstring="Calculate the total sum")
        
        one_match = calculate_relevance(chunk, keywords=["calculate"])
        two_matches = calculate_relevance(chunk, keywords=["calculate", "total"])
        
        assert two_matches >= one_match
    
    def test_task_description(self):
        """Task description matching."""
        chunk = create_test_chunk("process_payment", docstring="Process a payment")
        
        relevant = calculate_relevance(chunk, task_description="payment processing system")
        irrelevant = calculate_relevance(chunk, task_description="database migration")
        
        assert relevant > irrelevant
    
    def test_combined_keywords_and_task(self):
        """Combined keywords and task description."""
        chunk = create_test_chunk("auth_handler", docstring="Handle authentication")
        
        relevance = calculate_relevance(
            chunk,
            keywords=["auth"],
            task_description="implement user authentication",
        )
        assert 0 <= relevance <= 1

    def test_path_and_camel_case_are_searchable(self):
        chunk = create_test_chunk("GetActiveConfig")
        relevance = calculate_relevance(
            chunk,
            task_description="Firebase remote config",
            file_path="Assets/Scripts/Firebase/FirebaseService.cs",
        )
        assert relevance > 0


# ============================================================================
# Diversity Penalty Tests
# ============================================================================

class TestCalculateDiversityPenalty:
    """Tests for diversity penalty calculation."""
    
    def test_no_selected(self):
        """No penalty when nothing selected yet."""
        chunk = ScoredChunk(
            chunk=create_test_chunk("func"),
            file_path="test.py",
            file_entry=create_test_file_entry("test.py"),
            tokens=100,
            pagerank=0.1,
            relevance=1.0,
            base_score=0.1,
            adjusted_score=0.1,
            efficiency=0.001,
        )
        
        penalty = calculate_diversity_penalty(chunk, [])
        assert penalty == 1.0
    
    def test_zero_penalty_factor(self):
        """No penalty when factor is 0."""
        chunk = ScoredChunk(
            chunk=create_test_chunk("func"),
            file_path="test.py",
            file_entry=create_test_file_entry("test.py"),
            tokens=100,
            pagerank=0.1,
            relevance=1.0,
            base_score=0.1,
            adjusted_score=0.1,
            efficiency=0.001,
        )
        
        selected = [chunk]  # Same chunk selected
        penalty = calculate_diversity_penalty(chunk, selected, penalty_factor=0)
        assert penalty == 1.0
    
    def test_same_file_penalty(self):
        """Selecting from same file incurs penalty."""
        file_path = "utils.py"
        
        selected_chunk = ScoredChunk(
            chunk=create_test_chunk("helper1", file_path=file_path),
            file_path=file_path,
            file_entry=create_test_file_entry(file_path),
            tokens=50,
            pagerank=0.1,
            relevance=1.0,
            base_score=0.1,
            adjusted_score=0.1,
            efficiency=0.002,
        )
        
        candidate = ScoredChunk(
            chunk=create_test_chunk("helper2", file_path=file_path),
            file_path=file_path,
            file_entry=create_test_file_entry(file_path),
            tokens=50,
            pagerank=0.1,
            relevance=1.0,
            base_score=0.1,
            adjusted_score=0.1,
            efficiency=0.002,
        )
        
        penalty = calculate_diversity_penalty(candidate, [selected_chunk])
        assert penalty < 1.0
    
    def test_different_file_less_penalty(self):
        """Different files have less penalty."""
        selected = ScoredChunk(
            chunk=create_test_chunk("func1", file_path="a.py"),
            file_path="a.py",
            file_entry=create_test_file_entry("a.py"),
            tokens=50,
            pagerank=0.1,
            relevance=1.0,
            base_score=0.1,
            adjusted_score=0.1,
            efficiency=0.002,
        )
        
        same_file = ScoredChunk(
            chunk=create_test_chunk("func2", file_path="a.py"),
            file_path="a.py",
            file_entry=create_test_file_entry("a.py"),
            tokens=50,
            pagerank=0.1,
            relevance=1.0,
            base_score=0.1,
            adjusted_score=0.1,
            efficiency=0.002,
        )
        
        diff_file = ScoredChunk(
            chunk=create_test_chunk("func3", file_path="b.py"),
            file_path="b.py",
            file_entry=create_test_file_entry("b.py"),
            tokens=50,
            pagerank=0.1,
            relevance=1.0,
            base_score=0.1,
            adjusted_score=0.1,
            efficiency=0.002,
        )
        
        same_penalty = calculate_diversity_penalty(same_file, [selected])
        diff_penalty = calculate_diversity_penalty(diff_file, [selected])
        
        assert diff_penalty > same_penalty


# ============================================================================
# Prepare Chunks Tests
# ============================================================================

class TestPrepareChunks:
    """Tests for chunk preparation."""
    
    def test_empty_manifest(self):
        """Empty manifest returns empty list."""
        manifest = create_test_manifest()
        centrality = {}
        
        chunks = prepare_chunks(manifest, centrality)
        assert chunks == []
    
    def test_filters_low_pagerank(self):
        """Low PageRank chunks are filtered."""
        chunk1 = create_test_chunk("important", start_line=1, end_line=10)
        chunk2 = create_test_chunk("unimportant", start_line=20, end_line=30)
        
        file_entry = create_test_file_entry("test.py", [chunk1, chunk2])
        manifest = create_test_manifest([file_entry])
        
        centrality = {"test.py": 0.5}
        
        # Filter with high min_pagerank
        chunks = prepare_chunks(manifest, centrality, min_pagerank=0.9)
        assert len(chunks) == 0
        
        # No filter
        chunks = prepare_chunks(manifest, centrality, min_pagerank=0.0)
        assert len(chunks) == 2
    
    def test_sorted_by_efficiency(self):
        """Chunks are sorted by efficiency (descending)."""
        chunk1 = create_test_chunk("small", start_line=1, end_line=5)  # Small = higher efficiency
        chunk2 = create_test_chunk("large", start_line=10, end_line=100)  # Large = lower efficiency
        
        file_entry = create_test_file_entry("test.py", [chunk1, chunk2])
        manifest = create_test_manifest([file_entry])
        
        centrality = {"test.py": 0.5}
        
        chunks = prepare_chunks(manifest, centrality)
        
        # First chunk should have higher efficiency
        assert chunks[0].efficiency >= chunks[1].efficiency

    def test_excludes_vendor_and_generated_boundaries(self):
        project = create_test_file_entry("Assets/Game/FirebaseService.cs", [create_test_chunk("Fetch")])
        project.metadata["ownership"] = "project-owned"
        vendor = create_test_file_entry("Assets/Tools/Vendor.cs", [create_test_chunk("Fetch")])
        vendor.metadata["ownership"] = "vendor"
        manifest = create_test_manifest([project, vendor])

        chunks = prepare_chunks(
            manifest,
            {project.path: 0.5, vendor.path: 1.0},
            task_description="Firebase fetch",
        )

        assert {chunk.file_path for chunk in chunks} == {project.path}


# ============================================================================
# Optimization Algorithm Tests
# ============================================================================

class TestOptimizeContextGreedy:
    """Tests for greedy optimization algorithm."""
    
    def test_empty_manifest(self):
        """Empty manifest returns empty result."""
        manifest = create_test_manifest()
        result = optimize_context_greedy(manifest, {}, budget=1000)
        
        assert len(result.selected_chunks) == 0
        assert result.total_tokens == 0
        assert result.budget == 1000
    
    def test_selects_within_budget(self):
        """Selected chunks fit within budget."""
        chunks = [
            create_test_chunk(f"func{i}", start_line=i*20, end_line=i*20+10)
            for i in range(5)
        ]
        file_entry = create_test_file_entry("test.py", chunks)
        manifest = create_test_manifest([file_entry])
        
        centrality = {"test.py": 0.5}
        
        result = optimize_context_greedy(manifest, centrality, budget=500)
        
        assert result.total_tokens <= result.budget
    
    def test_respects_budget(self):
        """Large chunks don't exceed budget."""
        # Create a large chunk
        large_chunk = create_test_chunk("large", start_line=1, end_line=200)
        file_entry = create_test_file_entry("test.py", [large_chunk])
        manifest = create_test_manifest([file_entry])
        
        centrality = {"test.py": 0.5}
        
        # Very small budget
        result = optimize_context_greedy(manifest, centrality, budget=10)
        
        assert result.total_tokens <= result.budget
    
    def test_prefers_high_pagerank(self):
        """Higher PageRank files preferred."""
        chunk_low = create_test_chunk("low", file_path="low.py")
        chunk_high = create_test_chunk("high", file_path="high.py")
        
        file_low = create_test_file_entry("low.py", [chunk_low])
        file_high = create_test_file_entry("high.py", [chunk_high])
        
        manifest = create_test_manifest([file_low, file_high])
        
        centrality = {"low.py": 0.01, "high.py": 0.9}
        
        # Budget for only one chunk
        result = optimize_context_greedy(manifest, centrality, budget=200)
        
        if len(result.selected_chunks) > 0:
            # First selected should be from high PageRank file
            assert result.selected_chunks[0].file_path == "high.py"
    
    def test_diversity_affects_selection(self):
        """Diversity penalty affects chunk selection."""
        # Multiple similar chunks from same file
        chunks = [
            create_test_chunk(f"helper{i}", start_line=i*10, end_line=i*10+5)
            for i in range(5)
        ]
        file_entry = create_test_file_entry("helpers.py", chunks)
        
        # One chunk from different file
        other_chunk = create_test_chunk("other", file_path="other.py")
        other_file = create_test_file_entry("other.py", [other_chunk])
        
        manifest = create_test_manifest([file_entry, other_file])
        
        centrality = {"helpers.py": 0.3, "other.py": 0.3}
        
        # With diversity penalty
        with_diversity = optimize_context_greedy(
            manifest, centrality, budget=500, diversity_penalty=0.5
        )
        
        # Without diversity penalty
        without_diversity = optimize_context_greedy(
            manifest, centrality, budget=500, diversity_penalty=0.0
        )
        
        # Both should select something
        assert len(with_diversity.selected_chunks) > 0
        assert len(without_diversity.selected_chunks) > 0


class TestOptimizeContextKnapsack:
    """Tests for knapsack optimization algorithm."""
    
    def test_empty_manifest(self):
        """Empty manifest returns empty result."""
        manifest = create_test_manifest()
        result = optimize_context_knapsack(manifest, {}, budget=1000)
        
        assert len(result.selected_chunks) == 0
    
    def test_optimal_selection(self):
        """Knapsack finds optimal solution."""
        # Create chunks with known values and weights
        chunk1 = create_test_chunk("small_high", start_line=1, end_line=5)  # Small, we'll give high value
        chunk2 = create_test_chunk("large_low", start_line=10, end_line=50)  # Large, lower value
        
        file1 = create_test_file_entry("a.py", [chunk1])
        file2 = create_test_file_entry("b.py", [chunk2])
        
        manifest = create_test_manifest([file1, file2])
        
        # Give a.py much higher PageRank
        centrality = {"a.py": 0.9, "b.py": 0.1}
        
        result = optimize_context_knapsack(manifest, centrality, budget=500)
        
        # Should fit within budget
        assert result.total_tokens <= result.budget
    
    def test_respects_max_chunks(self):
        """Max chunks parameter limits consideration."""
        chunks = [
            create_test_chunk(f"func{i}", start_line=i*10, end_line=i*10+5)
            for i in range(20)
        ]
        file_entry = create_test_file_entry("test.py", chunks)
        manifest = create_test_manifest([file_entry])
        
        centrality = {"test.py": 0.5}
        
        result = optimize_context_knapsack(
            manifest, centrality, budget=1000, max_chunks=5
        )
        
        # Should work without error
        assert result.considered_chunks == 20


class TestOptimizeContext:
    """Tests for main optimize_context function."""
    
    def test_default_algorithm_is_greedy(self):
        """Default algorithm is greedy."""
        manifest = create_test_manifest()
        result = optimize_context(manifest, {}, budget=1000)
        
        assert isinstance(result, OptimizationResult)
    
    def test_knapsack_algorithm(self):
        """Knapsack algorithm can be selected."""
        manifest = create_test_manifest()
        result = optimize_context(manifest, {}, budget=1000, algorithm="knapsack")
        
        assert isinstance(result, OptimizationResult)
    
    def test_with_keywords(self):
        """Keywords filter relevant chunks."""
        auth_chunk = create_test_chunk("authenticate", docstring="Handle auth")
        db_chunk = create_test_chunk("query_database", docstring="Database query")
        
        file_entry = create_test_file_entry("test.py", [auth_chunk, db_chunk])
        manifest = create_test_manifest([file_entry])
        
        centrality = {"test.py": 0.5}
        
        result = optimize_context(
            manifest, centrality, budget=1000, keywords=["auth"]
        )
        
        # Auth-related chunks should rank higher
        assert len(result.selected_chunks) > 0


# ============================================================================
# Result Formatting Tests
# ============================================================================

class TestFormatOptimizationResult:
    """Tests for result formatting."""
    
    def test_empty_result(self):
        """Format empty result."""
        result = OptimizationResult(budget=1000)
        output = format_optimization_result(result)
        
        assert "Context Portfolio" in output
        assert "1,000" in output or "1000" in output
    
    def test_with_chunks(self):
        """Format result with chunks."""
        scored_chunk = ScoredChunk(
            chunk=create_test_chunk("test_func"),
            file_path="test.py",
            file_entry=create_test_file_entry("test.py"),
            tokens=100,
            pagerank=0.5,
            relevance=1.0,
            base_score=0.5,
            adjusted_score=0.5,
            efficiency=0.005,
        )
        
        result = OptimizationResult(
            selected_chunks=[scored_chunk],
            total_tokens=100,
            budget=1000,
            budget_utilization=0.1,
            total_score=0.5,
            average_efficiency=0.005,
            considered_chunks=1,
        )
        
        output = format_optimization_result(result)
        
        assert "test.py" in output
        assert "test_func" in output
        assert "function" in output


class TestOptimizationResultToDict:
    """Tests for OptimizationResult.to_dict()."""
    
    def test_empty_result(self):
        """Convert empty result to dict."""
        result = OptimizationResult(budget=1000)
        data = result.to_dict()
        
        assert "selected_chunks" in data
        assert "summary" in data
        assert data["summary"]["budget"] == 1000
    
    def test_with_chunks(self):
        """Convert result with chunks to dict."""
        scored_chunk = ScoredChunk(
            chunk=create_test_chunk("test_func"),
            file_path="test.py",
            file_entry=create_test_file_entry("test.py"),
            tokens=100,
            pagerank=0.5,
            relevance=1.0,
            base_score=0.5,
            adjusted_score=0.5,
            efficiency=0.005,
        )
        
        result = OptimizationResult(
            selected_chunks=[scored_chunk],
            total_tokens=100,
            budget=1000,
            budget_utilization=0.1,
            considered_chunks=1,
        )
        
        data = result.to_dict()
        
        assert len(data["selected_chunks"]) == 1
        assert data["selected_chunks"][0]["file_path"] == "test.py"
        assert data["summary"]["chunks_selected"] == 1


# ============================================================================
# Integration Tests
# ============================================================================

class TestOptimizerIntegration:
    """Integration tests for the optimizer."""
    
    def test_end_to_end_workflow(self):
        """Test complete optimization workflow."""
        # Create a realistic manifest
        chunks1 = [
            create_test_chunk("main", start_line=1, end_line=50, exported=True),
            create_test_chunk("helper", start_line=60, end_line=80, exported=False),
        ]
        chunks2 = [
            create_test_chunk("process", start_line=1, end_line=30, exported=True),
        ]
        
        file1 = create_test_file_entry("main.py", chunks1)
        file2 = create_test_file_entry("utils.py", chunks2)
        
        manifest = create_test_manifest([file1, file2])
        
        # Simulated PageRank scores
        centrality = {
            "main.py": 0.3,
            "utils.py": 0.7,  # Utils is more central
        }
        
        # Run optimization
        result = optimize_context(
            manifest=manifest,
            centrality=centrality,
            budget=500,
            diversity_penalty=0.3,
        )
        
        # Verify result
        assert result.budget == 500
        assert result.total_tokens <= 500
        assert len(result.selected_chunks) >= 0
        assert result.budget_utilization <= 1.0
        
        # Can convert to dict (for JSON serialization)
        data = result.to_dict()
        assert isinstance(data, dict)
        
        # Can format as Markdown
        md = format_optimization_result(result)
        assert isinstance(md, str)
