"""
Graph visualization export for better-context.

Exports dependency graphs in multiple formats for visualization and documentation.
"""

from __future__ import annotations

import json
import re
from typing import Dict, List, Set, Optional, Tuple

from .graph import DependencyGraph


# ============================================================================
# UTILITIES
# ============================================================================

def shorten_path(path: str, max_len: int = 30) -> str:
    """
    Shorten file path for display.
    
    Args:
        path: Full file path
        max_len: Maximum length before shortening
    
    Returns:
        Shortened path string
    """
    if len(path) <= max_len:
        return path
    
    parts = path.split('/')
    if len(parts) <= 2:
        return path
    
    # Try keeping last 2 parts
    short = '/'.join(parts[-2:])
    if len(short) <= max_len - 4:
        return f".../{short}"
    
    # Just use filename
    return f".../{parts[-1]}"


def node_id(path: str) -> str:
    """
    Convert path to valid Mermaid/DOT node ID.
    
    Replaces special characters that aren't valid in identifiers.
    """
    # Replace common special characters
    result = path.replace('/', '_')
    result = result.replace('.', '_')
    result = result.replace('-', '_')
    result = result.replace(' ', '_')
    result = result.replace('(', '_')
    result = result.replace(')', '_')
    result = result.replace('[', '_')
    result = result.replace(']', '_')
    
    # Ensure it starts with a letter or underscore
    if result and result[0].isdigit():
        result = '_' + result
    
    return result


def escape_label(text: str) -> str:
    """Escape special characters in labels."""
    return text.replace('"', '\\"').replace('\n', '\\n')


# ============================================================================
# MERMAID EXPORT
# ============================================================================

def export_mermaid(
    graph: DependencyGraph,
    centrality: Optional[Dict[str, float]] = None,
    cycles: Optional[List[List[str]]] = None,
    max_nodes: int = 50,
    direction: str = 'LR',
    show_labels: bool = True,
) -> str:
    """
    Export graph as Mermaid diagram.
    
    Features:
    - Highlight high-centrality nodes
    - Color cycle edges differently
    - Limit node count for readability
    
    Args:
        graph: DependencyGraph to export
        centrality: Optional PageRank scores for styling
        cycles: Optional list of cycles to highlight
        max_nodes: Maximum number of nodes to include
        direction: Graph direction (LR, TB, RL, BT)
        show_labels: Whether to show file names as labels
    
    Returns:
        Mermaid diagram as string
    """
    lines = [f'graph {direction}']
    
    # Select top nodes if graph is too large
    nodes = list(graph.nodes)
    if len(nodes) > max_nodes and centrality:
        nodes = sorted(nodes, key=lambda n: centrality.get(n, 0), reverse=True)[:max_nodes]
    elif len(nodes) > max_nodes:
        # Without centrality, just take first max_nodes (alphabetically)
        nodes = sorted(nodes)[:max_nodes]
    
    nodes_set = set(nodes)
    
    # Collect cycle edges for highlighting
    cycle_edges: Set[Tuple[str, str]] = set()
    if cycles:
        for cycle in cycles:
            cycle_set = set(cycle)
            for node in cycle:
                for dep in graph.edges.get(node, set()):
                    if dep in cycle_set:
                        cycle_edges.add((node, dep))
    
    # Identify high-centrality nodes
    high_centrality: Set[str] = set()
    if centrality:
        threshold = 0.05  # Top ~5% typically
        for node, score in centrality.items():
            if score > threshold:
                high_centrality.add(node)
    
    # Add nodes with styling
    for node in sorted(nodes):
        nid = node_id(node)
        label = shorten_path(node) if show_labels else nid
        
        if node in high_centrality:
            # High centrality: use special shape
            lines.append(f'    {nid}[("{label}")]')
        else:
            lines.append(f'    {nid}["{label}"]')
    
    # Add edges
    for source in sorted(nodes):
        for target in sorted(graph.edges.get(source, set())):
            if target in nodes_set:
                src_id = node_id(source)
                tgt_id = node_id(target)
                
                if (source, target) in cycle_edges:
                    # Cycle edge: dashed red
                    lines.append(f'    {src_id} -.->|cycle| {tgt_id}')
                else:
                    lines.append(f'    {src_id} --> {tgt_id}')
    
    # Add styling classes
    lines.append('')
    lines.append('    classDef highCentrality fill:#f9f,stroke:#333,stroke-width:2px')
    
    # Apply high centrality class
    if high_centrality:
        high_ids = [node_id(n) for n in high_centrality if n in nodes_set]
        if high_ids:
            lines.append(f'    class {",".join(high_ids)} highCentrality')
    
    return '\n'.join(lines)


