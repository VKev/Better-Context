
"""CLI entry point for better-context."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from collections import Counter
from pathlib import Path, PurePosixPath
from typing import Any, List, Optional

from .config import load_config
from .manifest import MANIFEST_VERSION, Manifest, generator_version, load_manifest
from .orchestrator import Orchestrator, generate_context
from .staleness import (
    check_staleness,
    collect_current_hashes,
    compute_source_hash,
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


def _get_version() -> str:
    """Get package version from metadata."""
    return str(generator_version())


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

    # --- unity command ---
    unity_parser = subparsers.add_parser(
        "unity",
        help="Query Unity scenes, prefabs, ScriptableObjects, events, and animators",
    )
    unity_subparsers = unity_parser.add_subparsers(dest="unity_command", required=True)

    unity_list_parser = unity_subparsers.add_parser(
        "list",
        help="List Unity runtime assets from the saved manifest",
    )
    unity_list_parser.add_argument("--kind", help="Filter by asset kind")
    unity_list_parser.add_argument(
        "--limit", type=int, default=50, help="Maximum assets (default: 50)"
    )
    unity_list_parser.add_argument(
        "--format", choices=["json", "human", "markdown"], default="json"
    )

    unity_show_parser = unity_subparsers.add_parser(
        "show",
        help="Show full runtime data for one project-relative Unity asset",
    )
    unity_show_parser.add_argument("path", help="Project-relative Unity asset path")
    unity_show_parser.add_argument(
        "--depth",
        type=int,
        default=2,
        help="Maximum GameObject hierarchy depth (-1 = unlimited; default: 2)",
    )
    unity_show_parser.add_argument(
        "--format", choices=["json", "human", "markdown"], default="json"
    )

    unity_bindings_parser = unity_subparsers.add_parser(
        "bindings",
        help="List verified and unresolved persistent UnityEvent bindings",
    )
    unity_bindings_parser.add_argument("--asset", help="Filter by exact project-relative asset")
    unity_bindings_parser.add_argument("--type", help="Filter by exact target type")
    unity_bindings_parser.add_argument("--method", help="Filter by exact target method")
    unity_bindings_parser.add_argument(
        "--format", choices=["json", "human", "markdown"], default="json"
    )

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
        "unity": cmd_unity,
    }

    handler = command_handlers.get(args.command)
    if handler:
        return handler(args)

    parser.print_help()
    return 1


def get_manifest_path(args: argparse.Namespace) -> Path:
    """Get manifest path from args or default location."""
    root = Path(getattr(args, 'root', Path('.')))
    config = load_config(root, getattr(args, "config", None))
    if hasattr(args, 'manifest') and args.manifest:
        return Path(args.manifest)
    return Path(root, str(config.output_dir), str(config.manifest_file))


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


def _load_fresh_unity_manifest(args: argparse.Namespace) -> Optional[Manifest]:
    """Load the Unity runtime manifest only when it matches the current project."""
    root = args.root.resolve()
    config = load_config(root, getattr(args, "config", None))
    manifest_path = root / config.output_dir / config.manifest_file
    if not manifest_path.exists():
        print(f"[error] Manifest not found at {manifest_path}")
        print("[hint] Run 'better-context-unity agents' to generate Unity runtime data.")
        return None

    try:
        manifest = load_manifest(manifest_path)
    except Exception as exc:
        print(f"[error] Failed to load manifest: {exc}")
        print("[hint] Run 'better-context-unity agents' to rebuild it.")
        return None

    if manifest.meta.version != MANIFEST_VERSION:
        print(
            "[error] Unity runtime manifest schema is outdated: "
            f"expected {MANIFEST_VERSION}, got {manifest.meta.version or 'unknown'}."
        )
        print("[hint] Run 'better-context-unity agents' to rebuild it.")
        return None

    staleness_info = load_staleness_info(root, config.output_dir)
    if staleness_info is None:
        print("[error] Manifest freshness cannot be verified (staleness data is missing).")
        print("[hint] Run 'better-context-unity agents' to rebuild it.")
        return None

    if manifest.meta.generated_at != staleness_info.generated_at:
        print("[error] Manifest and freshness data were generated by different analyses.")
        print("[hint] Run 'better-context-unity agents' to rebuild them together.")
        return None

    effective_config_hash = hashlib.sha256(str(vars(config)).encode()).hexdigest()[:16]
    if manifest.meta.config_hash != effective_config_hash:
        print("[error] Unity runtime manifest was generated with different configuration.")
        print("[hint] Run 'better-context-unity agents' with the current configuration.")
        return None

    try:
        current_hash = compute_source_hash(
            collect_current_hashes(root, getattr(args, "config", None))
        )
    except Exception as exc:
        print(f"[error] Failed to verify manifest freshness: {exc}")
        return None
    if current_hash != staleness_info.source_hash:
        print("[error] Unity runtime manifest is stale; project files changed after analysis.")
        print("[hint] Run 'better-context-unity agents' to refresh it.")
        return None

    if not isinstance(manifest.project.get("unity_runtime"), dict):
        print("[error] Manifest does not contain Unity runtime intelligence.")
        print("[hint] Run 'better-context-unity agents' with Better Context Unity 1.3.0 or newer.")
        return None
    return manifest


def _normalize_unity_path(value: str) -> str:
    """Return a safe, normalized project-relative manifest path."""
    normalized = value.strip().replace("\\", "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    path = PurePosixPath(normalized)
    has_drive_prefix = bool(path.parts and ":" in path.parts[0])
    if not normalized or path.is_absolute() or ".." in path.parts or has_drive_prefix:
        raise ValueError("Unity asset path must be project-relative and cannot contain '..'")
    return path.as_posix()


def _compact_unity_asset(value: dict[str, Any], default_path: str = "") -> dict[str, Any]:
    """Fill compact display fields from a full per-file runtime record."""
    asset = dict(value)
    asset.setdefault("path", default_path)
    objects = asset.get("objects", [])
    if not isinstance(objects, list):
        objects = []
    script_types: set[str] = set()
    object_by_id: dict[str, dict[str, Any]] = {}
    for obj in objects:
        if not isinstance(obj, dict):
            continue
        object_by_id[str(obj.get("file_id", ""))] = obj
        components = obj.get("components", [])
        if not isinstance(components, list):
            continue
        for component in components:
            if not isinstance(component, dict):
                continue
            script = component.get("script", {})
            if isinstance(script, dict):
                name = script.get("qualified_name") or script.get("type")
                if name:
                    script_types.add(str(name))

    root_values = asset.get("root_objects", asset.get("roots", []))
    root_objects = []
    if isinstance(root_values, list):
        for root in root_values:
            if isinstance(root, dict):
                root_objects.append(root.get("path") or root.get("name") or root.get("file_id"))
            else:
                obj = object_by_id.get(str(root), {})
                root_objects.append(obj.get("path") or obj.get("name") or root)
    events = asset.get("event_bindings", asset.get("unity_events", []))
    event_count = len(events) if isinstance(events, list) else 0
    animator = asset.get("animator", {})
    states = animator.get("states", []) if isinstance(animator, dict) else []

    asset.setdefault("object_count", len(objects))
    asset.setdefault(
        "component_count",
        sum(
            len(obj.get("components", []))
            for obj in objects
            if isinstance(obj, dict) and isinstance(obj.get("components", []), list)
        ),
    )
    asset.setdefault("script_types", sorted(script_types))
    asset.setdefault("root_objects", [str(value) for value in root_objects if value])
    asset.setdefault("event_count", event_count)
    asset.setdefault("animator_state_count", len(states) if isinstance(states, list) else 0)
    asset.setdefault("signal_score", asset.get("high_signal", 0))
    return asset



def _unity_assets(manifest: Manifest) -> list[dict[str, Any]]:
    """Read compact assets while accepting list and path-keyed manifest forms."""
    runtime = manifest.project.get("unity_runtime", {})
    raw_assets = runtime.get("assets", []) if isinstance(runtime, dict) else []
    assets: list[dict[str, Any]] = []
    if isinstance(raw_assets, dict):
        for path, value in raw_assets.items():
            if not isinstance(value, dict):
                continue
            assets.append(_compact_unity_asset(value, str(path)))
    elif isinstance(raw_assets, list):
        assets.extend(
            _compact_unity_asset(value) for value in raw_assets if isinstance(value, dict)
        )

    if not assets:
        for entry in manifest.files:
            value = entry.metadata.get("unity_runtime")
            if isinstance(value, dict):
                assets.append(_compact_unity_asset(value, entry.path))

    deduplicated: dict[str, dict[str, Any]] = {}
    for asset in assets:
        path = str(asset.get("path", "")).replace("\\", "/")
        if path:
            asset["path"] = path
            deduplicated[path.casefold()] = asset
    return sorted(deduplicated.values(), key=lambda asset: str(asset.get("path", "")).casefold())


def _normalize_unity_binding(value: dict[str, Any], default_asset: str = "") -> dict[str, Any]:
    binding = dict(value)
    binding.setdefault("asset", default_asset)
    binding.setdefault("owner_object", binding.get("owner_path", ""))
    binding.setdefault("status", binding.get("confidence", "unresolved"))
    return binding


def _unity_bindings(manifest: Manifest) -> list[dict[str, Any]]:
    """Read root bindings, falling back to per-asset runtime data."""
    runtime = manifest.project.get("unity_runtime", {})
    raw_bindings = runtime.get("event_bindings", []) if isinstance(runtime, dict) else []
    bindings = (
        [_normalize_unity_binding(value) for value in raw_bindings if isinstance(value, dict)]
        if isinstance(raw_bindings, list)
        else []
    )
    if bindings:
        return bindings

    for entry in manifest.files:
        file_runtime = entry.metadata.get("unity_runtime")
        if not isinstance(file_runtime, dict):
            continue
        file_bindings = file_runtime.get(
            "event_bindings", file_runtime.get("unity_events", [])
        )
        if not isinstance(file_bindings, list):
            continue
        for value in file_bindings:
            if not isinstance(value, dict):
                continue
            bindings.append(_normalize_unity_binding(value, entry.path))
    return bindings


def _unity_object_depth(value: dict[str, Any]) -> int:
    explicit = value.get("depth")
    if isinstance(explicit, int) and not isinstance(explicit, bool):
        return explicit
    object_path = value.get("path") or value.get("object_path")
    if isinstance(object_path, str):
        return max(0, len([part for part in object_path.split("/") if part]) - 1)
    return 0


def _trim_unity_children(value: dict[str, Any], remaining_depth: int) -> dict[str, Any]:
    trimmed = dict(value)
    children = value.get("children")
    if not isinstance(children, list):
        return trimmed
    if remaining_depth <= 0:
        trimmed["children"] = []
        return trimmed
    trimmed["children"] = [
        _trim_unity_children(child, remaining_depth - 1)
        if isinstance(child, dict)
        else child
        for child in children
    ]
    return trimmed


def _trim_unity_depth(runtime: dict[str, Any], depth: int) -> dict[str, Any]:
    """Limit object hierarchy output without modifying manifest data."""
    result = dict(runtime)
    objects = runtime.get("objects")
    if depth < 0:
        return result
    if isinstance(objects, list):
        result["objects"] = [
            _trim_unity_children(value, depth - _unity_object_depth(value))
            if isinstance(value, dict)
            else value
            for value in objects
            if not isinstance(value, dict) or _unity_object_depth(value) <= depth
        ]
    model = runtime.get("model")
    if isinstance(model, dict):
        trimmed_model = dict(model)
        roots = model.get("root_nodes")
        if isinstance(roots, list):
            trimmed_model["root_nodes"] = [
                _trim_unity_children(value, depth)
                if isinstance(value, dict)
                else value
                for value in roots
            ]
        result["model"] = trimmed_model
    return result


def _unity_cell(value: Any) -> str:
    if value is None or value == "":
        return "—"
    if isinstance(value, list):
        return ", ".join(str(item) for item in value) if value else "—"
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return str(value)


def _format_unity_assets(assets: list[dict[str, Any]], fmt: str, total: int) -> str:
    if fmt == "json":
        return json.dumps(
            {"assets": assets, "shown": len(assets), "total": total},
            indent=2,
            ensure_ascii=False,
        )
    if fmt == "markdown":
        lines = [
            "# Unity runtime assets",
            "",
            "| Asset | Kind | Status | Objects | Components | Scripts | Events | Animator states |",
            "|---|---|---|---:|---:|---|---:|---:|",
        ]
        for asset in assets:
            cells = [
                asset.get("path"),
                asset.get("kind"),
                asset.get("status"),
                asset.get("object_count", 0),
                asset.get("component_count", 0),
                asset.get("script_types", []),
                asset.get("event_count", 0),
                asset.get("animator_state_count", 0),
            ]
            escaped = [_unity_cell(cell).replace("|", "\\|").replace("\n", " ") for cell in cells]
            lines.append(f"| {' | '.join(escaped)} |")
        lines.extend(["", f"Showing {len(assets)} of {total} matching asset(s)."])
        return "\n".join(lines)

    lines = [f"Unity runtime assets: showing {len(assets)} of {total}"]
    for asset in assets:
        scripts = _unity_cell(asset.get("script_types", []))
        model_suffix = ""
        if asset.get("kind") == "model":
            model_suffix = (
                f", model_nodes={asset.get('model_node_count', 0)}, "
                f"meshes={asset.get('model_mesh_count', 0)}, "
                f"bones={asset.get('model_bone_count', 0)}, "
                f"clips={asset.get('embedded_clip_count', 0)}"
            )
        lines.append(
            f"- {asset.get('path', '—')} [{asset.get('kind', 'unknown')}] "
            f"{asset.get('status', 'unknown')}; objects={asset.get('object_count', 0)}, "
            f"components={asset.get('component_count', 0)}, scripts={scripts}, "
            f"events={asset.get('event_count', 0)}, "
            f"animator_states={asset.get('animator_state_count', 0)}{model_suffix}"
        )
    return "\n".join(lines)


def _format_unity_show(runtime: dict[str, Any], fmt: str) -> str:
    if fmt == "json":
        return json.dumps(runtime, indent=2, ensure_ascii=False)
    if fmt == "markdown":
        lines = [f"# Unity asset: {_unity_cell(runtime.get('path'))}", ""]
        for key in ("kind", "status", "ownership"):
            lines.append(f"- **{key.replace('_', ' ').title()}:** {_unity_cell(runtime.get(key))}")
        for key, value in runtime.items():
            if key in {"path", "kind", "status", "ownership"}:
                continue
            lines.extend(
                [
                    "",
                    f"## {key.replace('_', ' ').title()}",
                    "",
                    "```json",
                    json.dumps(value, indent=2, ensure_ascii=False),
                    "```",
                ]
            )
        return "\n".join(lines)

    lines = [f"Unity asset: {_unity_cell(runtime.get('path'))}"]
    for key, value in runtime.items():
        if key == "path":
            continue
        rendered = (
            json.dumps(value, ensure_ascii=False)
            if isinstance(value, (dict, list))
            else value
        )
        lines.append(f"{key}: {_unity_cell(rendered)}")
    return "\n".join(lines)


def _format_unity_bindings(bindings: list[dict[str, Any]], fmt: str) -> str:
    if fmt == "json":
        return json.dumps(
            {"bindings": bindings, "count": len(bindings)}, indent=2, ensure_ascii=False
        )
    if fmt == "markdown":
        lines = [
            "# UnityEvent bindings",
            "",
            "| Asset | Owner object | Target type | Method | Mode | Status |",
            "|---|---|---|---|---|---|",
        ]
        for binding in bindings:
            cells = [
                binding.get("asset"),
                binding.get("owner_object"),
                binding.get("target_type") or binding.get("target_script"),
                binding.get("method"),
                binding.get("mode"),
                binding.get("status"),
            ]
            escaped = [_unity_cell(cell).replace("|", "\\|").replace("\n", " ") for cell in cells]
            lines.append(f"| {' | '.join(escaped)} |")
        return "\n".join(lines)

    lines = [f"UnityEvent bindings: {len(bindings)}"]
    for binding in bindings:
        target_type = binding.get("target_type") or binding.get("target_script") or "—"
        lines.append(
            f"- {binding.get('asset', '—')} :: {binding.get('owner_object', '—')} -> "
            f"{target_type}.{binding.get('method', '—')} "
            f"[{binding.get('status', 'unknown')}, mode={binding.get('mode', '—')}]"
        )
    return "\n".join(lines)


def cmd_unity(args: argparse.Namespace) -> int:
    """Query Unity runtime intelligence from a verified fresh manifest."""
    manifest = _load_fresh_unity_manifest(args)
    if manifest is None:
        return 1

    if args.unity_command == "list":
        if args.limit <= 0:
            print("[error] --limit must be a positive integer")
            return 1
        assets = _unity_assets(manifest)
        if args.kind:
            kind = args.kind.replace("_", "-").casefold()
            assets = [
                asset
                for asset in assets
                if str(asset.get("kind", "")).replace("_", "-").casefold() == kind
            ]
        print(_format_unity_assets(assets[: args.limit], args.format, len(assets)))
        return 0

    if args.unity_command == "show":
        if args.depth < -1:
            print("[error] --depth must be -1 or greater")
            return 1
        try:
            target = _normalize_unity_path(args.path)
        except ValueError as exc:
            print(f"[error] {exc}")
            return 1

        compact = next(
            (
                asset
                for asset in _unity_assets(manifest)
                if asset["path"].casefold() == target.casefold()
            ),
            None,
        )
        entry = next(
            (item for item in manifest.files if item.path.casefold() == target.casefold()),
            None,
        )
        full = entry.metadata.get("unity_runtime") if entry is not None else None
        if compact is None and not isinstance(full, dict):
            print(f"[error] Unity runtime asset not found in manifest: {target}")
            return 1
        runtime = dict(compact or {})
        if isinstance(full, dict):
            runtime.update(full)
        runtime["path"] = target
        print(_format_unity_show(_trim_unity_depth(runtime, args.depth), args.format))
        return 0

    if args.unity_command == "bindings":
        bindings = _unity_bindings(manifest)
        if args.asset:
            try:
                asset_path = _normalize_unity_path(args.asset)
            except ValueError as exc:
                print(f"[error] {exc}")
                return 1
            bindings = [
                binding
                for binding in bindings
                if str(binding.get("asset", "")).replace("\\", "/").casefold()

                == asset_path.casefold()
            ]
        if args.type:
            expected_type = args.type.casefold()
            bindings = [
                binding
                for binding in bindings
                if str(binding.get("target_type") or binding.get("target_script") or "").casefold()
                == expected_type
            ]
        if args.method:
            expected_method = args.method.casefold()
            bindings = [
                binding
                for binding in bindings
                if str(binding.get("method", "")).casefold() == expected_method
            ]
        print(_format_unity_bindings(bindings, args.format))
        return 0

    print(f"[error] Unknown Unity command: {args.unity_command}")
    return 1


def cmd_scan(args: argparse.Namespace) -> int:
    """Scan codebase and generate manifest."""
    root = (args.path if args.path is not None else args.root).resolve()
    print(f"[scan] Scanning {root}...")
    
    try:
        orchestrator = Orchestrator(root, config_path=args.config)
        
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

        orchestrator = Orchestrator(root, config_path=args.config)
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
                orchestrator = Orchestrator(root, config_path=args.config)
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
        caller_node = node_ids.get(str(call.get("callerId") or ""))
        callee_node = node_ids.get(str(call.get("calleeId") or ""))
        if caller_node and callee_node:
            lines.append(
                f"  {caller_node} -->|{call.get('kind', 'call')}| {callee_node}"
            )
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
