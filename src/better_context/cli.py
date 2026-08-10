"""CLI entry point for better-context."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from collections import Counter
from importlib.metadata import version as get_version
from pathlib import Path
from typing import Any, List, Optional

from .config import load_config

def _get_version() -> str:
    """Get package version from metadata."""
    try:
        return get_version("better-context-unity")
    except Exception:
        return "1.1.0"  # Fallback for editable installs
from .manifest import load_manifest, Manifest
from .orchestrator import Orchestrator, generate_context
from .staleness import (
    check_staleness,
    format_staleness_report,
    load_staleness_info,
    save_staleness_info,
)
from .primitives.overview import analyze_overview
from .primitives.tree import analyze_tree
from .primitives.scripts import analyze_scripts
from .primitives.entries import analyze_entry_points
from .primitives.file_info import analyze_file
from .primitives.deps import get_file_dependencies
from .primitives.formatters import (
    format_json,
    format_tree_human,
    format_tree_markdown,
    format_overview_human,
    format_overview_markdown,
    format_scripts_human,
    format_scripts_markdown,
    format_entries_human,
    format_entries_markdown,
    format_file_info_human,
    format_file_info_markdown,
    format_deps_human,
    format_deps_markdown,
)
from .graph import build_dependency_graph, build_graph_from_edges
from .scanner import walk_repository, FileInventory
from .agents_map import (
    SUMMARY_FILE,
    generate_agents_map,
    load_summaries,
    normalize_summary_path,
    parse_summary_assignment,
    remove_managed_map,
    save_summaries,
    summary_targets,
)


def add_common_primitive_args(parser: argparse.ArgumentParser) -> None:
    """Add common arguments for primitive commands."""
    # NOOP for now, args added manually
    pass


def create_parser() -> argparse.ArgumentParser:
    """Create and configure the argument parser."""
    parser = argparse.ArgumentParser(
        prog="better-context-unity",
        description="Local Unity/C# codebase intelligence and safe hierarchical AGENTS.md maps.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
Examples:
  better-context-unity agents              Refresh Unity AGENTS.md maps
  better-context-unity scan                Generate only the manifest
  better-context-unity stats               Show codebase statistics

Agent Workflow:
  1. better-context-unity agents     # Index and refresh project maps
  2. better-context-unity overview   # Get Unity project metadata
  3. better-context-unity focus      # Inspect a known C# file neighborhood
""",
    )

    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {_get_version()}",
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

    # --- primitives command ---
    primitives_parser = subparsers.add_parser("primitives", help="Manage and inspect primitives")
    primitives_parser.add_argument("primitive_command", choices=["list", "show"], help="Command to run")
    primitives_parser.add_argument("--type", choices=["project", "file", "entry", "script"], help="Filter by primitive type")
    primitives_parser.add_argument("--id", help="Primitive ID for show command")

    # --- scan command ---
    scan_parser = subparsers.add_parser("scan", help="Index the codebase to enable deep analysis. Run this first!")
    scan_parser.add_argument(
        "path",
        nargs="?",
        type=Path,
        default=None,
        help="Path to scan",
    )
    scan_parser.add_argument(
        "--out",
        "-o",
        type=Path,
        default=None,
        help="Manifest output path (default: .better-context/manifest.json)",
    )

    agents_parser = subparsers.add_parser(
        "agents",
        help="Index the project and safely refresh hierarchical AGENTS.md maps",
    )
    agents_parser.add_argument(
        "--max-depth",
        type=int,
        default=-1,
        help="Maximum generated folder depth (-1 = unlimited)",
    )
    agents_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report maps that would change without writing them",
    )
    agents_parser.add_argument(
        "--summary",
        action="append",
        default=[],
        metavar="PATH=TEXT",
        help="Add or replace an optional persisted file/folder summary; repeatable",
    )
    agents_parser.add_argument(
        "--remove-summary",
        action="append",
        default=[],
        metavar="PATH",
        help="Remove a persisted summary before refreshing maps; repeatable",
    )

    # --- overview command ---
    overview_parser = subparsers.add_parser("overview", help="Extract project metadata (language, frameworks, etc.)")
    overview_parser.add_argument("--format", choices=["json", "human", "markdown"], default="json")
    overview_parser.add_argument("--timing", action="store_true", help="Show execution time")

    # --- tree command ---
    tree_parser = subparsers.add_parser("tree", help="Visualize file hierarchy. Use --depth to limit noise.")
    tree_parser.add_argument("--format", choices=["json", "human", "markdown"], default="json")
    tree_parser.add_argument("--depth", type=int, default=2, help="Max depth (default: 2)")

    # --- scripts command ---
    scripts_parser = subparsers.add_parser("scripts", help="Extract runnable scripts from package files")
    scripts_parser.add_argument("--format", choices=["json", "human", "markdown"], default="json")

    # --- entries command ---
    entries_parser = subparsers.add_parser("entries", help="Identify application entry points (CLI, main, server)")
    entries_parser.add_argument("--format", choices=["json", "human", "markdown"], default="json")

    # --- file command ---
    file_parser = subparsers.add_parser("file", help="Get metadata and structure for a specific file")
    file_parser.add_argument("path", help="Path to file")
    file_parser.add_argument("--format", choices=["json", "human", "markdown"], default="json")

    # --- deps command ---
    deps_parser = subparsers.add_parser("deps", help="Get direct dependencies and dependents for a file")
    deps_parser.add_argument("path", help="Path to file")
    deps_parser.add_argument("--format", choices=["json", "human", "markdown"], default="json")

    # --- stats command ---
    stats_parser = subparsers.add_parser("stats", help="Calculate metrics and find important files (PageRank)")
    stats_parser.add_argument(
        "--json",
        action="store_true",
        help="Output as JSON",
    )

    # --- graph command ---
    graph_parser = subparsers.add_parser("graph", help="Export dependency or function-call graph")
    graph_parser.add_argument(
        "--kind",
        choices=["dependency", "call"],
        default="dependency",
        help="Graph kind (default: dependency)",
    )
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
    clean_parser = subparsers.add_parser("clean", help="Remove generated files and caches")
    clean_parser.add_argument(
        "--cache-only",
        action="store_true",
        help="Only remove cache files, keep AGENTS.md",
    )

    # --- focus command ---
    focus_parser = subparsers.add_parser(
        "focus",
        help="Generate deep context for a specific file (dependencies, tests)",
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
        help="Verify if the cached manifest matches files on disk",
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
        help="Select relevant code chunks within a token limit",
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
        # "all": cmd_all,       # Deprecated
        "stats": cmd_stats,
        "graph": cmd_graph,
        "clean": cmd_clean,
        "focus": cmd_focus,
        "verify": cmd_verify,
        "optimize": cmd_optimize,
        # "primitives": cmd_primitives,
        "overview": cmd_overview,
        "tree": cmd_tree,
        "scripts": cmd_scripts,
        "entries": cmd_entries,
        "file": cmd_file,
        "deps": cmd_deps,
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
        return Path(args.manifest)
    return root / config.output_dir / config.manifest_file


def load_manifest_or_fail(args: argparse.Namespace) -> Optional[Manifest]:
    """Load manifest, returning None if not found."""
    manifest_path = get_manifest_path(args)
    if not manifest_path.exists():
        print(f"[error] Manifest not found at {manifest_path}")
        print("[hint] Run 'better-context-unity scan' first to generate the manifest")
        return None
    try:
        return load_manifest(manifest_path)
    except Exception as e:
        print(f"[error] Failed to load manifest: {e}")
        return None


def cmd_scan(args: argparse.Namespace) -> int:
    """Scan codebase and generate manifest."""
    root = (args.path if args.path is not None else args.root).resolve()
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
        save_staleness_info(
            root,
            {entry.path: entry.content_hash for entry in result.inventory.files if not entry.path.endswith("AGENTS.md")},
            result.manifest.meta.generated_at,
            orchestrator.config.output_dir,
        )
        
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
    """Index a project and create marker-managed AGENTS.md maps."""
    root = args.root.resolve()
    print(f"[agents] Analyzing {root}...")
    try:
        stored_summaries = load_summaries(root)
        updates: dict[str, str] = {}
        for assignment in args.summary:
            path, summary = parse_summary_assignment(assignment)
            updates[path] = summary
        removals = {normalize_summary_path(path) for path in args.remove_summary}
        overlap = sorted(updates.keys() & removals)
        if overlap:
            raise ValueError(f"Cannot add and remove the same summary: {overlap[0] or '.'}")

        orchestrator = Orchestrator(root)
        analysis = orchestrator.analyze()
        targets = summary_targets(analysis.manifest, root, args.max_depth)
        invalid_updates = sorted(path for path in updates if path not in targets)
        invalid_removals = sorted(
            path for path in removals if path not in targets and path not in stored_summaries
        )
        invalid = invalid_updates or invalid_removals
        if invalid:
            target = invalid[0] or "."
            raise ValueError(f"Summary target is not present in generated maps: {target}")

        summaries = dict(stored_summaries)
        for path in removals:
            summaries.pop(path, None)
        summaries.update(updates)
        summaries_changed = summaries != stored_summaries
        if summaries_changed:
            action = "Would store" if args.dry_run else "Stored"
            print(f"[agents] {action} {len(summaries)} optional summary(s) in {SUMMARY_FILE}")
            if not args.dry_run:
                save_summaries(root, summaries)
                orchestrator = Orchestrator(root)
                analysis = orchestrator.analyze()

        if not args.dry_run:
            manifest_path = orchestrator.save_manifest(analysis.manifest)
            print(f"[agents] Manifest saved to {manifest_path}")
        result = generate_agents_map(
            analysis.manifest,
            analysis.graph,
            root,
            max_depth=args.max_depth,
            dry_run=args.dry_run,
            summaries=summaries,
        )
        action = "would update" if args.dry_run else "updated"
        print(
            f"[agents] {action} {len(result.files_written)} map(s); "
            f"{len(result.unchanged)} unchanged; "
            f"{len(result.files_removed)} stale managed map(s) removed"
        )
        for path in result.files_written:
            print(f"  - {path}")
        for path in result.files_removed:
            print(f"  - removed managed block: {path}")
        for error in result.errors:
            print(f"[error] {error}")
        if not args.dry_run and not result.errors:
            save_staleness_info(
                root,
                {
                    entry.path: entry.content_hash
                    for entry in analysis.inventory.files
                    if not entry.path.endswith("AGENTS.md")
                },
                analysis.manifest.meta.generated_at,
                orchestrator.config.output_dir,
            )
        return 1 if result.errors else 0
    except Exception as exc:
        print(f"[error] AGENTS.md generation failed: {exc}")
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
    
    stats: dict[str, Any] = {
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
    
    output = export_graph(manifest, args.format, args.kind)
    
    if args.output:
        args.output.write_text(output)
        print(f"[graph] Written to {args.output}")
    else:
        print(output)
    
    return 0


def export_graph(manifest: Manifest, fmt: str, kind: str = "dependency") -> str:
    """Export graph in the specified format."""
    if kind == "call":
        return _export_call_graph(manifest, fmt)
    nodes = manifest.graph.nodes
    edges = manifest.graph.edges
    centrality = manifest.graph.centrality
    
    if fmt == 'json':
        return json.dumps({
            'nodes': nodes,
            'edges': [{'from': e[0], 'to': e[1]} for e in edges],
            'centrality': centrality,
            'cycles': manifest.graph.cycles,
            'edge_details': manifest.graph.edge_details,
            'architecture': manifest.graph.architecture,
            'coupling': manifest.graph.coupling,
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

    lines = ['graph TD']
    node_ids = {node: f'n{i}' for i, node in enumerate(nodes)}
    for from_file, to_file in edges:
        from_id = node_ids[from_file]
        to_id = node_ids[to_file]
        from_label = Path(from_file).name
        to_label = Path(to_file).name
        lines.append(f'  {from_id}[{from_label}] --> {to_id}[{to_label}]')
    connected = {path for edge in edges for path in edge}
    for node in nodes:
        if node not in connected:
            node_id = node_ids[node]
            label = Path(node).name
            lines.append(f'  {node_id}[{label}]')
    return '\n'.join(lines)


def _export_call_graph(manifest: Manifest, fmt: str) -> str:
    calls = manifest.graph.call_graph
    nodes: dict[str, str] = {}
    for call in calls:
        nodes[call.get("callerId", "")] = call.get("callerName", "")
        nodes[call.get("calleeId", "")] = call.get("calleeName", "")
    nodes.pop("", None)
    if fmt == "json":
        return json.dumps({"nodes": nodes, "calls": calls}, indent=2)
    if fmt == "dot":
        lines = ["digraph Calls {", "  rankdir=LR;", "  node [shape=box];"]
        for node_id, label in nodes.items():
            safe_id = node_id.replace('"', '\\"')
            safe_label = label.replace('"', '\\"')
            lines.append(f'  "{safe_id}" [label="{safe_label}"];')
        for call in calls:
            caller = str(call.get("callerId", "")).replace('"', '\\"')
            callee = str(call.get("calleeId", "")).replace('"', '\\"')
            kind = call.get("kind", "call")
            lines.append(f'  "{caller}" -> "{callee}" [label="{kind}"];')
        lines.append("}")
        return "\n".join(lines)
    node_ids = {node: f"c{index}" for index, node in enumerate(nodes)}
    lines = ["flowchart TD"]
    for node, local_id in node_ids.items():
        label = nodes[node].replace('"', "'")
        lines.append(f'  {local_id}["{label}"]')
    for call in calls:
        caller = node_ids.get(call.get("callerId"))
        callee = node_ids.get(call.get("calleeId"))
        if caller and callee:
            lines.append(f"  {caller} -->|{call.get('kind', 'call')}| {callee}")
    return "\n".join(lines)


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
    
    # Remove only our managed block from AGENTS.md files (unless cache-only)
    if not args.cache_only:
        for agents_md in root.rglob('AGENTS.md'):
            if remove_managed_map(agents_md):
                removed.append(str(agents_md.relative_to(root)))
            elif is_generated_agents_md(agents_md):
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
            print("[hint] Run 'better-context-unity scan' first to analyze the codebase.")
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
        print("[hint] Run 'better-context-unity agents' first to generate tracked context.")
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


def cmd_overview(args: argparse.Namespace) -> int:
    """Get project overview."""
    root = args.root.resolve()
    
    if args.timing:
        from .primitives.base import timed
        result, elapsed = timed(analyze_overview)(root)
        print(f"Time: {elapsed:.2f}ms", file=sys.stderr)
    else:
        result = analyze_overview(root)
    
    if args.format == "human":
        print(format_overview_human(result))
    elif args.format == "markdown":
        print(format_overview_markdown(result))
    else:
        print(format_json(result))
    return 0


def cmd_tree(args: argparse.Namespace) -> int:
    """Show directory structure."""
    root = args.root.resolve()
    result = analyze_tree(root, max_depth=args.depth)
        
    if args.format == "human":
        print(format_tree_human(result))
    elif args.format == "markdown":
        print(format_tree_markdown(result))
    else:
        print(format_json(result))
    return 0


def cmd_scripts(args: argparse.Namespace) -> int:
    """List available scripts."""
    root = args.root.resolve()
    result = analyze_scripts(root)
        
    if args.format == "human":
        print(format_scripts_human(result))
    elif args.format == "markdown":
        print(format_scripts_markdown(result))
    else:
        print(format_json(result))
    return 0


def cmd_entries(args: argparse.Namespace) -> int:
    """Find entry points."""
    root = args.root.resolve()
    result = analyze_entry_points(root)
        
    if args.format == "human":
        print(format_entries_human(result))
    elif args.format == "markdown":
        print(format_entries_markdown(result))
    else:
        print(format_json(result))
    return 0


def cmd_file(args: argparse.Namespace) -> int:
    """Get file metadata."""
    root = args.root.resolve()
    
    # Handle path resolution manually to ensure correct relative path logic
    path_arg = Path(args.path)
    if not path_arg.is_absolute():
        path = root / path_arg
    else:
        path = path_arg
        
    try:
        result = analyze_file(path, root)
    except Exception as e:
        print(f"Error analyzing file: {e}", file=sys.stderr)
        return 1
        
    if args.format == "human":
        print(format_file_info_human(result))
    elif args.format == "markdown":
        print(format_file_info_markdown(result))
    else:
        print(format_json(result))
    return 0


def cmd_deps(args: argparse.Namespace) -> int:
    """Get file dependencies."""
    root = args.root.resolve()
    
    # Check if manifest exists
    manifest = load_manifest_or_fail(args)
    
    if manifest:
        # Rebuild graph from manifest
        graph = build_graph_from_edges(
            manifest.graph.edges,
            manifest.graph.nodes,
        )
    else:
        # Fallback logic not implemented fully, just error for now as per test expectation?
        # Test expects "No dependency graph available"
        print(
            "Error: No dependency graph available. "
            "Run 'better-context-unity scan' first.",
            file=sys.stderr,
        )
        return 1
        
    result = get_file_dependencies(args.path, graph)
        
    if args.format == "human":
        print(format_deps_human(result))
    elif args.format == "markdown":
        print(format_deps_markdown(result))
    else:
        print(format_json(result))
    return 0

if __name__ == "__main__":
    sys.exit(main())
