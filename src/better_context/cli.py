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
from .staleness import check_staleness, format_staleness_report, load_staleness_info


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

    # --- focus command ---
    focus_parser = subparsers.add_parser(
        "focus",
        help="Generate context centered on a specific file (ego-centric view)",
    )
    focus_parser.add_argument(
        "file",
        type=str,
        help="Target file to focus on (relative to project root)",
    )
    focus_parser.add_argument(
        "--depth",
        "-d",
        type=int,
        default=3,
        help="Maximum graph distance to explore (default: 3)",
    )
    focus_parser.add_argument(
        "--decay",
        type=float,
        default=0.8,
        help="Score decay factor per hop (default: 0.8)",
    )
    focus_parser.add_argument(
        "--output",
        "-o",
        type=Path,
        default=None,
        help="Output file (default: stdout)",
    )
    focus_parser.add_argument(
        "--json",
        action="store_true",
        help="Output as JSON instead of Markdown",
    )
    focus_parser.add_argument(
        "--no-tests",
        action="store_true",
        help="Exclude test files from output",
    )
    focus_parser.add_argument(
        "--no-types",
        action="store_true",
        help="Exclude type definition files from output",
    )

    # --- verify command ---
    verify_parser = subparsers.add_parser(
        "verify",
        help="Check if generated context is stale and needs regeneration",
    )
    verify_parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        dest="verify_verbose",
        help="Show detailed file changes",
    )
    verify_parser.add_argument(
        "--json",
        action="store_true",
        dest="verify_json",
        help="Output as JSON",
    )

    # --- optimize command ---
    optimize_parser = subparsers.add_parser(
        "optimize",
        help="Select optimal context within token budget",
    )
    optimize_parser.add_argument(
        "--budget",
        "-b",
        type=int,
        default=8000,
        help="Token budget (default: 8000)",
    )
    optimize_parser.add_argument(
        "--keywords",
        "-k",
        type=str,
        nargs="*",
        default=None,
        help="Keywords to boost relevance",
    )
    optimize_parser.add_argument(
        "--task",
        "-t",
        type=str,
        default=None,
        help="Task description for relevance scoring",
    )
    optimize_parser.add_argument(
        "--algorithm",
        "-a",
        choices=["greedy", "knapsack"],
        default="greedy",
        help="Optimization algorithm (default: greedy)",
    )
    optimize_parser.add_argument(
        "--diversity",
        type=float,
        default=0.3,
        help="Diversity penalty factor 0-1 (default: 0.3)",
    )
    optimize_parser.add_argument(
        "--json",
        action="store_true",
        dest="optimize_json",
        help="Output as JSON",
    )
    optimize_parser.add_argument(
        "--output",
        "-o",
        type=Path,
        default=None,
        help="Output file (default: stdout)",
    )

    return parser


