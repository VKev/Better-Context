"""Focus Mode: Ego-Centric Context Generation.

Given a focal file, generate contextually relevant output centered on that file's
dependencies, dependents, and related code. Files are ranked by:
    score(f) = centrality(f) × (decay_factor ^ distance(f))

Where distance is the graph distance from the focal file.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Set, Tuple

if TYPE_CHECKING:
    from .graph import DependencyGraph
    from .manifest import Manifest


@dataclass
class FocusedFile:
    """A file in the focused context with scoring information."""
    
    path: str
    distance: int  # Graph distance from focal file (0 = focal file itself)
    direction: str  # 'focal', 'dependency', 'dependent', 'both'
    centrality: float
    score: float  # Combined score for ranking
    description: str = ""


@dataclass
class FocusedContext:
    """Result of focus mode analysis."""
    
    focal_file: str
    files: List[FocusedFile] = field(default_factory=list)
    total_files_in_neighborhood: int = 0
    max_depth_used: int = 0
    
    # Categorized views
    dependencies: List[FocusedFile] = field(default_factory=list)
    dependents: List[FocusedFile] = field(default_factory=list)
    related_tests: List[FocusedFile] = field(default_factory=list)
    shared_types: List[FocusedFile] = field(default_factory=list)


@dataclass
class FocusConfig:
    """Configuration for focus mode."""
    
    max_depth: int = 3  # Maximum graph distance to consider
    decay_factor: float = 0.8  # Score decay per hop
    include_tests: bool = True  # Include related test files
    include_types: bool = True  # Include shared type definition files
    min_score_threshold: float = 0.0001  # Minimum score to include


def compute_focus_context(
    focal_file: str,
    graph: "DependencyGraph",
    centrality: Dict[str, float],
    config: Optional[FocusConfig] = None,
) -> FocusedContext:
    """Compute focused context centered on a focal file.
    
    Uses bidirectional BFS to find all files within max_depth hops,
    then scores them by centrality × decay^distance.
    
    Args:
        focal_file: The file to center the analysis on
        graph: Dependency graph
        centrality: PageRank scores for all files
        config: Optional configuration
    
    Returns:
        FocusedContext with ranked files
    """
    config = config or FocusConfig()
    
    if focal_file not in graph.nodes:
        return FocusedContext(
            focal_file=focal_file,
            files=[],
            total_files_in_neighborhood=0,
            max_depth_used=0,
        )
    
    # BFS to find all reachable files within max_depth
    # Track both directions: dependencies (what focal imports) and dependents (what imports focal)
    distances_forward: Dict[str, int] = {}  # Files that focal depends on
    distances_backward: Dict[str, int] = {}  # Files that depend on focal
    
    # Forward BFS: dependencies (what this file imports)
    _bfs_distances(graph, focal_file, config.max_depth, 'forward', distances_forward)
    
    # Backward BFS: dependents (what imports this file)
    _bfs_distances(graph, focal_file, config.max_depth, 'backward', distances_backward)
    
    # Merge distances: use minimum distance from either direction
    all_files: Dict[str, Tuple[int, str]] = {}  # file -> (distance, direction)
    
    # Add focal file
    all_files[focal_file] = (0, 'focal')
    
    for f, dist in distances_forward.items():
        if f != focal_file:
            all_files[f] = (dist, 'dependency')
    
    for f, dist in distances_backward.items():
        if f == focal_file:
            continue
        if f in all_files:
            existing_dist, existing_dir = all_files[f]
            if dist < existing_dist:
                all_files[f] = (dist, 'dependent')
            elif dist == existing_dist:
                all_files[f] = (dist, 'both')
        else:
            all_files[f] = (dist, 'dependent')
    
    # Score and create FocusedFile objects
    focused_files: List[FocusedFile] = []
    
    for file_path, (distance, direction) in all_files.items():
        file_centrality = centrality.get(file_path, 0.001)
        score = file_centrality * (config.decay_factor ** distance)
        
        if score >= config.min_score_threshold:
            focused_files.append(FocusedFile(
                path=file_path,
                distance=distance,
                direction=direction,
                centrality=file_centrality,
                score=score,
                description=_generate_file_description(file_path, direction, distance),
            ))
    
    # Sort by score descending
    focused_files.sort(key=lambda f: f.score, reverse=True)
    
    # Categorize files
    dependencies = [f for f in focused_files if f.direction in ('dependency', 'both') and f.distance > 0]
    dependents = [f for f in focused_files if f.direction in ('dependent', 'both') and f.distance > 0]
    related_tests = [f for f in focused_files if _is_test_file(f.path)]
    shared_types = [f for f in focused_files if _is_type_file(f.path)]
    
    max_depth_used = max((f.distance for f in focused_files), default=0)
    
    return FocusedContext(
        focal_file=focal_file,
        files=focused_files,
        total_files_in_neighborhood=len(all_files),
        max_depth_used=max_depth_used,
        dependencies=dependencies,
        dependents=dependents,
        related_tests=related_tests if config.include_tests else [],
        shared_types=shared_types if config.include_types else [],
    )


def _bfs_distances(
    graph: "DependencyGraph",
    start: str,
    max_depth: int,
    direction: str,
    distances: Dict[str, int],
) -> None:
    """BFS to compute distances from start node.
    
    Args:
        graph: Dependency graph
        start: Starting node
        max_depth: Maximum distance to explore
        direction: 'forward' (dependencies) or 'backward' (dependents)
        distances: Output dict to populate with distances
    """
    queue: deque[Tuple[str, int]] = deque([(start, 0)])
    visited: Set[str] = set()
    
    while queue:
        node, dist = queue.popleft()
        
        if node in visited:
            continue
        visited.add(node)
        distances[node] = dist
        
        if dist >= max_depth:
            continue
        
        # Get neighbors based on direction
        if direction == 'forward':
            neighbors = graph.get_dependencies(node)
        else:
            neighbors = graph.get_dependents(node)
        
        for neighbor in neighbors:
            if neighbor not in visited:
                queue.append((neighbor, dist + 1))


def _generate_file_description(path: str, direction: str, distance: int) -> str:
    """Generate a human-readable description for a focused file."""
    if distance == 0:
        return "focal file"
    
    direction_desc = {
        'dependency': 'imported by focal',
        'dependent': 'imports focal',
        'both': 'bidirectional relationship',
    }.get(direction, direction)
    
    hop_word = 'hop' if distance == 1 else 'hops'
    return f"{direction_desc} ({distance} {hop_word})"


def _is_test_file(path: str) -> bool:
    """Check if a file is likely a test file."""
    path_lower = path.lower()
    name = Path(path).stem.lower()
    
    # Check for common test file patterns
    return (
        name.startswith('test_') or
        name.endswith('_test') or
        (name.startswith('test') and len(name) > 4 and not name[4].isalpha()) or
        'tests/' in path_lower or
        '/test/' in path_lower or
        path_lower.endswith('_test.py') or
        path_lower.endswith('_test.ts') or
        path_lower.endswith('_test.go') or
        path_lower.endswith('.test.ts') or
        path_lower.endswith('.test.js') or
        path_lower.endswith('.spec.ts') or
        path_lower.endswith('.spec.js')
    )


def _is_type_file(path: str) -> bool:
    """Check if a file is likely a type definition file."""
    path_lower = path.lower()
    name = Path(path).stem.lower()
    return (
        'types' in path_lower or
        'interfaces' in path_lower or
        name in ('types', 'interfaces', 'models', 'schemas') or
        path_lower.endswith('.d.ts') or
        path_lower.endswith('.pyi')
    )


def generate_focus_markdown(
    context: FocusedContext,
    manifest: Optional["Manifest"] = None,
    include_chunks: bool = False,
) -> str:
    """Generate a focused AGENTS.md for the context.
    
    Args:
        context: FocusedContext from compute_focus_context
        manifest: Optional manifest for additional file details
        include_chunks: Whether to include code chunk details
    
    Returns:
        Markdown string for the focused context
    """
    lines: List[str] = []
    
    # Header
    focal_name = Path(context.focal_file).name
    lines.append(f"# Focus: {focal_name}")
    lines.append("")
    lines.append(f"> Ego-centric context for `{context.focal_file}`")
    lines.append("")
    
    # Summary
    lines.append("## 📋 Summary")
    lines.append("")
    lines.append(f"- **Focal file**: `{context.focal_file}`")
    lines.append(f"- **Neighborhood size**: {context.total_files_in_neighborhood} files")
    lines.append(f"- **Max depth explored**: {context.max_depth_used} hops")
    lines.append(f"- **Direct dependencies**: {len([f for f in context.dependencies if f.distance == 1])}")
    lines.append(f"- **Direct dependents**: {len([f for f in context.dependents if f.distance == 1])}")
    lines.append("")
    
    # The focal file itself
    focal = next((f for f in context.files if f.distance == 0), None)
    if focal:
        lines.append("## 🎯 Focal File")
        lines.append("")
        lines.append(f"| File | Centrality | Description |")
        lines.append("|------|------------|-------------|")
        lines.append(f"| `{focal.path}` | {focal.centrality:.4f} | The file you're editing |")
        lines.append("")
    
    # Direct dependencies (distance = 1, forward)
    direct_deps = [f for f in context.dependencies if f.distance == 1]
    if direct_deps:
        lines.append("## ⬇️ Direct Dependencies")
        lines.append("")
        lines.append("Files that the focal file imports:")
        lines.append("")
        lines.append("| File | Centrality | Score |")
        lines.append("|------|------------|-------|")
        for f in sorted(direct_deps, key=lambda x: x.score, reverse=True):
            lines.append(f"| `{f.path}` | {f.centrality:.4f} | {f.score:.4f} |")
        lines.append("")
    
    # Direct dependents (distance = 1, backward)
    direct_dependents = [f for f in context.dependents if f.distance == 1]
    if direct_dependents:
        lines.append("## ⬆️ Direct Dependents")
        lines.append("")
        lines.append("Files that import the focal file:")
        lines.append("")
        lines.append("| File | Centrality | Score |")
        lines.append("|------|------------|-------|")
        for f in sorted(direct_dependents, key=lambda x: x.score, reverse=True):
            lines.append(f"| `{f.path}` | {f.centrality:.4f} | {f.score:.4f} |")
        lines.append("")
    
    # Extended neighborhood (distance > 1)
    extended = [f for f in context.files if f.distance > 1]
    if extended:
        lines.append("## 🔗 Extended Neighborhood")
        lines.append("")
        lines.append("Files within 2+ hops, ranked by relevance score:")
        lines.append("")
        lines.append("| File | Distance | Direction | Score |")
        lines.append("|------|----------|-----------|-------|")
        for f in sorted(extended, key=lambda x: x.score, reverse=True)[:15]:
            dir_symbol = {
                'dependency': '⬇️',
                'dependent': '⬆️',
                'both': '↔️',
            }.get(f.direction, '•')
            lines.append(f"| `{f.path}` | {f.distance} | {dir_symbol} | {f.score:.4f} |")
        lines.append("")
    
    # Related tests
    if context.related_tests:
        lines.append("## 🧪 Related Tests")
        lines.append("")
        lines.append("| Test File | Distance | Score |")
        lines.append("|-----------|----------|-------|")
        for f in sorted(context.related_tests, key=lambda x: x.score, reverse=True)[:10]:
            lines.append(f"| `{f.path}` | {f.distance} | {f.score:.4f} |")
        lines.append("")
    
    # Shared types
    if context.shared_types:
        lines.append("## 📐 Shared Types")
        lines.append("")
        lines.append("Type definition files in the neighborhood:")
        lines.append("")
        lines.append("| Type File | Distance | Score |")
        lines.append("|-----------|----------|-------|")
        for f in sorted(context.shared_types, key=lambda x: x.score, reverse=True)[:10]:
            lines.append(f"| `{f.path}` | {f.distance} | {f.score:.4f} |")
        lines.append("")
    
    # Reading order suggestion
    lines.append("## 📚 Suggested Reading Order")
    lines.append("")
    lines.append("To understand this file, read in this order:")
    lines.append("")
    
    # Start with direct dependencies (what the file uses), then the focal file, then dependents
    reading_order: List[str] = []
    for f in sorted(direct_deps, key=lambda x: x.score, reverse=True)[:5]:
        reading_order.append(f"1. `{f.path}` - {f.description}")
    reading_order.append(f"1. `{context.focal_file}` - **focal file**")
    for f in sorted(direct_dependents, key=lambda x: x.score, reverse=True)[:3]:
        reading_order.append(f"1. `{f.path}` - {f.description}")
    
    for item in reading_order:
        lines.append(item)
    lines.append("")
    
    return '\n'.join(lines)


def select_within_budget(
    files: List[FocusedFile],
    manifest: "Manifest",
    token_budget: int,
    tokens_per_line: float = 4.0,
) -> List[FocusedFile]:
    """Select files that fit within a token budget.
    
    Greedy selection: pick highest-scored files until budget exhausted.
    
    Args:
        files: Scored files from compute_focus_context
        manifest: Manifest with file size information
        token_budget: Maximum tokens to include
        tokens_per_line: Estimated tokens per line of code
    
    Returns:
        Subset of files that fit within budget
    """
    # Build path -> size mapping from manifest
    size_map: Dict[str, int] = {}
    for f in manifest.files:
        size_map[f.path] = f.size_bytes
    
    selected: List[FocusedFile] = []
    used_tokens = 0
    
    for f in files:
        # Estimate tokens for this file
        size_bytes = size_map.get(f.path, 1000)
        # Rough estimate: ~50 bytes per line, tokens_per_line tokens per line
        estimated_lines = size_bytes / 50
        estimated_tokens = int(estimated_lines * tokens_per_line)
        
        if used_tokens + estimated_tokens <= token_budget:
            selected.append(f)
            used_tokens += estimated_tokens
    
    return selected


__all__ = [
    'FocusedFile',
    'FocusedContext',
    'FocusConfig',
    'compute_focus_context',
    'generate_focus_markdown',
    'select_within_budget',
]
