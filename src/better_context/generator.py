"""AGENTS.md output generation.

Generates the hierarchical AGENTS.md files that AI agents consume.
Uses the template engine for rendering with context from manifest and graph analysis.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .manifest import Manifest, FileEntry
from .graph import DependencyGraph
from .centrality import calculate_pagerank, find_cycles, build_topological_layers, get_top_files
from .template import render_template, SimpleTemplate, ROOT_TEMPLATE, DIRECTORY_TEMPLATE
from .tree import build_directory_tree_string


@dataclass
class GeneratorConfig:
    """Configuration for AGENTS.md generation."""
    
    # Output control
    max_depth: int = -1  # -1 = unlimited
    max_key_files: int = 10
    max_external_deps: int = 10
    include_metrics: bool = True
    include_diagrams: bool = True
    
    # Templates
    root_template: str | None = None  # Custom template override
    directory_template: str | None = None
    
    # Formatting
    emoji_headers: bool = True
    line_limit: int = 500  # Max lines per AGENTS.md


@dataclass
class DirectoryContext:
    """Context for rendering a directory's AGENTS.md."""
    
    path: Path  # Absolute path
    rel_path: str  # Relative to project root
    name: str  # Directory name
    files: list[FileEntry]
    subdirs: list[str]
    key_files: list[dict[str, Any]]
    imports: list[dict[str, Any]]
    exports: list[dict[str, Any]]
    
    # Graph metrics for this directory
    pagerank_sum: float = 0.0
    cycle_count: int = 0


@dataclass
class GeneratorResult:
    """Result of AGENTS.md generation."""
    
    files_written: list[str] = field(default_factory=list)
    total_lines: int = 0
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def generate_agents_md(
    manifest: Manifest,
    graph: DependencyGraph,
    output_root: Path,
    config: GeneratorConfig | None = None,
) -> GeneratorResult:
    """Generate hierarchical AGENTS.md files from manifest and graph.
    
    Args:
        manifest: The analysis manifest
        graph: Dependency graph
        output_root: Root directory to write AGENTS.md files to
        config: Optional configuration
    
    Returns:
        GeneratorResult with list of files written
    """
    config = config or GeneratorConfig()
    result = GeneratorResult()
    
    # Calculate centrality scores
    scores = calculate_pagerank(graph)
    
    # Find cycles
    cycles = find_cycles(graph)
    
    # Build topological layers
    layers = build_topological_layers(graph)
    
    # Generate root AGENTS.md
    root_context = build_root_context(manifest, graph, scores, cycles, layers, config)
    root_content = render_root_template(root_context, config)
    
    root_path = output_root / "AGENTS.md"
    root_path.write_text(root_content, encoding="utf-8")
    result.files_written.append(str(root_path))
    result.total_lines += root_content.count('\n')
    
    # Generate directory AGENTS.md files
    if config.max_depth != 0:
        directories = collect_directories(manifest)
        
        for rel_dir in directories:
            if config.max_depth > 0:
                depth = rel_dir.count('/') + 1
                if depth > config.max_depth:
                    continue
            
            dir_context = build_directory_context(
                rel_dir, manifest, graph, scores, config
            )
            dir_content = render_directory_template(dir_context, config)
            
            dir_path = output_root / rel_dir / "AGENTS.md"
            dir_path.parent.mkdir(parents=True, exist_ok=True)
            dir_path.write_text(dir_content, encoding="utf-8")
            result.files_written.append(str(dir_path))
            result.total_lines += dir_content.count('\n')
    
    return result


def build_root_context(
    manifest: Manifest,
    graph: DependencyGraph,
    scores: dict[str, float],
    cycles: list[list[str]],
    layers: list[list[str]],
    config: GeneratorConfig,
) -> dict[str, Any]:
    """Build context for root AGENTS.md template."""
    
    # Project name from root path
    project_name = Path(manifest.meta.root_path).name
    
    # Build directory tree
    file_paths = [f.path for f in manifest.files]
    directory_tree = build_directory_tree_string(file_paths)
    
    # Get top files by PageRank
    top_files = get_top_files(scores, config.max_key_files)
    key_files = []
    for file_path, score in top_files:
        file_entry = next((f for f in manifest.files if f.path == file_path), None)
        description = generate_file_description(file_entry, graph) if file_entry else ""
        key_files.append({
            'path': file_path,
            'centrality': f"{score:.4f}",
            'description': description,
        })
    
    # Build layer info
    layer_info = []
    for i, layer in enumerate(layers):
        layer_info.append({
            'number': i,
            'count': len(layer),
            'description': describe_layer(i, layer),
        })
    
    # External dependencies
    external_deps = collect_external_deps(manifest, config.max_external_deps)
    
    # Dependency diagram (Mermaid)
    dependency_diagram = generate_mermaid_diagram(graph, config.max_key_files)
    
    # Metrics
    metrics = {
        'total_files': len(manifest.files),
        'total_chunks': sum(len(f.chunks) for f in manifest.files),
        'internal_edges': len(graph.get_all_edges()),
        'external_packages': len(external_deps.split('\n')) if external_deps else 0,
        'violations': None,  # TODO: architecture violations
    }
    
    # Subdirectories
    subdirs = get_top_level_dirs(manifest)
    subdirectories = [
        {'purpose': guess_directory_purpose(d), 'path': d}
        for d in subdirs
    ]
    
    # Format cycles for display
    cycle_strings = [" → ".join(c + [c[0]]) for c in cycles]
    
    return {
        'project_name': project_name,
        'generated_at': manifest.meta.generated_at,
        'purpose': generate_project_purpose(manifest),
        'directory_tree': directory_tree,
        'key_files': key_files,
        'layers': layer_info,
        'external_deps': external_deps,
        'dependency_diagram': dependency_diagram,
        'has_cycles': len(cycles) > 0,
        'cycles': cycle_strings,
        'metrics': metrics,
        'subdirectories': subdirectories,
    }


