"""PageRank centrality scoring for file importance ranking.

This module implements the PageRank algorithm to rank files by their
structural importance in the dependency graph.

Key insight:
- A file is important if many files import it (direct importance)
- A file is MORE important if important files import it (transitive importance)

PageRank captures both by propagating importance through the graph.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .graph import DependencyGraph


def calculate_pagerank(
    graph: "DependencyGraph",
    damping: float = 0.85,
    iterations: int = 20,
    tolerance: float = 1e-6,
) -> dict[str, float]:
    """Calculate PageRank scores for all nodes in the graph.
    
    The PageRank algorithm assigns importance scores to nodes based on
    the structure of incoming links. Files that are imported by many
    important files rank higher.
    
    Formula:
        PR(f) = (1-d)/N + d × Σ PR(g)/L(g) for all g linking to f
    
    We use the REVERSE graph semantics: edges point FROM importers TO imported.
    This way, files that are imported by many get high scores.
    
    Args:
        graph: DependencyGraph to analyze
        damping: Damping factor (probability of following a link vs random jump).
                 Default 0.85 is standard. Higher = more weight to link structure.
        iterations: Maximum iterations to run. Convergence usually by 15-20.
        tolerance: Early stop if score changes are below this threshold.
    
    Returns:
        Dictionary mapping file paths to PageRank scores (normalized to sum to 1.0)
    
    Example:
        >>> graph = build_graph_from_edges([("a.py", "utils.py"), ("b.py", "utils.py")])
        >>> scores = calculate_pagerank(graph)
        >>> scores["utils.py"] > scores["a.py"]  # utils.py is more important
        True
    """
    nodes = list(graph.nodes)
    n = len(nodes)
    
    if n == 0:
        return {}
    
    if n == 1:
        return {nodes[0]: 1.0}
    
    # Initialize scores uniformly
    scores: dict[str, float] = {node: 1.0 / n for node in nodes}
    
    for iteration in range(iterations):
        new_scores: dict[str, float] = {}
        
        # Calculate sum from dangling nodes (nodes with no outgoing edges)
        # These would "leak" PageRank, so we redistribute it
        dangling_sum = sum(
            scores[node] 
            for node in nodes 
            if graph.out_degree(node) == 0
        )
        dangling_contribution = dangling_sum / n
        
        delta = 0.0
        
        for node in nodes:
            # Base score from random jumps + dangling redistribution
            rank = (1 - damping) / n + damping * dangling_contribution
            
            # Add contributions from all nodes that import this one
            # (nodes that have edges TO this node in the reverse graph)
            incoming = graph.reverse_edges.get(node, set())
            
            for source in incoming:
                out_degree = graph.out_degree(source)
                if out_degree > 0:
                    rank += damping * scores[source] / out_degree
            
            new_scores[node] = rank
            delta += abs(rank - scores[node])
        
        scores = new_scores
        
        # Early termination if converged
        if delta < tolerance:
            break
    
    # Normalize scores to sum to 1.0
    total = sum(scores.values())
    if total > 0:
        scores = {k: v / total for k, v in scores.items()}
    
    return scores


def get_top_files(
    scores: dict[str, float],
    limit: int = 10,
) -> list[tuple[str, float]]:
    """Get the top-ranked files by PageRank score.
    
    Args:
        scores: PageRank scores from calculate_pagerank
        limit: Maximum number of results to return
    
    Returns:
        List of (file_path, score) tuples, sorted by score descending
    """
    sorted_scores = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    return sorted_scores[:limit]


def get_score_percentile(
    scores: dict[str, float],
    file_path: str,
) -> float:
    """Get the percentile rank of a file (0-100).
    
    Args:
        scores: PageRank scores
        file_path: Path to check
    
    Returns:
        Percentile (0-100) where 100 is the most important file
    """
    if file_path not in scores:
        return 0.0
    
    file_score = scores[file_path]
    lower_count = sum(1 for s in scores.values() if s < file_score)
    return (lower_count / len(scores)) * 100


def format_score(score: float, precision: int = 4) -> str:
    """Format a PageRank score for display.
    
    Args:
        score: Raw PageRank score
        precision: Decimal places
    
    Returns:
        Formatted string
    """
    return f"{score:.{precision}f}"


def describe_importance(score: float, total_files: int) -> str:
    """Generate a human-readable importance description.
    
    Args:
        score: PageRank score
        total_files: Total number of files in the graph
    
    Returns:
        Description string like "High (top 5%)" or "Low (bottom 20%)"
    """
    if total_files == 0:
        return "Unknown"
    
    # Uniform distribution would give each file 1/n
    uniform = 1.0 / total_files
    ratio = score / uniform if uniform > 0 else 0
    
    if ratio > 5:
        return "Very High (critical hub)"
    elif ratio > 2:
        return "High (key file)"
    elif ratio > 1:
        return "Above Average"
    elif ratio > 0.5:
        return "Average"
    elif ratio > 0.2:
        return "Below Average"
    else:
        return "Low (leaf file)"


def calculate_pagerank_with_stats(
    graph: "DependencyGraph",
    damping: float = 0.85,
    iterations: int = 20,
) -> dict:
    """Calculate PageRank with additional statistics.
    
    Args:
        graph: DependencyGraph to analyze
        damping: Damping factor
        iterations: Maximum iterations
    
    Returns:
        Dictionary containing:
        - scores: dict of file -> PageRank score
        - top_10: list of (file, score) for top 10 files
        - stats: summary statistics
    """
    scores = calculate_pagerank(graph, damping, iterations)
    
    if not scores:
        return {
            'scores': {},
            'top_10': [],
            'stats': {
                'total_files': 0,
                'max_score': 0,
                'min_score': 0,
                'mean_score': 0,
                'median_score': 0,
            }
        }
    
    sorted_scores = sorted(scores.values())
    n = len(sorted_scores)
    
    return {
        'scores': scores,
        'top_10': get_top_files(scores, 10),
        'stats': {
            'total_files': n,
            'max_score': sorted_scores[-1],
            'min_score': sorted_scores[0],
            'mean_score': sum(sorted_scores) / n,
            'median_score': sorted_scores[n // 2],
            'iterations_used': iterations,
            'damping': damping,
        }
    }


# Tarjan's algorithm for cycle detection
def find_strongly_connected_components(
    graph: "DependencyGraph",
) -> list[list[str]]:
    """Find strongly connected components using Tarjan's algorithm.
    
    A strongly connected component (SCC) is a maximal set of nodes where
    every node is reachable from every other node. SCCs with more than
    one node indicate circular dependencies.
    
    Complexity: O(V + E)
    
    Args:
        graph: DependencyGraph to analyze
    
    Returns:
        List of SCCs, where each SCC is a list of file paths.
        SCCs with len > 1 indicate cycles.
    """
    index_counter = [0]
    stack: list[str] = []
    lowlinks: dict[str, int] = {}
    index: dict[str, int] = {}
    on_stack: dict[str, bool] = {}
    sccs: list[list[str]] = []
    
    def strongconnect(node: str) -> None:
        # Set the depth index for this node
        index[node] = index_counter[0]
        lowlinks[node] = index_counter[0]
        index_counter[0] += 1
        stack.append(node)
        on_stack[node] = True
        
        # Consider successors
        for successor in graph.edges.get(node, set()):
            if successor not in index:
                # Successor not yet visited
                strongconnect(successor)
                lowlinks[node] = min(lowlinks[node], lowlinks[successor])
            elif on_stack.get(successor, False):
                # Successor is on stack, so it's in the current SCC
                lowlinks[node] = min(lowlinks[node], index[successor])
        
        # If node is a root node, pop the stack and generate an SCC
        if lowlinks[node] == index[node]:
            scc: list[str] = []
            while True:
                successor = stack.pop()
                on_stack[successor] = False
                scc.append(successor)
                if successor == node:
                    break
            sccs.append(scc)
    
    # Run for all nodes (handles disconnected components)
    for node in graph.nodes:
        if node not in index:
            strongconnect(node)
    
    return sccs


def find_cycles(graph: "DependencyGraph") -> list[list[str]]:
    """Find circular dependencies in the graph.
    
    Returns only SCCs with more than one node (actual cycles).
    
    Args:
        graph: DependencyGraph to analyze
    
    Returns:
        List of cycles, where each cycle is a list of file paths.
        Empty list if no cycles exist.
    """
    sccs = find_strongly_connected_components(graph)
    return [scc for scc in sccs if len(scc) > 1]


def build_topological_layers(
    graph: "DependencyGraph",
) -> list[list[str]]:
    """Build topological layers using Kahn's algorithm.
    
    Layer 0: Files with no imports (foundations)
    Layer N: Files whose imports are all in layers 0..N-1
    
    This enables "bottom-up" understanding of the codebase.
    
    Note: If cycles exist, some files won't be assigned to any layer.
    
    Args:
        graph: DependencyGraph to analyze
    
    Returns:
        List of layers, where each layer is a list of file paths.
    """
    # Calculate in-degrees (how many files this imports)
    in_degree = {node: graph.out_degree(node) for node in graph.nodes}
    
    # Find all nodes with no dependencies (layer 0 candidates)
    queue = [node for node in graph.nodes if in_degree[node] == 0]
    
    layers: list[list[str]] = []
    processed: set[str] = set()
    
    while queue:
        # All nodes in current queue are at the same layer
        current_layer = list(queue)
        layers.append(current_layer)
        processed.update(current_layer)
        
        # Find next layer
        next_queue: list[str] = []
        for node in current_layer:
            # For each file that imports this node
            for dependent in graph.reverse_edges.get(node, set()):
                if dependent not in processed:
                    # Check if all its dependencies are now processed
                    deps = graph.edges.get(dependent, set())
                    if all(d in processed for d in deps):
                        if dependent not in next_queue:
                            next_queue.append(dependent)
        
        queue = next_queue
    
    return layers


# ============================================================================
# BETWEENNESS CENTRALITY (Bridge File Detection)
# ============================================================================

def calculate_betweenness(
    graph: "DependencyGraph",
) -> dict[str, float]:
    """Calculate betweenness centrality using Brandes' algorithm.
    
    Betweenness centrality measures how often a node lies on the shortest
    paths between other nodes. High betweenness indicates a "bridge" file
    that connects otherwise-separate parts of the codebase.
    
    These are "change this and everything breaks" files:
    - Single points of failure
    - Coupling hotspots
    - Refactoring targets
    
    Complexity: O(V × E) using Brandes' algorithm
    
    Args:
        graph: DependencyGraph to analyze
    
    Returns:
        Dictionary mapping file paths to betweenness scores (normalized)
    
    Example:
        >>> graph = build_graph_from_edges([
        ...     ("a.py", "bridge.py"), ("bridge.py", "x.py"),
        ...     ("b.py", "bridge.py"), ("bridge.py", "y.py"),
        ... ])
        >>> scores = calculate_betweenness(graph)
        >>> scores["bridge.py"] > scores["a.py"]  # bridge.py connects modules
        True
    """
    nodes = list(graph.nodes)
    n = len(nodes)
    
    if n <= 2:
        return {node: 0.0 for node in nodes}
    
    # Initialize centrality scores
    centrality: dict[str, float] = {node: 0.0 for node in nodes}
    
    for source in nodes:
        # Single-source shortest paths using BFS
        stack, predecessors, num_paths, distance = _single_source_shortest_paths(
            graph, source
        )
        
        # Accumulate dependencies (back-propagation)
        dependency: dict[str, float] = {node: 0.0 for node in nodes}
        
        while stack:
            node = stack.pop()
            
            if num_paths[node] > 0:
                coeff = (1.0 + dependency[node]) / num_paths[node]
                
                for pred in predecessors.get(node, []):
                    dependency[pred] += num_paths[pred] * coeff
            
            if node != source:
                centrality[node] += dependency[node]
    
    # Normalize by (n-1)(n-2) for directed graphs
    scale = 1.0 / ((n - 1) * (n - 2)) if n > 2 else 1.0
    centrality = {k: v * scale for k, v in centrality.items()}
    
    return centrality


def _single_source_shortest_paths(
    graph: "DependencyGraph",
    source: str,
) -> tuple[list[str], dict[str, list[str]], dict[str, int], dict[str, int]]:
    """BFS-based single-source shortest paths for Brandes' algorithm.
    
    Args:
        graph: DependencyGraph
        source: Starting node
    
    Returns:
        Tuple of (stack, predecessors, num_paths, distance)
        - stack: Nodes in order of non-decreasing distance from source
        - predecessors: For each node, list of predecessors on shortest paths
        - num_paths: Number of shortest paths from source to each node
        - distance: Distance from source to each node (-1 if unreachable)
    """
    from collections import deque
    
    stack: list[str] = []
    predecessors: dict[str, list[str]] = {node: [] for node in graph.nodes}
    num_paths: dict[str, int] = {node: 0 for node in graph.nodes}
    distance: dict[str, int] = {node: -1 for node in graph.nodes}
    
    # Initialize source
    num_paths[source] = 1
    distance[source] = 0
    
    queue: deque[str] = deque([source])
    
    while queue:
        current = queue.popleft()
        stack.append(current)
        
        # Traverse outgoing edges (files that current imports)
        for neighbor in graph.edges.get(current, set()):
            # First time visiting neighbor?
            if distance[neighbor] < 0:
                distance[neighbor] = distance[current] + 1
                queue.append(neighbor)
            
            # Is this a shortest path to neighbor?
            if distance[neighbor] == distance[current] + 1:
                num_paths[neighbor] += num_paths[current]
                predecessors[neighbor].append(current)
    
    return stack, predecessors, num_paths, distance


@dataclass
class BridgeFile:
    """Information about a bridge file (high betweenness centrality)."""
    path: str
    betweenness: float
    pagerank: float
    risk_level: str  # 'high', 'medium', 'low'
    description: str


def find_bridge_files(
    graph: "DependencyGraph",
    betweenness: dict[str, float] | None = None,
    pagerank: dict[str, float] | None = None,
    threshold: float = 0.05,
    top_n: int = 10,
) -> list[BridgeFile]:
    """Find bridge files with high betweenness but potentially low PageRank.
    
    Bridge files are critical connectors - files that many shortest paths
    pass through. They're often overlooked because they may not have many
    direct dependents (low PageRank) but are crucial for connecting modules.
    
    Args:
        graph: DependencyGraph to analyze
        betweenness: Pre-computed betweenness scores (computed if None)
        pagerank: Pre-computed PageRank scores (computed if None)
        threshold: Minimum betweenness score to consider
        top_n: Maximum number of bridge files to return
    
    Returns:
        List of BridgeFile objects, sorted by betweenness descending
    """
    # Compute centrality measures if not provided
    if betweenness is None:
        betweenness = calculate_betweenness(graph)
    
    if pagerank is None:
        pagerank = calculate_pagerank(graph)
    
    bridges: list[BridgeFile] = []
    
    for file, bc in betweenness.items():
        if bc < threshold:
            continue
        
        pr = pagerank.get(file, 0)
        
        # Determine risk level based on betweenness magnitude
        if bc > 0.2:
            risk = 'high'
        elif bc > 0.1:
            risk = 'medium'
        else:
            risk = 'low'
        
        # Generate description
        desc = _describe_bridge_file(file, bc, pr, graph)
        
        bridges.append(BridgeFile(
            path=file,
            betweenness=bc,
            pagerank=pr,
            risk_level=risk,
            description=desc,
        ))
    
    # Sort by betweenness descending
    bridges.sort(key=lambda b: b.betweenness, reverse=True)
    
    return bridges[:top_n]


def _describe_bridge_file(
    path: str,
    betweenness: float,
    pagerank: float,
    graph: "DependencyGraph",
) -> str:
    """Generate a description for a bridge file."""
    parts = []
    
    in_deg = graph.in_degree(path)
    out_deg = graph.out_degree(path)
    
    # Characterize connectivity
    if in_deg > 0 and out_deg > 0:
        parts.append(f"connects {in_deg} importers to {out_deg} dependencies")
    elif in_deg > 0:
        parts.append(f"{in_deg} importers, no dependencies")
    elif out_deg > 0:
        parts.append(f"imports {out_deg} files")
    
    # Note if it's a hidden bridge (high betweenness but low PageRank)
    if betweenness > pagerank * 2:
        parts.append("critical but under-recognized")
    
    # Detect patterns from path
    path_lower = path.lower()
    if 'index' in path_lower or '__init__' in path_lower:
        parts.append("barrel/re-export")
    if 'adapter' in path_lower or 'bridge' in path_lower:
        parts.append("explicit adapter pattern")
    if 'client' in path_lower:
        parts.append("client interface")
    
    return " - ".join(parts) if parts else "bridge file"


def get_hidden_bridges(
    graph: "DependencyGraph",
    betweenness: dict[str, float] | None = None,
    pagerank: dict[str, float] | None = None,
    ratio_threshold: float = 2.0,
) -> list[BridgeFile]:
    """Find "hidden" bridges - files with high betweenness but low PageRank.
    
    These are files that are critical for code flow but might be overlooked
    because they don't have many direct dependents. They're often the most
    important files to understand for refactoring.
    
    Args:
        graph: DependencyGraph
        betweenness: Pre-computed betweenness (computed if None)
        pagerank: Pre-computed PageRank (computed if None)
        ratio_threshold: Minimum betweenness/pagerank ratio to consider
    
    Returns:
        List of hidden bridge files
    """
    if betweenness is None:
        betweenness = calculate_betweenness(graph)
    
    if pagerank is None:
        pagerank = calculate_pagerank(graph)
    
    hidden: list[BridgeFile] = []
    
    for file, bc in betweenness.items():
        pr = pagerank.get(file, 0.001)  # Avoid division by zero
        
        # Hidden bridge: high betweenness relative to PageRank
        if bc > 0.01 and bc / pr > ratio_threshold:
            risk = 'high' if bc > 0.1 else 'medium' if bc > 0.05 else 'low'
            
            hidden.append(BridgeFile(
                path=file,
                betweenness=bc,
                pagerank=pr,
                risk_level=risk,
                description=f"hidden connector (bc/pr ratio: {bc/pr:.1f}x)",
            ))
    
    # Sort by ratio (most hidden first)
    hidden.sort(key=lambda b: b.betweenness / max(b.pagerank, 0.001), reverse=True)
    
    return hidden


def format_bridge_file_table(bridges: list[BridgeFile]) -> str:
    """Format bridge files as a Markdown table.
    
    Args:
        bridges: List of BridgeFile objects
    
    Returns:
        Markdown table string
    """
    if not bridges:
        return "No bridge files detected."
    
    lines = [
        "| File | Betweenness | PageRank | Risk | Description |",
        "|------|-------------|----------|------|-------------|",
    ]
    
    for b in bridges:
        lines.append(
            f"| `{b.path}` | {b.betweenness:.4f} | {b.pagerank:.4f} | {b.risk_level.title()} | {b.description} |"
        )
    
    return "\n".join(lines)


# Export public API
__all__ = [
    'calculate_pagerank',
    'get_top_files',
    'get_score_percentile',
    'format_score',
    'describe_importance',
    'calculate_pagerank_with_stats',
    'find_strongly_connected_components',
    'find_cycles',
    'build_topological_layers',
    # Bridge file detection (Post-MVP)
    'calculate_betweenness',
    'BridgeFile',
    'find_bridge_files',
    'get_hidden_bridges',
    'format_bridge_file_table',
]