# ============================================================================
# DOT (GRAPHVIZ) EXPORT
# ============================================================================

def export_dot(
    graph: DependencyGraph,
    centrality: Optional[Dict[str, float]] = None,
    cycles: Optional[List[List[str]]] = None,
    max_nodes: int = 100,
    rankdir: str = 'LR',
) -> str:
    """
    Export graph as Graphviz DOT format.
    
    For high-quality rendering and advanced layouts.
    
    Args:
        graph: DependencyGraph to export
        centrality: Optional PageRank scores for node sizing
        cycles: Optional list of cycles to highlight
        max_nodes: Maximum number of nodes
        rankdir: Graph direction (LR, TB, RL, BT)
    
    Returns:
        DOT format string
    """
    lines = ['digraph dependencies {']
    lines.append(f'    rankdir={rankdir};')
    lines.append('    node [shape=box, fontname="Arial"];')
    lines.append('    edge [fontname="Arial", fontsize=10];')
    lines.append('')
    
    # Select nodes
    nodes = list(graph.nodes)
    if len(nodes) > max_nodes and centrality:
        nodes = sorted(nodes, key=lambda n: centrality.get(n, 0), reverse=True)[:max_nodes]
    elif len(nodes) > max_nodes:
        nodes = sorted(nodes)[:max_nodes]
    
    nodes_set = set(nodes)
    
    # Collect cycle edges
    cycle_edges: Set[Tuple[str, str]] = set()
    if cycles:
        for cycle in cycles:
            cycle_set = set(cycle)
            for node in cycle:
                for dep in graph.edges.get(node, set()):
                    if dep in cycle_set:
                        cycle_edges.add((node, dep))
    
    # Add nodes
    for node in sorted(nodes):
        attrs = []
        label = shorten_path(node)
        attrs.append(f'label="{escape_label(label)}"')
        
        if centrality:
            score = centrality.get(node, 0)
            # Scale node width by centrality (0.5 to 2.0)
            width = 0.5 + score * 5
            attrs.append(f'width={width:.2f}')
            
            # Color by centrality
            if score > 0.1:
                attrs.append('style=filled')
                attrs.append('fillcolor="#ff9999"')
            elif score > 0.05:
                attrs.append('style=filled')
                attrs.append('fillcolor="#ffcccc"')
        
        lines.append(f'    "{node}" [{", ".join(attrs)}];')
    
    lines.append('')
    
    # Add edges
    for source in sorted(nodes):
        for target in sorted(graph.edges.get(source, set())):
            if target in nodes_set:
                if (source, target) in cycle_edges:
                    lines.append(f'    "{source}" -> "{target}" [color=red, style=dashed, label="cycle"];')
                else:
                    lines.append(f'    "{source}" -> "{target}";')
    
    lines.append('}')
    return '\n'.join(lines)


# ============================================================================
# JSON EXPORT
# ============================================================================

def export_json(
    graph: DependencyGraph,
    centrality: Optional[Dict[str, float]] = None,
    layers: Optional[List[List[str]]] = None,
    cycles: Optional[List[List[str]]] = None,
    pretty: bool = True,
) -> str:
    """
    Export graph as JSON for custom visualization.
    
    Args:
        graph: DependencyGraph to export
        centrality: Optional PageRank scores
        layers: Optional topological layers
        cycles: Optional detected cycles
        pretty: Whether to pretty-print
    
    Returns:
        JSON string
    """
    # Build layer lookup
    layer_map = {}
    if layers:
        for i, layer in enumerate(layers):
            for node in layer:
                layer_map[node] = i
    
    data = {
        'nodes': [
            {
                'id': node,
                'label': shorten_path(node),
                'centrality': centrality.get(node, 0) if centrality else None,
                'layer': layer_map.get(node),
                'in_degree': graph.in_degree(node),
                'out_degree': graph.out_degree(node),
            }
            for node in sorted(graph.nodes)
        ],
        'edges': [
            {'source': s, 'target': t}
            for s in sorted(graph.edges.keys())
            for t in sorted(graph.edges.get(s, set()))
        ],
        'stats': {
            'node_count': len(graph.nodes),
            'edge_count': len([1 for s, ts in graph.edges.items() for t in ts]),
        }
    }
    
    if cycles:
        data['cycles'] = cycles
    
    if pretty:
        return json.dumps(data, indent=2)
    return json.dumps(data)