def build_directory_context(
    rel_dir: str,
    manifest: Manifest,
    graph: DependencyGraph,
    scores: dict[str, float],
    config: GeneratorConfig,
) -> dict[str, Any]:
    """Build context for a directory's AGENTS.md."""
    
    dir_name = Path(rel_dir).name or rel_dir
    
    # Get files in this directory
    dir_files = [f for f in manifest.files if f.path.startswith(rel_dir + '/') or f.path == rel_dir]
    direct_files = [f for f in dir_files if '/' not in f.path[len(rel_dir)+1:]]
    
    # Format file info
    files = []
    for f in direct_files:
        score = scores.get(f.path, 0)
        files.append({
            'name': Path(f.path).name,
            'description': generate_file_description(f, graph),
            'centrality': f"{score:.4f}",
        })
    
    # Sort by centrality
    files.sort(key=lambda x: float(x['centrality']), reverse=True)
    
    # Get subdirectories
    subdirs = get_subdirs_of(rel_dir, manifest)
    has_subdirs = len(subdirs) > 0
    subdir_info = [
        {'name': d, 'purpose': guess_directory_purpose(d)}
        for d in subdirs
    ]
    
    # Get exports from files in this directory
    exports = []
    for f in direct_files:
        for exp in f.exports:
            exports.append({
                'name': exp.name,
                'type': exp.type,
                'description': '',  # TODO: extract from docstring
            })
    
    # Dependencies
    internal_deps = []
    external_deps = []
    for f in direct_files:
        for imp in f.imports:
            if imp.is_relative or not imp.module.startswith('.'):
                # Guess if internal or external
                if any(mf.path.endswith(imp.module.replace('.', '/') + '.py') for mf in manifest.files):
                    internal_deps.append({
                        'path': imp.module,
                        'symbols': ', '.join(imp.symbols) if imp.symbols else '*',
                    })
                else:
                    external_deps.append({
                        'package': imp.module.split('.')[0],
                        'symbols': ', '.join(imp.symbols) if imp.symbols else '*',
                    })
    
    return {
        'directory_name': dir_name,
        'directory_path': rel_dir,
        'purpose': guess_directory_purpose(rel_dir),
        'files': files,
        'has_subdirs': has_subdirs,
        'subdirs': subdir_info,
        'exports': exports[:20],  # Limit exports shown
        'internal_deps': internal_deps[:20],
        'external_deps': external_deps[:20],
    }


def render_root_template(context: dict[str, Any], config: GeneratorConfig) -> str:
    """Render the root AGENTS.md template."""
    if config.root_template:
        template = SimpleTemplate(config.root_template)
    else:
        template = SimpleTemplate(ROOT_TEMPLATE)
    
    return template.render(context)


def render_directory_template(context: dict[str, Any], config: GeneratorConfig) -> str:
    """Render a directory AGENTS.md template."""
    if config.directory_template:
        template = SimpleTemplate(config.directory_template)
    else:
        template = SimpleTemplate(DIRECTORY_TEMPLATE)
    
    return template.render(context)


def collect_directories(manifest: Manifest) -> list[str]:
    """Get all directories that contain files."""
    dirs = set()
    for f in manifest.files:
        path = Path(f.path)
        for parent in path.parents:
            if str(parent) != '.':
                dirs.add(str(parent))
    return sorted(dirs)


def get_top_level_dirs(manifest: Manifest) -> list[str]:
    """Get top-level directories."""
    dirs = set()
    for f in manifest.files:
        parts = f.path.split('/')
        if len(parts) > 1:
            dirs.add(parts[0])
    return sorted(dirs)


def get_subdirs_of(parent: str, manifest: Manifest) -> list[str]:
    """Get immediate subdirectories of a directory."""
    subdirs = set()
    prefix = parent + '/'
    for f in manifest.files:
        if f.path.startswith(prefix):
            rest = f.path[len(prefix):]
            if '/' in rest:
                subdirs.add(rest.split('/')[0])
    return sorted(subdirs)


