"""Dependency graph construction and analysis.

Builds directed graphs from import/export relationships.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Set, List, Optional, Tuple, Iterator

from .resolution import (
    RawImport, ResolvedEdge, ResolutionResult,
    build_file_index, resolve_all_imports, get_internal_edges,
)


@dataclass
class DependencyGraph:
    """A directed dependency graph."""

    nodes: set[str] = field(default_factory=set)
    edges: dict[str, set[str]] = field(default_factory=dict)
    reverse_edges: dict[str, set[str]] = field(default_factory=dict)
    
    # Track edge metadata
    edge_info: dict[Tuple[str, str], ResolvedEdge] = field(default_factory=dict)

    def add_node(self, node: str) -> None:
        """Add a node to the graph."""
        self.nodes.add(node)
        self.edges.setdefault(node, set())
        self.reverse_edges.setdefault(node, set())

    def add_edge(
        self, 
        from_file: str, 
        to_file: str,
        edge_data: Optional[ResolvedEdge] = None,
    ) -> None:
        """Add an edge from one file to another."""
        self.add_node(from_file)
        self.add_node(to_file)
        self.edges[from_file].add(to_file)
        self.reverse_edges[to_file].add(from_file)
        
        if edge_data:
            self.edge_info[(from_file, to_file)] = edge_data

    def out_degree(self, node: str) -> int:
        """Get number of outgoing edges from a node."""
        return len(self.edges.get(node, set()))

    def in_degree(self, node: str) -> int:
        """Get number of incoming edges to a node."""
        return len(self.reverse_edges.get(node, set()))
    
    def has_edge(self, from_file: str, to_file: str) -> bool:
        """Check if an edge exists."""
        return to_file in self.edges.get(from_file, set())
    
    def get_dependencies(self, node: str) -> Set[str]:
        """Get all files that a node depends on (imports)."""
        return self.edges.get(node, set()).copy()
    
    def get_dependents(self, node: str) -> Set[str]:
        """Get all files that depend on a node (importers)."""
        return self.reverse_edges.get(node, set()).copy()
    
    def get_all_edges(self) -> List[Tuple[str, str]]:
        """Get all edges as (from, to) tuples."""
        edges = []
        for from_file, to_files in self.edges.items():
            for to_file in to_files:
                edges.append((from_file, to_file))
        return edges


def build_dependency_graph(
    files: Dict[str, List[RawImport]],
    all_file_paths: List[str],
    project_root: Path,
) -> Tuple[DependencyGraph, ResolutionResult]:
    """
    Build a dependency graph from parsed import data.
    
    Args:
        files: Dict mapping file paths to their RawImport lists
        all_file_paths: All available file paths in the project
        project_root: Project root directory
    
    Returns:
        Tuple of (DependencyGraph, ResolutionResult)
    """
    # Resolve all imports
    resolution = resolve_all_imports(
        files=files,
        file_paths=all_file_paths,
        project_root=project_root,
    )
    
    # Build graph
    graph = DependencyGraph()
    
    # Add all files as nodes (even those with no imports)
    for path in all_file_paths:
        graph.add_node(path)
    
    # Add edges from resolved imports
    for edge in get_internal_edges(resolution):
        if edge.to_file:
            graph.add_edge(edge.from_file, edge.to_file, edge)
    
    return graph, resolution


def build_graph_from_edges(
    edges: List[Tuple[str, str]],
    nodes: Optional[List[str]] = None,
) -> DependencyGraph:
    """
    Build a graph from a list of edges.
    
    Useful for testing and simple cases.
    
    Args:
        edges: List of (from, to) tuples
        nodes: Optional list of all nodes (inferred from edges if not provided)
    
    Returns:
        DependencyGraph
    """
    graph = DependencyGraph()
    
    # Add explicit nodes
    if nodes:
        for node in nodes:
            graph.add_node(node)
    
    # Add edges (and implicit nodes)
    for from_file, to_file in edges:
        graph.add_edge(from_file, to_file)
    
    return graph


def get_graph_stats(graph: DependencyGraph) -> dict:
    """
    Get statistics about the dependency graph.
    
    Args:
        graph: DependencyGraph to analyze
    
    Returns:
        Dictionary with graph statistics
    """
    edge_count = sum(len(targets) for targets in graph.edges.values())
    
    in_degrees = [graph.in_degree(n) for n in graph.nodes]
    out_degrees = [graph.out_degree(n) for n in graph.nodes]
    
    return {
        'node_count': len(graph.nodes),
        'edge_count': edge_count,
        'density': edge_count / (len(graph.nodes) ** 2) if graph.nodes else 0,
        'max_in_degree': max(in_degrees) if in_degrees else 0,
        'max_out_degree': max(out_degrees) if out_degrees else 0,
        'avg_in_degree': sum(in_degrees) / len(in_degrees) if in_degrees else 0,
        'avg_out_degree': sum(out_degrees) / len(out_degrees) if out_degrees else 0,
        'leaf_nodes': sum(1 for d in out_degrees if d == 0),  # No imports
        'root_nodes': sum(1 for d in in_degrees if d == 0),   # No importers
    }


def get_most_imported(graph: DependencyGraph, limit: int = 10) -> List[Tuple[str, int]]:
    """
    Get the files with the most importers.
    
    Args:
        graph: DependencyGraph
        limit: Maximum number of results
    
    Returns:
        List of (file, in_degree) tuples, sorted by in_degree descending
    """
    scored = [(node, graph.in_degree(node)) for node in graph.nodes]
    scored.sort(key=lambda x: x[1], reverse=True)
    return scored[:limit]


def get_most_dependencies(graph: DependencyGraph, limit: int = 10) -> List[Tuple[str, int]]:
    """
    Get the files with the most imports.
    
    Args:
        graph: DependencyGraph
        limit: Maximum number of results
    
    Returns:
        List of (file, out_degree) tuples, sorted by out_degree descending
    """
    scored = [(node, graph.out_degree(node)) for node in graph.nodes]
    scored.sort(key=lambda x: x[1], reverse=True)
    return scored[:limit]


def get_isolated_nodes(graph: DependencyGraph) -> List[str]:
    """
    Get nodes with no incoming or outgoing edges.
    
    These are completely isolated files.
    """
    return [
        node for node in graph.nodes
        if graph.in_degree(node) == 0 and graph.out_degree(node) == 0
    ]


def subgraph(graph: DependencyGraph, nodes: Set[str]) -> DependencyGraph:
    """
    Extract a subgraph containing only the specified nodes.
    
    Args:
        graph: Original graph
        nodes: Nodes to include
    
    Returns:
        New DependencyGraph with only specified nodes and their internal edges
    """
    sub = DependencyGraph()
    
    for node in nodes:
        if node in graph.nodes:
            sub.add_node(node)
    
    for from_node in nodes:
        for to_node in graph.get_dependencies(from_node):
            if to_node in nodes:
                edge_data = graph.edge_info.get((from_node, to_node))
                sub.add_edge(from_node, to_node, edge_data)
    
    return sub


def transitive_closure(
    graph: DependencyGraph, 
    start_node: str, 
    direction: str = 'forward',
) -> Set[str]:
    """
    Get all nodes reachable from start_node.
    
    Args:
        graph: DependencyGraph
        start_node: Starting node
        direction: 'forward' (what it depends on) or 'backward' (what depends on it)
    
    Returns:
        Set of all reachable nodes (not including start_node)
    """
    if start_node not in graph.nodes:
        return set()
    
    visited = set()
    stack = [start_node]
    
    while stack:
        node = stack.pop()
        if node in visited:
            continue
        visited.add(node)
        
        if direction == 'forward':
            neighbors = graph.get_dependencies(node)
        else:
            neighbors = graph.get_dependents(node)
        
        for neighbor in neighbors:
            if neighbor not in visited:
                stack.append(neighbor)
    
    visited.discard(start_node)  # Don't include start node
    return visited


# ============================================================================
# TARJAN'S STRONGLY CONNECTED COMPONENTS
# ============================================================================

@dataclass
class CycleReport:
    """Report for a detected circular dependency."""
    files: List[str]                    # Files in the cycle
    edges: List[Tuple[str, str]]        # Edges forming the cycle
    suggested_break: Optional[str]      # Suggested edge to remove


def tarjan_scc(graph: DependencyGraph) -> List[List[str]]:
    """
    Tarjan's algorithm for strongly connected components.
    
    Returns list of SCCs, each SCC is a list of nodes.
    SCCs with >1 node indicate circular dependencies.
    
    Time complexity: O(V + E)
    """
    index_counter = [0]  # Mutable for closure
    stack: List[str] = []
    lowlinks: Dict[str, int] = {}
    index: Dict[str, int] = {}
    on_stack: Dict[str, bool] = {}
    sccs: List[List[str]] = []
    
    def strongconnect(node: str) -> None:
        # Set the depth index for node
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
                # Successor is on stack, part of current SCC
                lowlinks[node] = min(lowlinks[node], index[successor])
        
        # If node is a root, pop the SCC
        if lowlinks[node] == index[node]:
            scc: List[str] = []
            while True:
                w = stack.pop()
                on_stack[w] = False
                scc.append(w)
                if w == node:
                    break
            sccs.append(scc)
    
    for node in graph.nodes:
        if node not in index:
            strongconnect(node)
    
    return sccs


def tarjan_scc_iterative(graph: DependencyGraph) -> List[List[str]]:
    """
    Iterative version of Tarjan's algorithm.
    
    Uses explicit stack to avoid Python's recursion limit on large graphs.
    """
    index_counter = 0
    stack: List[str] = []
    lowlinks: Dict[str, int] = {}
    indices: Dict[str, int] = {}
    on_stack: Dict[str, bool] = {}
    sccs: List[List[str]] = []
    
    # Work stack: (node, phase, iterator)
    # phase 0: initial visit
    # phase 1: after visiting successors
    work_stack: List[Tuple[str, int, Optional[Iterator]]] = []
    
    for start_node in graph.nodes:
        if start_node in indices:
            continue
        
        work_stack.append((start_node, 0, None))
        
        while work_stack:
            node, phase, successors_iter = work_stack.pop()
            
            if phase == 0:
                # Initial visit
                indices[node] = index_counter
                lowlinks[node] = index_counter
                index_counter += 1
                stack.append(node)
                on_stack[node] = True
                
                # Push back for phase 1, then push successors for phase 0
                successors = iter(graph.edges.get(node, set()))
                work_stack.append((node, 1, successors))
            
            elif phase == 1:
                # Process successors one at a time
                try:
                    successor = next(successors_iter)
                    # Re-push current node to continue later
                    work_stack.append((node, 1, successors_iter))
                    
                    if successor not in indices:
                        # Push successor for phase 0
                        work_stack.append((successor, 0, None))
                    elif on_stack.get(successor, False):
                        lowlinks[node] = min(lowlinks[node], indices[successor])
                except StopIteration:
                    # All successors processed, check if root
                    if lowlinks[node] == indices[node]:
                        scc: List[str] = []
                        while True:
                            w = stack.pop()
                            on_stack[w] = False
                            scc.append(w)
                            if w == node:
                                break
                        sccs.append(scc)
                    
                    # Update parent's lowlink
                    if work_stack:
                        parent, parent_phase, _ = work_stack[-1]
                        if parent_phase == 1 and parent in lowlinks:
                            lowlinks[parent] = min(
                                lowlinks[parent], 
                                lowlinks.get(node, indices.get(node, 0))
                            )
    
    return sccs


def detect_cycles(graph: DependencyGraph, use_iterative: bool = False) -> List[List[str]]:
    """
    Return only the SCCs that represent cycles (size > 1).
    
    Args:
        graph: DependencyGraph to analyze
        use_iterative: Use iterative version for large graphs
    
    Returns:
        List of cycles, each cycle is a list of file paths
    """
    if use_iterative:
        sccs = tarjan_scc_iterative(graph)
    else:
        sccs = tarjan_scc(graph)
    
    return [scc for scc in sccs if len(scc) > 1]


def analyze_cycle(cycle: List[str], graph: DependencyGraph) -> CycleReport:
    """
    Analyze a cycle and suggest where to break it.
    
    The suggestion is to break the edge where the source file has
    the highest in-degree (most imported), as this is typically a
    more central file that shouldn't depend on peripheral files.
    
    Args:
        cycle: List of files in the cycle
        graph: DependencyGraph for context
    
    Returns:
        CycleReport with analysis and suggestion
    """
    # Find edges within the cycle
    cycle_set = set(cycle)
    edges: List[Tuple[str, str]] = []
    
    for file in cycle:
        for dependency in graph.get_dependencies(file):
            if dependency in cycle_set:
                edges.append((file, dependency))
    
    # Suggest breaking the edge where source has highest in-degree
    suggested_break = None
    if edges:
        best_edge = max(edges, key=lambda e: graph.in_degree(e[0]))
        suggested_break = f"{best_edge[0]} → {best_edge[1]}"
    
    return CycleReport(
        files=cycle,
        edges=edges,
        suggested_break=suggested_break,
    )


def get_all_cycle_reports(graph: DependencyGraph) -> List[CycleReport]:
    """
    Detect all cycles and return detailed reports.
    
    Args:
        graph: DependencyGraph to analyze
    
    Returns:
        List of CycleReport for each detected cycle
    """
    cycles = detect_cycles(graph)
    return [analyze_cycle(cycle, graph) for cycle in cycles]


def has_cycles(graph: DependencyGraph) -> bool:
    """Quick check if graph has any cycles."""
    return len(detect_cycles(graph)) > 0


# ============================================================================
# KAHN'S ALGORITHM FOR TOPOLOGICAL LAYERS
# ============================================================================

def _kahn_layers_internal(graph: DependencyGraph) -> List[List[str]]:
    """
    Core Kahn's algorithm producing layers (not a single ordering).
    
    Uses REVERSE edges so that layer 0 = files with no dependencies (foundations),
    and higher layers depend on lower layers.
    
    Assumes graph is a DAG (no cycles).
    """
    # Calculate out-degrees (we're processing in reverse dependency order)
    # A file with no outgoing edges = no imports = foundation
    out_degree: Dict[str, int] = {node: 0 for node in graph.nodes}
    for node, targets in graph.edges.items():
        out_degree[node] = len(targets)
    
    # Initialize with nodes that have no imports (foundations)
    current_layer = sorted([n for n in graph.nodes if out_degree[n] == 0])
    layers: List[List[str]] = []
    
    processed = set()
    
    while current_layer:
        layers.append(current_layer)
        processed.update(current_layer)
        next_layer: List[str] = []
        
        for node in current_layer:
            # Check all nodes that import this node
            for dependent in graph.reverse_edges.get(node, set()):
                if dependent in processed:
                    continue
                # Check if all dependencies of this node are processed
                deps = graph.edges.get(dependent, set())
                if all(d in processed for d in deps):
                    if dependent not in next_layer:
                        next_layer.append(dependent)
        
        current_layer = sorted(next_layer)
    
    return layers


def condense_graph(
    graph: DependencyGraph,
    sccs: List[List[str]],
) -> Tuple[DependencyGraph, Dict[str, List[str]]]:
    """
    Replace each SCC with a single representative node.
    
    Args:
        graph: Original graph with cycles
        sccs: List of SCCs (cycles) from tarjan_scc
    
    Returns:
        Tuple of (condensed DAG, mapping from representative -> original nodes)
    """
    # Map each node to its SCC representative
    node_to_rep: Dict[str, str] = {}
    scc_map: Dict[str, List[str]] = {}
    
    for scc in sccs:
        if len(scc) > 1:  # Only condense actual cycles
            rep = sorted(scc)[0]  # Use alphabetically first as representative
            scc_map[rep] = scc
            for node in scc:
                node_to_rep[node] = rep
    
    # Nodes not in any SCC are their own representative
    for node in graph.nodes:
        if node not in node_to_rep:
            node_to_rep[node] = node
    
    # Build condensed graph
    condensed = DependencyGraph()
    for node in set(node_to_rep.values()):
        condensed.add_node(node)
    
    for source, targets in graph.edges.items():
        source_rep = node_to_rep[source]
        for target in targets:
            target_rep = node_to_rep[target]
            if source_rep != target_rep:  # Skip intra-SCC edges
                condensed.add_edge(source_rep, target_rep)
    
    return condensed, scc_map


def expand_layers(
    layers: List[List[str]],
    scc_map: Dict[str, List[str]],
) -> List[List[str]]:
    """
    Expand condensed layers back to original files.
    
    SCC members are placed in the same layer as their representative.
    """
    expanded: List[List[str]] = []
    
    for layer in layers:
        expanded_layer: List[str] = []
        for node in layer:
            if node in scc_map:
                # Expand SCC to all its members
                expanded_layer.extend(sorted(scc_map[node]))
            else:
                expanded_layer.append(node)
        expanded.append(sorted(expanded_layer))
    
    return expanded


def build_topological_layers(graph: DependencyGraph) -> List[List[str]]:
    """
    Build topological layers using Kahn's algorithm.
    
    Layer 0 contains files with no imports (foundations).
    Layer N contains files that only import from layers 0..N-1.
    
    Handles cycles by condensing SCCs to single nodes.
    
    Args:
        graph: DependencyGraph to analyze
    
    Returns:
        List of layers, each layer is a sorted list of file paths
    """
    # Handle cycles by contracting SCCs
    sccs = tarjan_scc(graph)
    cycles = [scc for scc in sccs if len(scc) > 1]
    
    if cycles:
        # Create condensed graph (DAG)
        condensed, scc_map = condense_graph(graph, sccs)
        layers = _kahn_layers_internal(condensed)
        # Expand SCCs back to original files
        return expand_layers(layers, scc_map)
    
    return _kahn_layers_internal(graph)


def assign_layer_numbers(layers: List[List[str]]) -> Dict[str, int]:
    """
    Convert layer list to node -> layer number mapping.
    
    Args:
        layers: Output from build_topological_layers
    
    Returns:
        Dict mapping file path to layer number
    """
    result: Dict[str, int] = {}
    for i, layer in enumerate(layers):
        for node in layer:
            result[node] = i
    return result


def get_layer_stats(layers: List[List[str]]) -> dict:
    """
    Get statistics about topological layers.
    
    Args:
        layers: Output from build_topological_layers
    
    Returns:
        Statistics dictionary
    """
    if not layers:
        return {
            'num_layers': 0,
            'total_nodes': 0,
            'layer_sizes': [],
            'avg_layer_size': 0,
            'max_layer_size': 0,
        }
    
    layer_sizes = [len(layer) for layer in layers]
    
    return {
        'num_layers': len(layers),
        'total_nodes': sum(layer_sizes),
        'layer_sizes': layer_sizes,
        'avg_layer_size': sum(layer_sizes) / len(layer_sizes),
        'max_layer_size': max(layer_sizes),
        'foundation_count': layer_sizes[0] if layer_sizes else 0,
    }