# ============================================================================
# HIGH-LEVEL EXPORT FUNCTION
# ============================================================================

def export_graph(
    graph: DependencyGraph,
    format: str = 'mermaid',
    centrality: Optional[Dict[str, float]] = None,
    cycles: Optional[List[List[str]]] = None,
    layers: Optional[List[List[str]]] = None,
    max_nodes: int = 50,
) -> str:
    """
    Export graph in the specified format.
    
    Args:
        graph: DependencyGraph to export
        format: Output format ('mermaid', 'dot', 'json')
        centrality: Optional PageRank scores
        cycles: Optional detected cycles
        layers: Optional topological layers (for JSON only)
        max_nodes: Maximum nodes to include
    
    Returns:
        Formatted string
    
    Raises:
        ValueError: If format is not supported
    """
    fmt = format.lower()
    
    if fmt == 'mermaid':
        return export_mermaid(graph, centrality, cycles, max_nodes)
    elif fmt == 'dot' or fmt == 'graphviz':
        return export_dot(graph, centrality, cycles, max_nodes)
    elif fmt == 'json':
        return export_json(graph, centrality, layers, cycles)
    else:
        raise ValueError(f"Unsupported format: {format}. Use 'mermaid', 'dot', or 'json'.")


# ============================================================================
# ARCHITECTURE DIAGRAMS (Post-MVP Feature)
# ============================================================================

# Layer detection patterns for auto-classifying files
LAYER_PATTERNS = {
    'presentation': ['component', 'page', 'view', 'ui', 'screen', 'layout', 'template'],
    'application': ['handler', 'controller', 'route', 'api', 'endpoint', 'action', 'middleware'],
    'domain': ['model', 'entity', 'service', 'domain', 'core', 'business', 'logic'],
    'infrastructure': ['db', 'database', 'storage', 'http', 'client', 'adapter', 'repository'],
    'shared': ['util', 'helper', 'common', 'type', 'lib', 'shared', 'config', 'constant'],
}


def detect_layer_from_path(path: str) -> Optional[str]:
    """
    Detect architectural layer from file path.
    
    Args:
        path: File path
    
    Returns:
        Layer name or None if not detected
    """
    path_lower = path.lower()
    
    for layer, patterns in LAYER_PATTERNS.items():
        if any(p in path_lower for p in patterns):
            return layer
    
    return None


def classify_files_by_layer(
    files: List[str],
) -> Dict[str, List[str]]:
    """
    Classify files into architectural layers.
    
    Args:
        files: List of file paths
    
    Returns:
        Dict mapping layer name to list of files
    """
    from collections import defaultdict
    
    layers: Dict[str, List[str]] = defaultdict(list)
    
    for file in files:
        layer = detect_layer_from_path(file)
        if layer:
            layers[layer].append(file)
        else:
            # Unclassified files go to 'other'
            layers['other'].append(file)
    
    return dict(layers)


def classify_files_by_directory(
    files: List[str],
    max_depth: int = 2,
) -> Dict[str, List[str]]:
    """
    Group files by top-level directory.
    
    Args:
        files: List of file paths
        max_depth: Maximum directory depth for grouping
    
    Returns:
        Dict mapping directory to list of files
    """
    from collections import defaultdict
    
    groups: Dict[str, List[str]] = defaultdict(list)
    
    for file in files:
        parts = file.split('/')
        if len(parts) > 1:
            # Use first N directories as group key
            key = '/'.join(parts[:min(max_depth, len(parts) - 1)])
            groups[key].append(file)
        else:
            groups['root'].append(file)
    
    return dict(groups)


