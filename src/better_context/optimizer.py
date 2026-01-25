"""Token Budget Portfolio Optimizer for better-context.

Given a token budget, returns the mathematically optimal context "portfolio"—
the subset of code chunks that maximizes value while staying within limits.

Algorithm:
    Maximize: Σ(PageRank × relevance × diversity) / tokens_used
    Subject to: tokens_used ≤ budget

Key features:
- Greedy/knapsack selector with diversity penalty
- Token estimation using character-based approximation (or tiktoken if available)
- Relevance scoring via keyword matching
- Cluster-based diversity penalty to encourage variety
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable
import re

from .manifest import ChunkEntry, FileEntry, Manifest


# Token estimation constants
# Average characters per token (GPT-3/4 models average ~4 chars/token)
CHARS_PER_TOKEN = 4.0

# Minimum tokens to consider a chunk valuable
MIN_CHUNK_TOKENS = 10

# Default diversity penalty factor (0 = no penalty, 1 = full penalty)
DEFAULT_DIVERSITY_PENALTY = 0.3


@dataclass
class ScoredChunk:
    """A chunk with its optimization scores."""
    
    chunk: ChunkEntry
    file_path: str
    file_entry: FileEntry
    tokens: int
    pagerank: float
    relevance: float
    base_score: float
    adjusted_score: float  # After diversity penalty
    efficiency: float  # adjusted_score / tokens
    
    @property
    def id(self) -> str:
        return self.chunk.id


@dataclass
class OptimizationResult:
    """Result of token budget optimization."""
    
    selected_chunks: list[ScoredChunk] = field(default_factory=list)
    total_tokens: int = 0
    budget: int = 0
    budget_utilization: float = 0.0
    total_score: float = 0.0
    average_efficiency: float = 0.0
    
    # Metadata
    considered_chunks: int = 0
    filtered_chunks: int = 0
    diversity_penalty_applied: bool = False
    
    def to_dict(self) -> dict[str, Any]:
        """Convert to JSON-serializable dict."""
        return {
            'selected_chunks': [
                {
                    'chunk_id': sc.id,
                    'file_path': sc.file_path,
                    'name': sc.chunk.name,
                    'type': sc.chunk.type,
                    'tokens': sc.tokens,
                    'pagerank': sc.pagerank,
                    'relevance': sc.relevance,
                    'score': sc.adjusted_score,
                    'efficiency': sc.efficiency,
                    'lines': f"{sc.chunk.start_line}-{sc.chunk.end_line}",
                }
                for sc in self.selected_chunks
            ],
            'summary': {
                'total_tokens': self.total_tokens,
                'budget': self.budget,
                'budget_utilization': round(self.budget_utilization, 2),
                'total_score': round(self.total_score, 4),
                'chunks_selected': len(self.selected_chunks),
                'chunks_considered': self.considered_chunks,
                'average_efficiency': round(self.average_efficiency, 4),
            }
        }


def estimate_tokens(text: str) -> int:
    """Estimate token count for a piece of text.
    
    Uses a character-based approximation. For more accurate results,
    tiktoken can be used if available.
    
    Args:
        text: Text to estimate tokens for
        
    Returns:
        Estimated token count
    """
    # Try tiktoken if available (for accurate GPT token counting)
    try:
        import tiktoken
        enc = tiktoken.get_encoding("cl100k_base")  # GPT-4 encoding
        return len(enc.encode(text))
    except ImportError:
        pass
    
    # Fallback: character-based estimation
    # Account for whitespace compression and special characters
    char_count = len(text)
    return max(1, int(char_count / CHARS_PER_TOKEN))


def estimate_chunk_tokens(chunk: ChunkEntry, source_lines: list[str] | None = None) -> int:
    """Estimate tokens for a code chunk.
    
    Args:
        chunk: The chunk to estimate
        source_lines: Optional source lines for accurate counting
        
    Returns:
        Estimated token count
    """
    if source_lines:
        # Extract actual chunk content
        start_idx = chunk.start_line - 1
        end_idx = chunk.end_line
        chunk_lines = source_lines[start_idx:end_idx]
        content = '\n'.join(chunk_lines)
        return estimate_tokens(content)
    
    # Fallback: estimate from metadata
    line_count = chunk.end_line - chunk.start_line + 1
    # Assume average 50 characters per line of code
    estimated_chars = line_count * 50
    return max(MIN_CHUNK_TOKENS, int(estimated_chars / CHARS_PER_TOKEN))


def calculate_relevance(
    chunk: ChunkEntry,
    keywords: list[str] | None = None,
    task_description: str | None = None,
) -> float:
    """Calculate relevance score for a chunk based on keywords/task.
    
    Args:
        chunk: The chunk to score
        keywords: Optional list of keywords to match
        task_description: Optional task description for semantic matching
        
    Returns:
        Relevance score between 0 and 1
    """
    if not keywords and not task_description:
        return 1.0  # No filtering, all chunks equally relevant
    
    # Build searchable text from chunk
    search_text = f"{chunk.name} {chunk.type} {chunk.docstring or ''}"
    search_text = search_text.lower()
    
    # Keyword matching
    if keywords:
        keyword_matches = sum(1 for kw in keywords if kw.lower() in search_text)
        keyword_score = keyword_matches / len(keywords) if keywords else 0
    else:
        keyword_score = 0
    
    # Task description matching (simple token overlap)
    if task_description:
        task_tokens = set(re.findall(r'\w+', task_description.lower()))
        chunk_tokens = set(re.findall(r'\w+', search_text))
        overlap = len(task_tokens & chunk_tokens)
        task_score = overlap / len(task_tokens) if task_tokens else 0
    else:
        task_score = 0
    
    # Combine scores
    if keywords and task_description:
        return (keyword_score + task_score) / 2
    elif keywords:
        return keyword_score
    else:
        return task_score


def calculate_diversity_penalty(
    chunk: ScoredChunk,
    selected: list[ScoredChunk],
    penalty_factor: float = DEFAULT_DIVERSITY_PENALTY,
) -> float:
    """Calculate diversity penalty based on already-selected chunks.
    
    Penalizes selecting chunks from the same file or with similar names.
    
    Args:
        chunk: Candidate chunk
        selected: Already selected chunks
        penalty_factor: How much to penalize (0 = none, 1 = full)
        
    Returns:
        Penalty multiplier (1.0 = no penalty, lower = more penalty)
    """
    if not selected or penalty_factor == 0:
        return 1.0
    
    # Count chunks from same file
    same_file_count = sum(1 for s in selected if s.file_path == chunk.file_path)
    
    # Count chunks with similar names (same prefix)
    chunk_prefix = chunk.chunk.name[:3].lower() if len(chunk.chunk.name) >= 3 else chunk.chunk.name.lower()
    similar_name_count = sum(
        1 for s in selected 
        if s.chunk.name.lower().startswith(chunk_prefix) or chunk.chunk.name.lower().startswith(s.chunk.name[:3].lower())
    )
    
    # Count chunks of same type
    same_type_count = sum(1 for s in selected if s.chunk.type == chunk.chunk.type)
    
    # Calculate penalty (diminishing returns for same file/type/name)
    file_penalty = 1.0 / (1 + same_file_count * 0.5)
    name_penalty = 1.0 / (1 + similar_name_count * 0.3)
    type_penalty = 1.0 / (1 + same_type_count * 0.1)
    
    # Combine penalties
    raw_penalty = file_penalty * name_penalty * type_penalty
    
    # Apply penalty factor to control strength
    return 1.0 - penalty_factor * (1.0 - raw_penalty)


def prepare_chunks(
    manifest: Manifest,
    centrality: dict[str, float],
    keywords: list[str] | None = None,
    task_description: str | None = None,
    source_cache: dict[str, list[str]] | None = None,
    min_pagerank: float = 0.0,
) -> list[ScoredChunk]:
    """Prepare all chunks with their optimization scores.
    
    Args:
        manifest: The analysis manifest
        centrality: PageRank scores by file path
        keywords: Optional relevance keywords
        task_description: Optional task description
        source_cache: Optional cache of source lines by file path
        min_pagerank: Minimum PageRank to include (filter low-importance)
        
    Returns:
        List of ScoredChunk objects sorted by base efficiency
    """
    scored_chunks: list[ScoredChunk] = []
    
    for file_entry in manifest.files:
        file_path = file_entry.path
        pagerank = centrality.get(file_path, 0.0)
        
        # Skip low-importance files
        if pagerank < min_pagerank:
            continue
        
        # Get source lines if available
        source_lines = source_cache.get(file_path) if source_cache else None
        
        for chunk in file_entry.chunks:
            # Estimate tokens
            tokens = estimate_chunk_tokens(chunk, source_lines)
            
            if tokens < MIN_CHUNK_TOKENS:
                continue
            
            # Calculate relevance
            relevance = calculate_relevance(chunk, keywords, task_description)
            
            # Base score: PageRank × relevance
            # Boost exported/public symbols slightly
            export_boost = 1.2 if chunk.exported else 1.0
            base_score = pagerank * relevance * export_boost
            
            # Initial efficiency (before diversity penalty)
            efficiency = base_score / tokens if tokens > 0 else 0
            
            scored_chunks.append(ScoredChunk(
                chunk=chunk,
                file_path=file_path,
                file_entry=file_entry,
                tokens=tokens,
                pagerank=pagerank,
                relevance=relevance,
                base_score=base_score,
                adjusted_score=base_score,  # Updated during selection
                efficiency=efficiency,
            ))
    
    # Sort by base efficiency (highest first)
    scored_chunks.sort(key=lambda c: c.efficiency, reverse=True)
    
    return scored_chunks


def optimize_context_greedy(
    manifest: Manifest,
    centrality: dict[str, float],
    budget: int,
    keywords: list[str] | None = None,
    task_description: str | None = None,
    diversity_penalty: float = DEFAULT_DIVERSITY_PENALTY,
    source_cache: dict[str, list[str]] | None = None,
    min_relevance: float = 0.0,
) -> OptimizationResult:
    """Select optimal chunks within token budget using greedy algorithm.
    
    Greedy approach: repeatedly select the chunk with highest efficiency
    (score/tokens) that fits in remaining budget, applying diversity penalty.
    
    Args:
        manifest: The analysis manifest
        centrality: PageRank scores by file path
        budget: Token budget
        keywords: Optional relevance keywords
        task_description: Optional task description
        diversity_penalty: Diversity penalty factor (0-1)
        source_cache: Optional source lines cache
        min_relevance: Minimum relevance score to include
        
    Returns:
        OptimizationResult with selected chunks
    """
    # Prepare all chunks
    candidates = prepare_chunks(
        manifest, centrality, keywords, task_description, source_cache
    )
    
    considered = len(candidates)
    
    # Filter by minimum relevance
    if min_relevance > 0:
        candidates = [c for c in candidates if c.relevance >= min_relevance]
    
    filtered = considered - len(candidates)
    
    # Greedy selection
    selected: list[ScoredChunk] = []
    remaining_budget = budget
    
    while candidates and remaining_budget > 0:
        # Update adjusted scores with diversity penalty
        for candidate in candidates:
            penalty = calculate_diversity_penalty(candidate, selected, diversity_penalty)
            candidate.adjusted_score = candidate.base_score * penalty
            candidate.efficiency = candidate.adjusted_score / candidate.tokens if candidate.tokens > 0 else 0
        
        # Sort by current efficiency
        candidates.sort(key=lambda c: c.efficiency, reverse=True)
        
        # Find best chunk that fits
        best_idx = None
        for i, candidate in enumerate(candidates):
            if candidate.tokens <= remaining_budget:
                best_idx = i
                break
        
        if best_idx is None:
            # No more chunks fit
            break
        
        # Select this chunk
        best = candidates.pop(best_idx)
        selected.append(best)
        remaining_budget -= best.tokens
    
    # Calculate totals
    total_tokens = sum(c.tokens for c in selected)
    total_score = sum(c.adjusted_score for c in selected)
    avg_efficiency = total_score / total_tokens if total_tokens > 0 else 0
    
    return OptimizationResult(
        selected_chunks=selected,
        total_tokens=total_tokens,
        budget=budget,
        budget_utilization=total_tokens / budget if budget > 0 else 0,
        total_score=total_score,
        average_efficiency=avg_efficiency,
        considered_chunks=considered,
        filtered_chunks=filtered,
        diversity_penalty_applied=diversity_penalty > 0,
    )


def optimize_context_knapsack(
    manifest: Manifest,
    centrality: dict[str, float],
    budget: int,
    keywords: list[str] | None = None,
    task_description: str | None = None,
    source_cache: dict[str, list[str]] | None = None,
    max_chunks: int = 100,
) -> OptimizationResult:
    """Select optimal chunks using 0/1 knapsack dynamic programming.
    
    True optimal solution but O(n * budget) complexity.
    Use for smaller budgets or when optimality matters more than speed.
    
    Note: This ignores diversity penalty for true optimality.
    Use greedy with diversity_penalty > 0 for diverse selections.
    
    Args:
        manifest: The analysis manifest
        centrality: PageRank scores by file path
        budget: Token budget
        keywords: Optional relevance keywords
        task_description: Optional task description
        source_cache: Optional source lines cache
        max_chunks: Maximum chunks to consider (for performance)
        
    Returns:
        OptimizationResult with optimally selected chunks
    """
    # Prepare chunks
    candidates = prepare_chunks(
        manifest, centrality, keywords, task_description, source_cache
    )
    
    considered = len(candidates)
    
    # Limit for performance
    if len(candidates) > max_chunks:
        candidates = candidates[:max_chunks]
    
    n = len(candidates)
    
    if n == 0:
        return OptimizationResult(budget=budget, considered_chunks=considered)
    
    # DP table: dp[i][w] = max value achievable with first i items and capacity w
    # For memory efficiency, use 1D rolling array
    # Scale budget down for performance (round to nearest 10)
    scale_factor = 10
    scaled_budget = budget // scale_factor + 1
    
    # Scale chunk tokens
    for c in candidates:
        c.tokens = max(1, c.tokens // scale_factor)
    
    # DP array
    dp = [0.0] * (scaled_budget + 1)
    keep = [[False] * (scaled_budget + 1) for _ in range(n)]
    
    for i, chunk in enumerate(candidates):
        tokens = chunk.tokens
        value = chunk.base_score * 1000  # Scale up for precision
        
        # Iterate backwards to avoid using same item twice
        for w in range(scaled_budget, tokens - 1, -1):
            if dp[w - tokens] + value > dp[w]:
                dp[w] = dp[w - tokens] + value
                keep[i][w] = True
    
    # Backtrack to find selected items
    selected: list[ScoredChunk] = []
    w = scaled_budget
    
    for i in range(n - 1, -1, -1):
        if keep[i][w]:
            chunk = candidates[i]
            # Restore original token count
            chunk.tokens *= scale_factor
            selected.append(chunk)
            w -= chunk.tokens // scale_factor
    
    selected.reverse()
    
    # Calculate totals
    total_tokens = sum(c.tokens for c in selected)
    total_score = sum(c.base_score for c in selected)
    avg_efficiency = total_score / total_tokens if total_tokens > 0 else 0
    
    return OptimizationResult(
        selected_chunks=selected,
        total_tokens=total_tokens,
        budget=budget,
        budget_utilization=total_tokens / budget if budget > 0 else 0,
        total_score=total_score,
        average_efficiency=avg_efficiency,
        considered_chunks=considered,
        filtered_chunks=0,
        diversity_penalty_applied=False,
    )


def optimize_context(
    manifest: Manifest,
    centrality: dict[str, float],
    budget: int,
    keywords: list[str] | None = None,
    task_description: str | None = None,
    algorithm: str = "greedy",
    diversity_penalty: float = DEFAULT_DIVERSITY_PENALTY,
    source_cache: dict[str, list[str]] | None = None,
) -> OptimizationResult:
    """Main entry point for context optimization.
    
    Selects the optimal subset of code chunks that maximizes value
    within the given token budget.
    
    Args:
        manifest: The analysis manifest containing all chunks
        centrality: PageRank scores by file path
        budget: Maximum tokens to include
        keywords: Optional keywords to boost relevance
        task_description: Optional task description for relevance
        algorithm: "greedy" (default, fast, diversity-aware) or "knapsack" (optimal)
        diversity_penalty: Penalty for selecting similar chunks (0-1)
        source_cache: Optional dict mapping file paths to source lines
        
    Returns:
        OptimizationResult with selected chunks and metadata
        
    Example:
        >>> from better_context.manifest import load_manifest
        >>> from better_context.centrality import calculate_pagerank
        >>> manifest = load_manifest("manifest.json")
        >>> # Assume graph is built
        >>> scores = calculate_pagerank(graph)
        >>> result = optimize_context(manifest, scores, budget=8000)
        >>> print(f"Selected {len(result.selected_chunks)} chunks")
    """
    if algorithm == "knapsack":
        return optimize_context_knapsack(
            manifest=manifest,
            centrality=centrality,
            budget=budget,
            keywords=keywords,
            task_description=task_description,
            source_cache=source_cache,
        )
    else:  # greedy (default)
        return optimize_context_greedy(
            manifest=manifest,
            centrality=centrality,
            budget=budget,
            keywords=keywords,
            task_description=task_description,
            diversity_penalty=diversity_penalty,
            source_cache=source_cache,
        )


def format_optimization_result(result: OptimizationResult) -> str:
    """Format optimization result as Markdown.
    
    Args:
        result: OptimizationResult to format
        
    Returns:
        Markdown string
    """
    lines = [
        "# Context Portfolio",
        "",
        f"**Budget:** {result.budget:,} tokens",
        f"**Used:** {result.total_tokens:,} tokens ({result.budget_utilization:.1%})",
        f"**Chunks:** {len(result.selected_chunks)} selected from {result.considered_chunks} considered",
        f"**Total Score:** {result.total_score:.4f}",
        "",
        "## Selected Chunks",
        "",
        "| File | Chunk | Type | Tokens | Score | Efficiency |",
        "|------|-------|------|--------|-------|------------|",
    ]
    
    for sc in result.selected_chunks:
        lines.append(
            f"| `{sc.file_path}` | {sc.chunk.name} | {sc.chunk.type} | "
            f"{sc.tokens} | {sc.adjusted_score:.4f} | {sc.efficiency:.6f} |"
        )
    
    return "\n".join(lines)


# Export public API
__all__ = [
    'ScoredChunk',
    'OptimizationResult',
    'estimate_tokens',
    'estimate_chunk_tokens',
    'calculate_relevance',
    'calculate_diversity_penalty',
    'prepare_chunks',
    'optimize_context_greedy',
    'optimize_context_knapsack',
    'optimize_context',
    'format_optimization_result',
    'CHARS_PER_TOKEN',
    'DEFAULT_DIVERSITY_PENALTY',
]