def generate_file_description(file_entry: FileEntry | None, graph: DependencyGraph) -> str:
    """Generate a brief description for a file."""
    if not file_entry:
        return ""
    
    parts = []
    
    # Count exports
    if file_entry.exports:
        parts.append(f"{len(file_entry.exports)} exports")
    
    # Count dependents
    in_degree = graph.in_degree(file_entry.path)
    if in_degree > 0:
        parts.append(f"{in_degree} dependents")
    
    # Detect patterns
    path_lower = file_entry.path.lower()
    if 'index' in path_lower or '__init__' in path_lower:
        parts.append("barrel export")
    if 'types' in path_lower or 'interface' in path_lower:
        parts.append("type definitions")
    if 'test' in path_lower:
        parts.append("tests")
    if 'config' in path_lower:
        parts.append("configuration")
    
    return ' - '.join(parts) if parts else "module"


def describe_layer(layer_num: int, files: list[str]) -> str:
    """Generate a description for a topological layer."""
    if layer_num == 0:
        return "Foundation (no dependencies)"
    elif layer_num == 1:
        return "Core utilities and helpers"
    else:
        return f"Application layer {layer_num}"


def collect_external_deps(manifest: Manifest, limit: int) -> str:
    """Collect external package dependencies."""
    packages = set()
    for f in manifest.files:
        for imp in f.imports:
            if not imp.is_relative and not imp.module.startswith('.'):
                pkg = imp.module.split('.')[0]
                # Filter out likely internal modules
                if not any(mf.path.startswith(pkg) for mf in manifest.files):
                    packages.add(pkg)
    
    sorted_pkgs = sorted(packages)[:limit]
    return '\n'.join(f"- {pkg}" for pkg in sorted_pkgs)


def generate_mermaid_diagram(graph: DependencyGraph, max_nodes: int = 10) -> str:
    """Generate a Mermaid diagram of the dependency graph."""
    # Get top nodes by degree
    nodes = list(graph.nodes)
    if len(nodes) > max_nodes:
        # Take nodes with highest in-degree
        nodes = sorted(nodes, key=lambda n: graph.in_degree(n), reverse=True)[:max_nodes]
    
    nodes_set = set(nodes)
    
    lines = ["graph TD"]
    for from_file in nodes:
        for to_file in graph.edges.get(from_file, set()):
            if to_file in nodes_set:
                # Sanitize names for Mermaid
                from_id = sanitize_mermaid_id(from_file)
                to_id = sanitize_mermaid_id(to_file)
                lines.append(f"  {from_id}[{Path(from_file).name}] --> {to_id}[{Path(to_file).name}]")
    
    return '\n'.join(lines)


def sanitize_mermaid_id(path: str) -> str:
    """Convert file path to valid Mermaid ID."""
    return path.replace('/', '_').replace('.', '_').replace('-', '_')


def guess_directory_purpose(dir_name: str) -> str:
    """Guess the purpose of a directory from its name."""
    name_lower = dir_name.lower()
    
    purposes = {
        'src': 'Source code',
        'lib': 'Library code',
        'core': 'Core functionality',
        'api': 'API endpoints',
        'models': 'Data models',
        'services': 'Business logic',
        'utils': 'Utilities',
        'helpers': 'Helper functions',
        'components': 'UI components',
        'views': 'View templates',
        'controllers': 'Controllers',
        'handlers': 'Request handlers',
        'middleware': 'Middleware',
        'routes': 'Route definitions',
        'config': 'Configuration',
        'tests': 'Test files',
        'test': 'Test files',
        'docs': 'Documentation',
        'scripts': 'Build scripts',
        'tools': 'Development tools',
        'types': 'Type definitions',
        'interfaces': 'Interface definitions',
        'languages': 'Language adapters',
    }
    
    return purposes.get(name_lower, f"{dir_name} module")


def generate_project_purpose(manifest: Manifest) -> str:
    """Generate a project purpose statement."""
    project_name = Path(manifest.meta.root_path).name
    file_count = len(manifest.files)
    
    # Detect likely project type
    languages = set(f.language for f in manifest.files)
    
    if 'typescript' in languages or 'javascript' in languages:
        if any('react' in str(f.imports) for f in manifest.files):
            return f"A React application with {file_count} files."
        return f"A TypeScript/JavaScript project with {file_count} files."
    elif 'python' in languages:
        return f"A Python project with {file_count} files."
    elif 'go' in languages:
        return f"A Go project with {file_count} files."
    
    return f"A codebase with {file_count} files across {len(languages)} languages."


# Export public API
__all__ = [
    'GeneratorConfig',
    'GeneratorResult',
    'generate_agents_md',
    'build_root_context',
    'build_directory_context',
]
