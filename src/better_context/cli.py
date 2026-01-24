"""CLI entry point for better-context."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from collections import Counter
from pathlib import Path
from typing import List, Optional

from .config import load_config
from .manifest import load_manifest, Manifest
from .orchestrator import Orchestrator, generate_context


def create_parser() -> argparse.ArgumentParser:
    """Create and configure the argument parser."""
    parser = argparse.ArgumentParser(
        prog="better-context",
        description="AI Agent Codebase Intelligence CLI - Generate AGENTS.md hierarchies",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
Examples:
  better-context all ./my-project          Scan and generate AGENTS.md
  better-context scan --out manifest.json  Generate only the manifest
  better-context stats                     Show codebase statistics
  better-context graph -f mermaid          Export dependency graph
""",
    )

    parser.add_argument(
        "--version",
        action="version",
        version="%(prog)s 1.0.0",
    )

    parser.add_argument(
        "--root",
        type=Path,
        default=Path("."),
        help="Project root directory (default: current directory)",
    )

    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help="Path to .ctx.json config file",
    )

    parser.add_argument(
        "-v",
        "--verbose",
        action="count",
        default=0,
        help="Increase verbosity (-v, -vv, -vvv)",
    )

    parser.add_argument(
        "--no-color",
        action="store_true",
        help="Disable colored output",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    # --- scan command ---
    scan_parser = subparsers.add_parser("scan", help="Scan codebase and generate manifest")
    scan_parser.add_argument(
        "path",
        nargs="?",
        type=Path,
        default=Path("."),
        help="Path to scan",
    )
    scan_parser.add_argument(
        "--out",
        "-o",
        type=Path,
        default=None,
        help="Manifest output path (default: .better-context/manifest.json)",
    )

    # --- agents command ---
    agents_parser = subparsers.add_parser("agents", help="Generate AGENTS.md files from manifest")
    agents_parser.add_argument(
        "--manifest",
        "-m",
        type=Path,
        default=None,
        help="Path to manifest file",
    )
    agents_parser.add_argument(
        "--depth",
        type=int,
        default=-1,
        help="Max depth for AGENTS.md generation (-1 = unlimited)",
    )

    # --- all command ---
    all_parser = subparsers.add_parser("all", help="Scan and generate AGENTS.md (common workflow)")
    all_parser.add_argument(
        "path",
        nargs="?",
        type=Path,
        default=Path("."),
        help="Path to analyze",
    )

    # --- stats command ---
    stats_parser = subparsers.add_parser("stats", help="Show codebase statistics")
    stats_parser.add_argument(
        "--json",
        action="store_true",
        help="Output as JSON",
    )

    # --- graph command ---
    graph_parser = subparsers.add_parser("graph", help="Export dependency graph")
    graph_parser.add_argument(
        "-f",
        "--format",
        choices=["mermaid", "dot", "json"],
        default="mermaid",
        help="Output format",
    )
    graph_parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=None,
        help="Output file (default: stdout)",
    )

    # --- clean command ---
    clean_parser = subparsers.add_parser("clean", help="Remove generated files")
    clean_parser.add_argument(
        "--cache-only",
        action="store_true",
        help="Only remove cache files, keep AGENTS.md",
    )

    return parser


def main(argv: Optional[List[str]] = None) -> int:
    """Main entry point for the CLI."""
    parser = create_parser()
    args = parser.parse_args(argv)

    # Dispatch to command handlers
    command_handlers = {
        "scan": cmd_scan,
        "agents": cmd_agents,
        "all": cmd_all,
        "stats": cmd_stats,
        "graph": cmd_graph,
        "clean": cmd_clean,
    }

    handler = command_handlers.get(args.command)
    if handler:
        return handler(args)

    parser.print_help()
    return 1


def get_manifest_path(args: argparse.Namespace) -> Path:
    """Get manifest path from args or default location."""
    root = getattr(args, 'root', Path('.'))
    config = load_config(root)
    if hasattr(args, 'manifest') and args.manifest:
        return args.manifest
    return root / config.output_dir / config.manifest_file


def load_manifest_or_fail(args: argparse.Namespace) -> Optional[Manifest]:
    """Load manifest, returning None if not found."""
    manifest_path = get_manifest_path(args)
    if not manifest_path.exists():
        print(f"[error] Manifest not found at {manifest_path}")
        print("[hint] Run 'better-context scan' first to generate the manifest")
        return None
    try:
        return load_manifest(manifest_path)
    except Exception as e:
        print(f"[error] Failed to load manifest: {e}")
        return None


