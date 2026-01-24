"""Architecture layer detection.

Automatically classifies files and directories into architectural layers:
- Presentation: UI components, views, pages
- Application: Use cases, handlers, controllers
- Domain: Business logic, models, entities
- Infrastructure: Database, external APIs, adapters
- Shared: Cross-cutting utilities, types, helpers

Detection uses multiple heuristics:
1. Directory naming patterns
2. Import direction analysis
3. Export type analysis (types vs implementations)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, List, Dict, Optional, Set

if TYPE_CHECKING:
    from .graph import DependencyGraph
    from .manifest import FileEntry


# Architectural layer definitions (ordered from lowest to highest)
LAYER_ORDER = ['infrastructure', 'shared', 'domain', 'application', 'presentation']

# Layer index lookup
LAYER_INDEX = {layer: i for i, layer in enumerate(LAYER_ORDER)}


@dataclass
class LayerClassification:
    """Classification result for a file."""
    
    path: str
    layer: str
    confidence: float  # 0.0-1.0
    method: str  # 'path', 'exports', 'imports', 'default'
    

@dataclass
class LayerViolation:
    """A detected layer violation."""
    
    source_path: str
    source_layer: str
    target_path: str
    target_layer: str
    message: str


@dataclass
class ArchitectureReport:
    """Complete architecture analysis report."""
    
    layers: Dict[str, List[str]] = field(default_factory=dict)
    violations: List[LayerViolation] = field(default_factory=list)
    classifications: Dict[str, LayerClassification] = field(default_factory=dict)
    stats: Dict[str, any] = field(default_factory=dict)


# Layer detection patterns by directory name
# Key: layer name, Value: list of path patterns to match
LAYER_PATTERNS: Dict[str, List[str]] = {
    'presentation': [
        'component', 'page', 'view', 'ui', 'screen', 'layout',
        'template', 'widget', 'dialog', 'modal', 'form',
        'pages', 'components', 'views', 'screens', 'layouts',
        'templates', 'widgets', 'dialogs', 'modals', 'forms',
    ],
    'application': [
        'handler', 'controller', 'route', 'api', 'endpoint', 'action',
        'usecase', 'use-case', 'use_case', 'command', 'query',
        'handlers', 'controllers', 'routes', 'endpoints', 'actions',
        'usecases', 'commands', 'queries',
    ],
    'domain': [
        'model', 'entity', 'service', 'domain', 'core', 'business',
        'aggregate', 'value', 'repository',
        'models', 'entities', 'services', 'aggregates', 'repositories',
    ],
    'infrastructure': [
        'db', 'database', 'storage', 'http', 'client', 'adapter',
        'external', 'integration', 'provider', 'gateway', 'driver',
        'persistence', 'cache', 'queue', 'messaging',
        'adapters', 'providers', 'gateways', 'drivers',
    ],
    'shared': [
        'util', 'utils', 'helper', 'helpers', 'common', 'type', 'types',
        'lib', 'shared', 'config', 'constant', 'constants',
        'interface', 'interfaces', 'dto', 'dtos', 'schema', 'schemas',
    ],
}


def detect_layer_from_path(path: str) -> Optional[str]:
    """Detect layer from file/directory path patterns.
    
    This is the highest confidence method - matches explicit naming.
    
    Args:
        path: File path (relative)
    
    Returns:
        Layer name or None if no match
    """
    path_lower = path.lower()
    path_parts = path_lower.replace('\\', '/').split('/')
    
    for layer, patterns in LAYER_PATTERNS.items():
        for pattern in patterns:
            # Check if any path component matches
            for part in path_parts:
                # Exact match or pattern at start/end
                if part == pattern or part.startswith(pattern) or part.endswith(pattern):
                    return layer
            # Also check if pattern appears in the path
            if pattern in path_lower:
                return layer
    
    return None


def detect_layer_from_exports(file: "FileEntry") -> Optional[str]:
    """Detect layer from export composition.
    
    Files exporting mostly types/interfaces are likely shared.
    Files with no exports might be entry points (presentation).
    
    Args:
        file: FileEntry with exports
    
    Returns:
        Layer name or None if inconclusive
    """
    if not file.exports:
        return None
    
    type_exports = sum(
        1 for e in file.exports 
        if e.type in ('type', 'interface', 'type_alias')
    )
    impl_exports = len(file.exports) - type_exports
    
    # Mostly types = shared layer
    if type_exports > impl_exports * 2:
        return 'shared'
    
    return None


def detect_layer_from_imports(
    file: "FileEntry",
    graph: "DependencyGraph",
    file_layers: Dict[str, str],
) -> str:
    """Infer layer from what a file imports.
    
    A file should be at or above the highest layer it imports from.
    
    Args:
        file: FileEntry to classify
        graph: Dependency graph
        file_layers: Already classified files
    
    Returns:
        Inferred layer name
    """
    imports = graph.get_dependencies(file.path)
    
    if not imports:
        return 'shared'  # No imports = likely utility/type file
    
    # Find the highest layer among imports
    max_layer_idx = -1
    for imp in imports:
        if imp in file_layers:
            layer = file_layers[imp]
            if layer in LAYER_INDEX:
                idx = LAYER_INDEX[layer]
                max_layer_idx = max(max_layer_idx, idx)
    
    if max_layer_idx == -1:
        return 'domain'  # Default guess
    
    # File should be at or above its highest import
    # (add 1 but cap at max layer)
    new_idx = min(max_layer_idx + 1, len(LAYER_ORDER) - 1)
    return LAYER_ORDER[new_idx]


def classify_file_layer(
    file: "FileEntry",
    graph: "DependencyGraph",
    existing_layers: Dict[str, str],
) -> LayerClassification:
    """Classify a file into an architectural layer.
    
    Uses multiple heuristics in order of confidence:
    1. Path patterns (highest confidence)
    2. Export types
    3. Import analysis (lowest confidence)
    
    Args:
        file: FileEntry to classify
        graph: Dependency graph
        existing_layers: Already classified files
    
    Returns:
        LayerClassification with layer and confidence
    """
    # 1. Check path patterns (highest confidence)
    path_layer = detect_layer_from_path(file.path)
    if path_layer:
        return LayerClassification(
            path=file.path,
            layer=path_layer,
            confidence=0.9,
            method='path',
        )
    
    # 2. Check export types
    export_layer = detect_layer_from_exports(file)
    if export_layer:
        return LayerClassification(
            path=file.path,
            layer=export_layer,
            confidence=0.7,
            method='exports',
        )
    
    # 3. Infer from imports
    import_layer = detect_layer_from_imports(file, graph, existing_layers)
    return LayerClassification(
        path=file.path,
        layer=import_layer,
        confidence=0.5,
        method='imports',
    )


def classify_all_files(
    files: List["FileEntry"],
    graph: "DependencyGraph",
) -> Dict[str, LayerClassification]:
    """Classify all files into architectural layers.
    
    Uses two-pass approach:
    1. First pass: classify by path and exports (high confidence)
    2. Second pass: classify remaining by imports (using first pass results)
    
    Args:
        files: All file entries
        graph: Dependency graph
    
    Returns:
        Dict mapping file paths to LayerClassification
    """
    classifications: Dict[str, LayerClassification] = {}
    file_layers: Dict[str, str] = {}
    
    # First pass: classify by path and exports
    unclassified = []
    for file in files:
        path_layer = detect_layer_from_path(file.path)
        if path_layer:
            classification = LayerClassification(
                path=file.path,
                layer=path_layer,
                confidence=0.9,
                method='path',
            )
            classifications[file.path] = classification
            file_layers[file.path] = path_layer
            continue
        
        export_layer = detect_layer_from_exports(file)
        if export_layer:
            classification = LayerClassification(
                path=file.path,
                layer=export_layer,
                confidence=0.7,
                method='exports',
            )
            classifications[file.path] = classification
            file_layers[file.path] = export_layer
            continue
        
        unclassified.append(file)
    
    # Second pass: classify remaining by imports
    for file in unclassified:
        import_layer = detect_layer_from_imports(file, graph, file_layers)
        classification = LayerClassification(
            path=file.path,
            layer=import_layer,
            confidence=0.5,
            method='imports',
        )
        classifications[file.path] = classification
        file_layers[file.path] = import_layer
    
    return classifications


def get_layer_map(classifications: Dict[str, LayerClassification]) -> Dict[str, str]:
    """Extract simple path -> layer mapping from classifications.
    
    Args:
        classifications: Full classification results
    
    Returns:
        Dict mapping paths to layer names
    """
    return {path: c.layer for path, c in classifications.items()}


def detect_layer_violations(
    files: List["FileEntry"],
    layers: Dict[str, str],
    graph: "DependencyGraph",
) -> List[LayerViolation]:
    """Detect imports that violate the layer hierarchy.
    
    Violations occur when a lower layer imports from a higher layer.
    For example, infrastructure importing from presentation.
    
    Args:
        files: All file entries
        layers: File path to layer mapping
        graph: Dependency graph
    
    Returns:
        List of detected violations
    """
    violations = []
    
    for file in files:
        file_layer = layers.get(file.path)
        if not file_layer or file_layer not in LAYER_INDEX:
            continue
        
        file_layer_idx = LAYER_INDEX[file_layer]
        
        for imported in graph.get_dependencies(file.path):
            imported_layer = layers.get(imported)
            if not imported_layer or imported_layer not in LAYER_INDEX:
                continue
            
            imported_layer_idx = LAYER_INDEX[imported_layer]
            
            # Higher layers importing lower layers is OK
            # Lower layers importing higher layers is a violation
            if imported_layer_idx > file_layer_idx:
                violations.append(LayerViolation(
                    source_path=file.path,
                    source_layer=file_layer,
                    target_path=imported,
                    target_layer=imported_layer,
                    message=(
                        f"{file_layer} layer should not import from {imported_layer} layer: "
                        f"{file.path} → {imported}"
                    ),
                ))
    
    return violations


def analyze_architecture(
    files: List["FileEntry"],
    graph: "DependencyGraph",
) -> ArchitectureReport:
    """Perform complete architecture analysis.
    
    Args:
        files: All file entries
        graph: Dependency graph
    
    Returns:
        ArchitectureReport with layers, violations, and stats
    """
    # Classify all files
    classifications = classify_all_files(files, graph)
    layers_map = get_layer_map(classifications)
    
    # Group by layer
    layers: Dict[str, List[str]] = {layer: [] for layer in LAYER_ORDER}
    for path, layer in layers_map.items():
        if layer in layers:
            layers[layer].append(path)
    
    # Sort each layer's files
    for layer in layers:
        layers[layer].sort()
    
    # Detect violations
    violations = detect_layer_violations(files, layers_map, graph)
    
    # Calculate stats
    total = len(classifications)
    high_confidence = sum(1 for c in classifications.values() if c.confidence >= 0.7)
    
    stats = {
        'total_files': total,
        'layer_counts': {layer: len(paths) for layer, paths in layers.items()},
        'high_confidence_count': high_confidence,
        'confidence_ratio': high_confidence / total if total > 0 else 0,
        'violation_count': len(violations),
        'classification_methods': {
            'path': sum(1 for c in classifications.values() if c.method == 'path'),
            'exports': sum(1 for c in classifications.values() if c.method == 'exports'),
            'imports': sum(1 for c in classifications.values() if c.method == 'imports'),
        },
    }
    
    return ArchitectureReport(
        layers=layers,
        violations=violations,
        classifications=classifications,
        stats=stats,
    )


def format_layer_summary(report: ArchitectureReport) -> str:
    """Format architecture report as markdown.
    
    Args:
        report: ArchitectureReport
    
    Returns:
        Markdown string
    """
    lines = ["## 🏗️ Architecture Layers\n"]
    
    layer_emojis = {
        'presentation': '🖥️',
        'application': '⚙️',
        'domain': '💼',
        'infrastructure': '🔧',
        'shared': '📦',
    }
    
    for layer in LAYER_ORDER:
        emoji = layer_emojis.get(layer, '📁')
        count = len(report.layers.get(layer, []))
        lines.append(f"| {emoji} {layer.title()} | {count} files |")
    
    if report.violations:
        lines.append(f"\n⚠️ **{len(report.violations)} layer violation(s) detected**\n")
        for v in report.violations[:5]:
            lines.append(f"- {v.message}")
        if len(report.violations) > 5:
            lines.append(f"- ... and {len(report.violations) - 5} more")
    
    return '\n'.join(lines)


def format_layer_violations(violations: List[LayerViolation]) -> str:
    """Format layer violations as markdown table.
    
    Args:
        violations: List of LayerViolation
    
    Returns:
        Markdown table string
    """
    if not violations:
        return "✅ No layer violations detected."
    
    lines = [
        "| Source | Source Layer | Target | Target Layer |",
        "|--------|--------------|--------|--------------|",
    ]
    
    for v in violations:
        lines.append(f"| {v.source_path} | {v.source_layer} | {v.target_path} | {v.target_layer} |")
    
    return '\n'.join(lines)


# Export public API
__all__ = [
    'LAYER_ORDER',
    'LAYER_INDEX',
    'LAYER_PATTERNS',
    'LayerClassification',
    'LayerViolation',
    'ArchitectureReport',
    'detect_layer_from_path',
    'detect_layer_from_exports',
    'detect_layer_from_imports',
    'classify_file_layer',
    'classify_all_files',
    'get_layer_map',
    'detect_layer_violations',
    'analyze_architecture',
    'format_layer_summary',
    'format_layer_violations',
]