def main(argv: Optional[List[str]] = None) -> int:
    """Main entry point for the CLI."""
    parser = create_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return int(exc.code) if isinstance(exc.code, int) else 1

    # Dispatch to command handlers
    command_handlers = {
        "scan": cmd_scan,
        "agents": cmd_agents,
        "all": cmd_all,
        "stats": cmd_stats,
        "graph": cmd_graph,
        "clean": cmd_clean,
        "focus": cmd_focus,
        "verify": cmd_verify,
        "optimize": cmd_optimize,
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


def cmd_focus(args: argparse.Namespace) -> int:
    """Generate context centered on a specific file."""
    root = args.root.resolve()
    target_file = args.file
    
    # Normalize target file path
    if not target_file.startswith(str(root)):
        # Assume relative path
        target_path = Path(target_file)
        if target_path.is_absolute():
            # Make relative to root
            try:
                target_file = str(target_path.relative_to(root))
            except ValueError:
                print(f"[error] File {target_file} is not within project root {root}")
                return 1
    
    # Load manifest
    manifest = load_manifest_or_fail(args)
    if manifest is None:
        return 1
    
    # Check if target file exists in manifest
    target_exists = any(f.path == target_file for f in manifest.files)
    if not target_exists:
        # Try to find similar paths
        similar = [f.path for f in manifest.files if target_file in f.path or f.path.endswith(target_file)]
        if similar:
            print(f"[error] File '{target_file}' not found in manifest.")
            print(f"[hint] Did you mean one of these?")
            for s in similar[:5]:
                print(f"  - {s}")
        else:
            print(f"[error] File '{target_file}' not found in manifest.")
            print(f"[hint] Run 'better-context scan' first to analyze the codebase.")
        return 1
    
    print(f"[focus] Generating context for {target_file}...")
    
    try:
        from .graph import build_graph_from_edges
        from .focus import compute_focus_context, generate_focus_markdown, FocusConfig
        
        # Rebuild graph from manifest
        graph = build_graph_from_edges(
            manifest.graph.edges,
            manifest.graph.nodes,
        )
        
        # Configure focus mode
        config = FocusConfig(
            max_depth=args.depth,
            decay_factor=args.decay,
            include_tests=not args.no_tests,
            include_types=not args.no_types,
        )
        
        # Compute focused context
        context = compute_focus_context(
            target_file,
            graph,
            manifest.graph.centrality,
            config,
        )
        
        if args.json:
            # JSON output
            import json
            output_data = {
                'focal_file': context.focal_file,
                'total_files': context.total_files_in_neighborhood,
                'max_depth': context.max_depth_used,
                'files': [
                    {
                        'path': f.path,
                        'distance': f.distance,
                        'direction': f.direction,
                        'centrality': f.centrality,
                        'score': f.score,
                        'description': f.description,
                    }
                    for f in context.files
                ],
                'dependencies': [f.path for f in context.dependencies],
                'dependents': [f.path for f in context.dependents],
                'related_tests': [f.path for f in context.related_tests],
                'shared_types': [f.path for f in context.shared_types],
            }
            output = json.dumps(output_data, indent=2)
        else:
            # Markdown output
            output = generate_focus_markdown(context, manifest)
        
        if args.output:
            args.output.write_text(output, encoding='utf-8')
            print(f"[focus] Written to {args.output}")
        else:
            print(output)
        
        print(f"[focus] Found {context.total_files_in_neighborhood} files in neighborhood")
        print(f"[focus] {len(context.dependencies)} dependencies, {len(context.dependents)} dependents")
        
        return 0
        
    except Exception as e:
        print(f"[error] Focus analysis failed: {e}")
        if args.verbose:
            import traceback
            traceback.print_exc()
        return 1


def cmd_optimize(args: argparse.Namespace) -> int:
    """Select optimal context within token budget."""
    root = args.root.resolve()
    
    # Load manifest
    manifest = load_manifest_or_fail(args)
    if manifest is None:
        return 1
    
    print(f"[optimize] Selecting optimal context within {args.budget:,} tokens...")
    
    try:
        from .optimizer import optimize_context, format_optimization_result
        
        # Run optimization
        result = optimize_context(
            manifest=manifest,
            centrality=manifest.graph.centrality,
            budget=args.budget,
            keywords=args.keywords,
            task_description=args.task,
            algorithm=args.algorithm,
            diversity_penalty=args.diversity,
        )
        
        if getattr(args, 'optimize_json', False):
            # JSON output
            output = json.dumps(result.to_dict(), indent=2)
        else:
            # Markdown output
            output = format_optimization_result(result)
        
        if args.output:
            args.output.write_text(output, encoding='utf-8')
            print(f"[optimize] Written to {args.output}")
        else:
            print(output)
        
        print(f"\n[optimize] Selected {len(result.selected_chunks)} chunks")
        print(f"[optimize] Used {result.total_tokens:,} of {result.budget:,} tokens ({result.budget_utilization:.1%})")
        print(f"[optimize] Total score: {result.total_score:.4f}")
        
        return 0
        
    except Exception as e:
        print(f"[error] Optimization failed: {e}")
        if args.verbose:
            import traceback
            traceback.print_exc()
        return 1


def cmd_verify(args: argparse.Namespace) -> int:
    """Check if generated context is stale and needs regeneration."""
    root = args.root.resolve()
    
    # Check if staleness info exists
    info = load_staleness_info(root)
    if info is None:
        print("[verify] No staleness info found.")
        print("[hint] Run 'better-context all' first to generate context with staleness tracking.")
        return 1
    
    try:
        result = check_staleness(root)
        
        if getattr(args, 'verify_json', False):
            import json
            output = {
                'is_stale': result.is_stale,
                'source_hash': result.source_hash,
                'previous_hash': result.previous_hash,
                'changed': result.changed,
                'added': result.added,
                'removed': result.removed,
                'total_changes': result.total_changes,
            }
            print(json.dumps(output, indent=2))
        else:
            verbose = getattr(args, 'verify_verbose', False)
            report = format_staleness_report(result, verbose=verbose)
            print(report)
        
        # Return exit code 0 if fresh, 1 if stale
        return 0 if not result.is_stale else 1
        
    except Exception as e:
        print(f"[error] Staleness check failed: {e}")
        if args.verbose:
            import traceback
            traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