def cmd_scan(args: argparse.Namespace) -> int:
    """Scan codebase and generate manifest."""
    root = (args.path or args.root).resolve()
    print(f"[scan] Scanning {root}...")
    
    try:
        orchestrator = Orchestrator(root)
        
        def progress(phase: str, current: int, total: int) -> None:
            if args.verbose:
                print(f"  [{phase}] {current}/{total}")
        
        orchestrator.set_progress_callback(progress)
        result = orchestrator.analyze()
        
        # Save manifest
        output_path = args.out if args.out else None
        manifest_path = orchestrator.save_manifest(result.manifest, output_path)
        
        print(f"[scan] Found {result.file_count} files")
        print(f"[scan] Detected {len(result.cycles)} cycles")
        print(f"[scan] Manifest saved to {manifest_path}")
        return 0
        
    except Exception as e:
        print(f"[error] Scan failed: {e}")
        if args.verbose:
            import traceback
            traceback.print_exc()
        return 1


def cmd_agents(args: argparse.Namespace) -> int:
    """Generate AGENTS.md files from manifest."""
    root = args.root.resolve()
    
    # Load manifest
    manifest = load_manifest_or_fail(args)
    if manifest is None:
        return 1
    
    print("[agents] Generating AGENTS.md files...")
    
    try:
        orchestrator = Orchestrator(root)
        
        # Rebuild graph from manifest
        from .graph import build_graph_from_edges
        graph = build_graph_from_edges(
            manifest.graph.edges,
            manifest.graph.nodes,
        )
        
        result = orchestrator.generate(
            manifest,
            graph,
            max_depth=args.depth,
        )
        
        print(f"[agents] Generated {len(result.files_written)} AGENTS.md files")
        print(f"[agents] Total lines: {result.total_lines}")
        return 0
        
    except Exception as e:
        print(f"[error] Generation failed: {e}")
        if args.verbose:
            import traceback
            traceback.print_exc()
        return 1


def cmd_all(args: argparse.Namespace) -> int:
    """Scan and generate AGENTS.md (common workflow)."""
    root = (args.path or args.root).resolve()
    print(f"[all] Analyzing {root}...")
    
    try:
        result = generate_context(root)
        
        print(f"[all] Analyzed {result.analysis.file_count} files")
        print(f"[all] Generated {len(result.generation.files_written)} AGENTS.md files")
        print(f"[all] Completed in {result.total_time_ms}ms")
        
        if result.analysis.has_cycles:
            print(f"[warning] Found {len(result.analysis.cycles)} circular dependencies")
        
        return 0
        
    except Exception as e:
        print(f"[error] Analysis failed: {e}")
        if args.verbose:
            import traceback
            traceback.print_exc()
        return 1


def cmd_stats(args: argparse.Namespace) -> int:
    """Show codebase statistics."""
    manifest = load_manifest_or_fail(args)
    if manifest is None:
        return 1
    
    # Compute statistics
    language_counts = Counter(f.language for f in manifest.files if f.language)
    total_chunks = sum(len(f.chunks) for f in manifest.files)
    total_imports = sum(len(f.imports) for f in manifest.files)
    total_exports = sum(len(f.exports) for f in manifest.files)
    total_bytes = sum(f.size_bytes for f in manifest.files)
    
    # Get top files by centrality
    top_files = sorted(
        manifest.graph.centrality.items(),
        key=lambda x: x[1],
        reverse=True
    )[:5]
    
    stats = {
        'files': len(manifest.files),
        'total_bytes': total_bytes,
        'chunks': total_chunks,
        'imports': total_imports,
        'exports': total_exports,
        'dependencies': len(manifest.graph.edges),
        'cycles': len(manifest.graph.cycles),
        'layers': len(manifest.graph.layers),
        'languages': dict(language_counts),
        'top_files': [{'path': p, 'centrality': round(c, 4)} for p, c in top_files],
        'generated_at': manifest.meta.generated_at,
        'version': manifest.meta.version,
    }
    
    if args.json:
        print(json.dumps(stats, indent=2))
    else:
        print(f"\n📊 Codebase Statistics")
        print(f"{'=' * 40}")
        print(f"Files:        {stats['files']}")
        print(f"Total Size:   {stats['total_bytes'] / 1024:.1f} KB")
        print(f"Definitions:  {stats['chunks']}")
        print(f"Imports:      {stats['imports']}")
        print(f"Exports:      {stats['exports']}")
        print(f"Dependencies: {stats['dependencies']}")
        print(f"Cycles:       {stats['cycles']}")
        print(f"Layers:       {stats['layers']}")
        print()
        print("📝 Languages:")
        for lang, count in sorted(language_counts.items(), key=lambda x: -x[1]):
            print(f"  {lang}: {count}")
        print()
        print("🔑 Top Files (by centrality):")
        for entry in stats['top_files']:
            print(f"  {entry['path']} ({entry['centrality']:.4f})")
        print()
        print(f"Generated: {stats['generated_at']}")
    
    return 0