def generate_architecture_diagram(
    graph: DependencyGraph,
    classification: Optional[Dict[str, List[str]]] = None,
    cycles: Optional[List[List[str]]] = None,
    max_files_per_group: int = 10,
    direction: str = 'TB',
) -> str:
    """
    Generate a Mermaid architecture diagram with module clusters.
    
    Features:
    - Groups files into subgraphs by layer or directory
    - Highlights cycle edges in red
    - Shows dependencies between groups
    
    Args:
        graph: DependencyGraph to visualize
        classification: Optional file classification (layer -> files mapping).
                       If None, auto-classifies by layer detection.
        cycles: Optional list of cycles to highlight
        max_files_per_group: Max files to show per subgraph
        direction: Graph direction (TB = top-bottom, LR = left-right)
    
    Returns:
        Mermaid diagram string
    """
    # Auto-classify if not provided
    if classification is None:
        classification = classify_files_by_layer(list(graph.nodes))
        # Fall back to directory grouping if layer detection didn't work well
        if len(classification) <= 2:  # Only 'other' and maybe one layer
            classification = classify_files_by_directory(list(graph.nodes))
    
    lines = [f'graph {direction}']
    
    # Collect cycle edges for highlighting
    cycle_edges: Set[Tuple[str, str]] = set()
    cycle_nodes: Set[str] = set()
    if cycles:
        for cycle in cycles:
            cycle_nodes.update(cycle)
            for i, node in enumerate(cycle):
                next_node = cycle[(i + 1) % len(cycle)]
                cycle_edges.add((node, next_node))
    
    # Track all included nodes
    included_nodes: Set[str] = set()
    
    # Create subgraphs for each group
    layer_order = ['presentation', 'application', 'domain', 'infrastructure', 'shared', 'other']
    
    # Sort groups: known layers first, then alphabetically
    sorted_groups = sorted(
        classification.keys(),
        key=lambda g: (layer_order.index(g) if g in layer_order else len(layer_order), g)
    )
    
    for group in sorted_groups:
        files = classification[group]
        if not files:
            continue
        
        # Limit files per group
        display_files = files[:max_files_per_group]
        
        # Generate subgraph
        group_id = node_id(group)
        group_title = group.replace('_', ' ').title()
        
        lines.append(f'    subgraph {group_id}["{group_title}"]')
        
        for file in sorted(display_files):
            nid = node_id(file)
            label = shorten_path(file, 25)
            
            if file in cycle_nodes:
                # Cycle node: use special styling
                lines.append(f'        {nid}["{label}"]:::cycleNode')
            else:
                lines.append(f'        {nid}["{label}"]')
            
            included_nodes.add(file)
        
        if len(files) > max_files_per_group:
            lines.append(f'        more_{group_id}[("...{len(files) - max_files_per_group} more")]')
        
        lines.append('    end')
    
    lines.append('')
    
    # Add edges (only between included nodes)
    for source in sorted(included_nodes):
        for target in sorted(graph.edges.get(source, set())):
            if target in included_nodes:
                src_id = node_id(source)
                tgt_id = node_id(target)
                
                if (source, target) in cycle_edges:
                    lines.append(f'    {src_id} -.-o|cycle| {tgt_id}')
                else:
                    lines.append(f'    {src_id} --> {tgt_id}')
    
    # Add styling
    lines.append('')
    lines.append('    classDef cycleNode fill:#faa,stroke:#f00,stroke-width:2px')
    
    return '\n'.join(lines)


def generate_layer_diagram(
    graph: DependencyGraph,
    layers: Optional[List[List[str]]] = None,
    cycles: Optional[List[List[str]]] = None,
    max_files_per_layer: int = 8,
) -> str:
    """
    Generate a Mermaid diagram showing topological layers.
    
    Layers are determined by dependency depth:
    - Layer 0: Files with no imports (foundations)
    - Layer N: Files that only import from layers 0..N-1
    
    Args:
        graph: DependencyGraph
        layers: Optional pre-computed topological layers
        cycles: Optional cycles to highlight
        max_files_per_layer: Max files to show per layer
    
    Returns:
        Mermaid diagram string
    """
    # If no layers provided, import and compute them
    if layers is None:
        from .centrality import build_topological_layers
        layers = build_topological_layers(graph)
    
    lines = ['graph TB']
    
    # Collect cycle info
    cycle_nodes: Set[str] = set()
    if cycles:
        for cycle in cycles:
            cycle_nodes.update(cycle)
    
    included_nodes: Set[str] = set()
    
    # Create subgraphs for each layer
    for i, layer in enumerate(layers):
        if not layer:
            continue
        
        layer_id = f'layer_{i}'
        
        # Determine layer description
        if i == 0:
            layer_desc = "Foundation (no imports)"
        elif i == 1:
            layer_desc = "Core Utilities"
        elif i == len(layers) - 1:
            layer_desc = "Application Layer"
        else:
            layer_desc = f"Layer {i}"
        
        lines.append(f'    subgraph {layer_id}["{layer_desc}"]')
        
        # Sort by how many dependents they have (most important first)
        sorted_layer = sorted(layer, key=lambda f: graph.in_degree(f), reverse=True)
        display_files = sorted_layer[:max_files_per_layer]
        
        for file in display_files:
            nid = node_id(file)
            label = shorten_path(file, 25)
            
            if file in cycle_nodes:
                lines.append(f'        {nid}["{label}"]:::cycleNode')
            else:
                lines.append(f'        {nid}["{label}"]')
            
            included_nodes.add(file)
        
        if len(layer) > max_files_per_layer:
            lines.append(f'        more_{layer_id}[("...{len(layer) - max_files_per_layer} more")]')
        
        lines.append('    end')
    
    lines.append('')
    
    # Add edges
    for source in sorted(included_nodes):
        for target in sorted(graph.edges.get(source, set())):
            if target in included_nodes:
                src_id = node_id(source)
                tgt_id = node_id(target)
                lines.append(f'    {src_id} --> {tgt_id}')
    
    # Styling
    lines.append('')
    lines.append('    classDef cycleNode fill:#faa,stroke:#f00,stroke-width:2px')
    
    return '\n'.join(lines)


