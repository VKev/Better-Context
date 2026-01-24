"""Coupling metrics calculator (Ca/Ce/I/A/D).

Implements Robert C. Martin's package metrics for evaluating module stability
and architectural health:

- Ca (Afferent Coupling): Number of modules that depend ON this module
- Ce (Efferent Coupling): Number of modules this module depends ON
- I (Instability): Ce / (Ca + Ce) - 0 = stable, 1 = unstable
- A (Abstractness): abstract definitions / total definitions
- D (Distance from Main Sequence): |A + I - 1| - 0 = ideal

Zone Analysis:
- Main Sequence: D ≈ 0 (healthy balance)
- Zone of Pain: I ≈ 0, A ≈ 0 (stable but concrete - hard to extend)
- Zone of Uselessness: I ≈ 1, A ≈ 1 (unstable and abstract - unused)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, List, Dict, Optional

if TYPE_CHECKING:
    from .graph import DependencyGraph
    from .manifest import FileEntry


@dataclass
class CouplingMetrics:
    """Coupling metrics for a single module/file."""
    
    path: str
    ca: int          # Afferent coupling (incoming dependencies)
    ce: int          # Efferent coupling (outgoing dependencies)
    i: float         # Instability: Ce / (Ca + Ce)
    a: float         # Abstractness: abstract / total
    d: float         # Distance from main sequence: |A + I - 1|
    zone: str        # Classification: 'main', 'pain', 'uselessness', 'neutral'
    abstract_count: int = 0  # Number of abstract definitions
    concrete_count: int = 0  # Number of concrete definitions


@dataclass
class ZoneReport:
    """Report on architectural zones in the codebase."""
    
    on_main_sequence: List[str] = field(default_factory=list)
    zone_of_pain: List[str] = field(default_factory=list)
    zone_of_uselessness: List[str] = field(default_factory=list)
    neutral: List[str] = field(default_factory=list)
    recommendations: List[str] = field(default_factory=list)


# Types considered abstract by language
ABSTRACT_TYPES = {
    'interface',
    'type',
    'type_alias',
    'protocol',
    'abstract_class',
    'abc',
}

# Types considered concrete implementations
CONCRETE_TYPES = {
    'function',
    'class',
    'method',
    'variable',
    'constant',
}


def is_abstract_chunk(chunk_type: str, metadata: dict) -> bool:
    """Determine if a chunk represents an abstract definition.
    
    Args:
        chunk_type: The chunk's type field
        metadata: The chunk's metadata dict
    
    Returns:
        True if the chunk is abstract (interface, type, protocol, etc.)
    """
    if chunk_type in ABSTRACT_TYPES:
        return True
    
    # Check metadata flags
    if metadata.get('is_abstract', False):
        return True
    if metadata.get('is_protocol', False):
        return True
    if metadata.get('is_interface', False):
        return True
    
    return False


def count_abstract_definitions(file: "FileEntry") -> int:
    """Count abstract definitions in a file.
    
    Abstract definitions include:
    - TypeScript/Java interfaces
    - TypeScript type aliases
    - Python Protocols and ABCs
    - Abstract classes
    
    Args:
        file: FileEntry with chunks
    
    Returns:
        Count of abstract definitions
    """
    abstract_count = 0
    for chunk in file.chunks:
        if is_abstract_chunk(chunk.type, chunk.metadata):
            abstract_count += 1
    return abstract_count


def count_concrete_definitions(file: "FileEntry") -> int:
    """Count concrete (non-abstract) definitions in a file.
    
    Args:
        file: FileEntry with chunks
    
    Returns:
        Count of concrete definitions
    """
    concrete_count = 0
    for chunk in file.chunks:
        if not is_abstract_chunk(chunk.type, chunk.metadata):
            concrete_count += 1
    return concrete_count


def classify_zone(i: float, a: float) -> str:
    """Classify a module into an architectural zone.
    
    Zones based on Robert C. Martin's package metrics:
    - Main Sequence: D ≤ 0.2 (healthy balance of stability and abstractness)
    - Zone of Pain: Low I, Low A (stable but concrete - hard to extend)
    - Zone of Uselessness: High I, High A (unstable and abstract - unused)
    - Neutral: Everything else
    
    Args:
        i: Instability metric (0-1)
        a: Abstractness metric (0-1)
    
    Returns:
        Zone classification string
    """
    d = abs(a + i - 1)
    
    if d <= 0.2:
        return 'main'
    elif i < 0.3 and a < 0.3:
        return 'pain'
    elif i > 0.7 and a > 0.7:
        return 'uselessness'
    else:
        return 'neutral'


def calculate_coupling_metrics(
    module_path: str,
    graph: "DependencyGraph",
    files: List["FileEntry"],
) -> CouplingMetrics:
    """Calculate coupling metrics for a single module.
    
    Args:
        module_path: Path to the module/file
        graph: Dependency graph
        files: List of all file entries
    
    Returns:
        CouplingMetrics for the module
    """
    # Afferent coupling: files that depend on this module
    ca = graph.in_degree(module_path)
    
    # Efferent coupling: files this module depends on
    ce = graph.out_degree(module_path)
    
    # Instability
    total = ca + ce
    i = ce / total if total > 0 else 0.5  # Default to 0.5 if isolated
    
    # Find the file entry for abstractness calculation
    file_entry = next((f for f in files if f.path == module_path), None)
    
    abstract_count = 0
    concrete_count = 0
    a = 0.0
    
    if file_entry and file_entry.chunks:
        abstract_count = count_abstract_definitions(file_entry)
        concrete_count = count_concrete_definitions(file_entry)
        total_defs = abstract_count + concrete_count
        a = abstract_count / total_defs if total_defs > 0 else 0.0
    
    # Distance from main sequence
    d = abs(a + i - 1)
    
    # Classify zone
    zone = classify_zone(i, a)
    
    return CouplingMetrics(
        path=module_path,
        ca=ca,
        ce=ce,
        i=i,
        a=a,
        d=d,
        zone=zone,
        abstract_count=abstract_count,
        concrete_count=concrete_count,
    )


def calculate_all_coupling_metrics(
    graph: "DependencyGraph",
    files: List["FileEntry"],
) -> Dict[str, CouplingMetrics]:
    """Calculate coupling metrics for all files in the graph.
    
    Args:
        graph: Dependency graph
        files: List of all file entries
    
    Returns:
        Dict mapping file paths to their CouplingMetrics
    """
    metrics = {}
    
    for node in graph.nodes:
        metrics[node] = calculate_coupling_metrics(node, graph, files)
    
    return metrics


def calculate_directory_metrics(
    dir_path: str,
    files: List["FileEntry"],
    graph: "DependencyGraph",
) -> CouplingMetrics:
    """Calculate aggregate coupling metrics for a directory.
    
    This aggregates metrics for all files within a directory,
    treating the directory as a single module.
    
    Args:
        dir_path: Directory path (relative)
        files: All file entries
        graph: Dependency graph
    
    Returns:
        Aggregated CouplingMetrics for the directory
    """
    # Normalize path
    dir_path = dir_path.rstrip('/')
    
    # Get all files in directory
    dir_files = [f for f in files if f.path.startswith(dir_path + '/') or f.path == dir_path]
    dir_paths = {f.path for f in dir_files}
    
    if not dir_files:
        return CouplingMetrics(
            path=dir_path,
            ca=0,
            ce=0,
            i=0.5,
            a=0.0,
            d=0.5,
            zone='neutral',
        )
    
    # Calculate external connections (edges crossing directory boundary)
    # Ca: external files importing files in this directory
    ca_set: set[str] = set()
    for f in dir_files:
        for dependent in graph.get_dependents(f.path):
            if dependent not in dir_paths:
                ca_set.add(dependent)
    ca = len(ca_set)
    
    # Ce: files in this directory importing external files
    ce_set: set[str] = set()
    for f in dir_files:
        for dependency in graph.get_dependencies(f.path):
            if dependency not in dir_paths:
                ce_set.add(dependency)
    ce = len(ce_set)
    
    # Aggregate abstractness
    abstract = sum(count_abstract_definitions(f) for f in dir_files)
    concrete = sum(count_concrete_definitions(f) for f in dir_files)
    total = abstract + concrete
    a = abstract / total if total > 0 else 0.0
    
    # Calculate derived metrics
    total_coupling = ca + ce
    i = ce / total_coupling if total_coupling > 0 else 0.5
    d = abs(a + i - 1)
    zone = classify_zone(i, a)
    
    return CouplingMetrics(
        path=dir_path,
        ca=ca,
        ce=ce,
        i=i,
        a=a,
        d=d,
        zone=zone,
        abstract_count=abstract,
        concrete_count=concrete,
    )


def generate_zone_report(metrics: Dict[str, CouplingMetrics]) -> ZoneReport:
    """Generate a report analyzing architectural zones.
    
    Args:
        metrics: Dict mapping paths to CouplingMetrics
    
    Returns:
        ZoneReport with classifications and recommendations
    """
    report = ZoneReport()
    
    for path, m in sorted(metrics.items()):
        if m.zone == 'main':
            report.on_main_sequence.append(path)
        elif m.zone == 'pain':
            report.zone_of_pain.append(path)
            report.recommendations.append(
                f"{path}: Zone of Pain (I={m.i:.2f}, A={m.a:.2f}). "
                "This module is stable but concrete. Consider adding abstractions "
                "(interfaces, protocols) to make it more extensible."
            )
        elif m.zone == 'uselessness':
            report.zone_of_uselessness.append(path)
            report.recommendations.append(
                f"{path}: Zone of Uselessness (I={m.i:.2f}, A={m.a:.2f}). "
                "This module is unstable and overly abstract. Consider adding "
                "implementations or reconsidering if abstractions are needed."
            )
        else:
            report.neutral.append(path)
    
    return report


def identify_critical_modules(
    metrics: Dict[str, CouplingMetrics],
    ca_threshold: int = 5,
    d_threshold: float = 0.4,
) -> List[Dict[str, any]]:
    """Identify modules that are critical or problematic.
    
    Critical modules are those with:
    - High afferent coupling (many dependents)
    - In Zone of Pain with high distance from main sequence
    - High instability with many dependents
    
    Args:
        metrics: Dict mapping paths to CouplingMetrics
        ca_threshold: Minimum afferent coupling to be considered critical
        d_threshold: Minimum distance from main sequence to flag
    
    Returns:
        List of critical module info dicts sorted by risk score
    """
    critical = []
    
    for path, m in metrics.items():
        score = 0.0
        reasons = []
        
        # High afferent coupling = risky to change
        if m.ca >= ca_threshold:
            score += m.ca * 2  # Weight by number of dependents
            reasons.append(f"High impact ({m.ca} dependents)")
        
        # Zone of Pain with significant distance
        if m.zone == 'pain' and m.d > d_threshold:
            score += 20
            reasons.append("Stable but concrete (hard to extend)")
        
        # Zone of Uselessness
        if m.zone == 'uselessness':
            score += 15
            reasons.append("Unstable and abstract (possibly unused)")
        
        # High instability with dependents is risky
        if m.i > 0.7 and m.ca > 0:
            score += 10
            reasons.append(f"Unstable with {m.ca} dependents")
        
        if score > 0:
            critical.append({
                'path': path,
                'score': score,
                'reasons': reasons,
                'metrics': m,
            })
    
    return sorted(critical, key=lambda x: x['score'], reverse=True)


def get_coupling_summary(metrics: Dict[str, CouplingMetrics]) -> dict:
    """Get summary statistics for coupling metrics.
    
    Args:
        metrics: Dict mapping paths to CouplingMetrics
    
    Returns:
        Summary statistics dict
    """
    if not metrics:
        return {
            'total_modules': 0,
            'zone_counts': {},
            'avg_instability': 0,
            'avg_abstractness': 0,
            'avg_distance': 0,
        }
    
    zone_counts = {'main': 0, 'pain': 0, 'uselessness': 0, 'neutral': 0}
    total_i = 0.0
    total_a = 0.0
    total_d = 0.0
    
    for m in metrics.values():
        zone_counts[m.zone] = zone_counts.get(m.zone, 0) + 1
        total_i += m.i
        total_a += m.a
        total_d += m.d
    
    n = len(metrics)
    
    return {
        'total_modules': n,
        'zone_counts': zone_counts,
        'avg_instability': total_i / n,
        'avg_abstractness': total_a / n,
        'avg_distance': total_d / n,
        'health_score': zone_counts['main'] / n if n > 0 else 0,
    }


def format_coupling_table(metrics: Dict[str, CouplingMetrics], limit: int = 20) -> str:
    """Format coupling metrics as a markdown table.
    
    Args:
        metrics: Dict mapping paths to CouplingMetrics
        limit: Maximum rows to show
    
    Returns:
        Markdown table string
    """
    lines = [
        "| File | Ca | Ce | I | A | D | Zone |",
        "|------|----|----|-----|-----|-----|------|",
    ]
    
    # Sort by distance from main sequence (worst first)
    sorted_metrics = sorted(metrics.values(), key=lambda m: m.d, reverse=True)
    
    for m in sorted_metrics[:limit]:
        zone_emoji = {
            'main': '✅',
            'pain': '⚠️',
            'uselessness': '❌',
            'neutral': '➖',
        }.get(m.zone, '➖')
        
        lines.append(
            f"| {m.path} | {m.ca} | {m.ce} | {m.i:.2f} | {m.a:.2f} | {m.d:.2f} | {zone_emoji} {m.zone} |"
        )
    
    if len(metrics) > limit:
        lines.append(f"| ... | | | | | | ({len(metrics) - limit} more) |")
    
    return '\n'.join(lines)


# Export public API
__all__ = [
    'CouplingMetrics',
    'ZoneReport',
    'ABSTRACT_TYPES',
    'CONCRETE_TYPES',
    'is_abstract_chunk',
    'count_abstract_definitions',
    'count_concrete_definitions',
    'classify_zone',
    'calculate_coupling_metrics',
    'calculate_all_coupling_metrics',
    'calculate_directory_metrics',
    'generate_zone_report',
    'identify_critical_modules',
    'get_coupling_summary',
    'format_coupling_table',
]