def cmd_graph(args: argparse.Namespace) -> int:
    """Export dependency graph."""
    manifest = load_manifest_or_fail(args)
    if manifest is None:
        return 1
    
    output = export_graph(manifest, args.format)
    
    if args.output:
        args.output.write_text(output)
        print(f"[graph] Written to {args.output}")
    else:
        print(output)
    
    return 0


def export_graph(manifest: Manifest, fmt: str) -> str:
    """Export graph in the specified format."""
    nodes = manifest.graph.nodes
    edges = manifest.graph.edges
    centrality = manifest.graph.centrality
    
    if fmt == 'json':
        return json.dumps({
            'nodes': nodes,
            'edges': [{'from': e[0], 'to': e[1]} for e in edges],
            'centrality': centrality,
            'cycles': manifest.graph.cycles,
        }, indent=2)
    
    elif fmt == 'dot':
        lines = ['digraph Dependencies {']
        lines.append('  rankdir=LR;')
        lines.append('  node [shape=box];')
        
        # Add nodes with labels
        for node in nodes:
            score = centrality.get(node, 0)
            label = Path(node).name
            lines.append(f'  "{node}" [label="{label}\\n{score:.3f}"];')
        
        # Add edges
        for from_file, to_file in edges:
            lines.append(f'  "{from_file}" -> "{to_file}";')
        
        lines.append('}')
        return '\n'.join(lines)
    
    else:  # mermaid
        lines = ['graph TD']
        
        # Create node ID mapping
        node_ids = {node: f'n{i}' for i, node in enumerate(nodes)}
        
        # Add edges with node definitions
        for from_file, to_file in edges:
            from_id = node_ids[from_file]
            to_id = node_ids[to_file]
            from_label = Path(from_file).name
            to_label = Path(to_file).name
            lines.append(f'  {from_id}[{from_label}] --> {to_id}[{to_label}]')
        
        # Add orphan nodes (no edges)
        connected = set()
        for from_file, to_file in edges:
            connected.add(from_file)
            connected.add(to_file)
        
        for node in nodes:
            if node not in connected:
                node_id = node_ids[node]
                label = Path(node).name
                lines.append(f'  {node_id}[{label}]')
        
        return '\n'.join(lines)


def cmd_clean(args: argparse.Namespace) -> int:
    """Remove generated files."""
    root = args.root.resolve()
    config = load_config(root)
    removed: List[str] = []
    
    # Remove .better-context directory
    bc_dir = root / config.output_dir
    if bc_dir.exists():
        if args.cache_only:
            # Only remove cache files
            for cache_file in bc_dir.glob('*.cache'):
                cache_file.unlink()
                removed.append(str(cache_file.relative_to(root)))
        else:
            shutil.rmtree(bc_dir)
            removed.append(config.output_dir)
    
    # Remove generated AGENTS.md files (unless cache-only)
    if not args.cache_only:
        for agents_md in root.rglob('AGENTS.md'):
            if is_generated_agents_md(agents_md):
                agents_md.unlink()
                removed.append(str(agents_md.relative_to(root)))
    
    if removed:
        print(f"[clean] Removed {len(removed)} items:")
        for item in removed[:10]:
            print(f"  - {item}")
        if len(removed) > 10:
            print(f"  ... and {len(removed) - 10} more")
    else:
        print("[clean] Nothing to clean")
    
    return 0


def is_generated_agents_md(path: Path) -> bool:
    """Check if an AGENTS.md file was generated by better-context.
    
    Generated files contain a specific marker comment.
    """
    try:
        content = path.read_text(encoding='utf-8')
        return 'Auto-generated context for AI agents' in content
    except Exception:
        return False


if __name__ == "__main__":
    sys.exit(main())