def generate_cycle_diagram(
    graph: DependencyGraph,
    cycles: List[List[str]],
    max_cycles: int = 5,
) -> str:
    """
    Generate a Mermaid diagram focused on circular dependencies.
    
    Shows only the files involved in cycles and their relationships.
    
    Args:
        graph: DependencyGraph
        cycles: List of detected cycles
        max_cycles: Maximum number of cycles to show
    
    Returns:
        Mermaid diagram string
    """
    if not cycles:
        return 'graph LR\n    no_cycles["No circular dependencies detected ✓"]:::good\n    classDef good fill:#afa,stroke:#0a0'
    
    lines = ['graph LR']
    
    # Limit cycles
    display_cycles = cycles[:max_cycles]
    
    # Collect all nodes in cycles
    all_cycle_nodes: Set[str] = set()
    cycle_edges: Set[Tuple[str, str]] = set()
    
    for cycle in display_cycles:
        all_cycle_nodes.update(cycle)
        for i, node in enumerate(cycle):
            next_node = cycle[(i + 1) % len(cycle)]
            cycle_edges.add((node, next_node))
    
    # Add nodes
    for node in sorted(all_cycle_nodes):
        nid = node_id(node)
        label = shorten_path(node, 25)
        lines.append(f'    {nid}["{label}"]:::cycleNode')
    
    lines.append('')
    
    # Add cycle edges
    for source, target in sorted(cycle_edges):
        src_id = node_id(source)
        tgt_id = node_id(target)
        lines.append(f'    {src_id} ==>|cycle| {tgt_id}')
    
    # Add any non-cycle edges between cycle nodes
    for source in sorted(all_cycle_nodes):
        for target in sorted(graph.edges.get(source, set())):
            if target in all_cycle_nodes and (source, target) not in cycle_edges:
                src_id = node_id(source)
                tgt_id = node_id(target)
                lines.append(f'    {src_id} --> {tgt_id}')
    
    # Styling
    lines.append('')
    lines.append('    classDef cycleNode fill:#faa,stroke:#f00,stroke-width:2px')
    
    if len(cycles) > max_cycles:
        lines.append(f'    note["...and {len(cycles) - max_cycles} more cycles"]')
    
    return '\n'.join(lines)


def export_architecture_diagram(
    graph: DependencyGraph,
    diagram_type: str = 'architecture',
    layers: Optional[List[List[str]]] = None,
    cycles: Optional[List[List[str]]] = None,
    classification: Optional[Dict[str, List[str]]] = None,
) -> str:
    """
    High-level function to generate architecture diagrams.
    
    Args:
        graph: DependencyGraph to visualize
        diagram_type: One of 'architecture', 'layers', 'cycles'
        layers: Optional topological layers
        cycles: Optional detected cycles
        classification: Optional file classification for architecture diagram
    
    Returns:
        Mermaid diagram string
    
    Raises:
        ValueError: If diagram_type is not supported
    """
    dtype = diagram_type.lower()
    
    if dtype == 'architecture':
        return generate_architecture_diagram(graph, classification, cycles)
    elif dtype == 'layers':
        return generate_layer_diagram(graph, layers, cycles)
    elif dtype == 'cycles':
        return generate_cycle_diagram(graph, cycles or [])
    else:
        raise ValueError(
            f"Unsupported diagram type: {diagram_type}. "
            "Use 'architecture', 'layers', or 'cycles'."
        )
