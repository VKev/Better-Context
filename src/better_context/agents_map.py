"""Safe hierarchical AGENTS.md maps for Unity repositories."""

from __future__ import annotations

import json
import re
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from urllib.parse import quote

from .graph import DependencyGraph
from .manifest import FileEntry, Manifest
from .unity_intelligence import classify_ownership

BEGIN = "<!-- better-context-unity:begin -->"
END = "<!-- better-context-unity:end -->"
MANAGED_PATTERN = re.compile(re.escape(BEGIN) + r".*?" + re.escape(END), re.DOTALL)
UNITY_ROOTS = {"Assets", "Packages", "ProjectSettings"}
SUMMARY_FILE = ".ctx-summaries.json"
MAX_SUMMARY_LENGTH = 240
UNITY_LIFECYCLE_METHODS = {
    "Awake",
    "OnEnable",
    "Start",
    "FixedUpdate",
    "Update",
    "LateUpdate",
    "OnDisable",
    "OnDestroy",
    "OnValidate",
    "Reset",
}


@dataclass
class MapResult:
    files_written: list[str] = field(default_factory=list)
    files_removed: list[str] = field(default_factory=list)
    unchanged: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def generate_agents_map(
    manifest: Manifest,
    graph: DependencyGraph,
    output_root: Path,
    max_depth: int = -1,
    dry_run: bool = False,
    summaries: Mapping[str, str] | None = None,
) -> MapResult:
    """Create or refresh only the marked map block in each AGENTS.md."""
    output_root = output_root.resolve()
    unity = _is_unity_project(output_root)
    directories = _collect_directories(manifest, unity, max_depth)
    summaries = summaries or {}
    result = MapResult()

    for rel_dir in sorted(directories, key=lambda value: (value.count("/"), value)):
        target = output_root / Path(rel_dir) / "AGENTS.md" if rel_dir else output_root / "AGENTS.md"
        managed = _render_directory(
            rel_dir,
            directories,
            manifest,
            graph,
            unity,
            summaries,
        )
        try:
            current = target.read_text(encoding="utf-8") if target.exists() else ""
            updated = _merge_managed_block(current, managed)
            relative_target = target.relative_to(output_root).as_posix()
            if updated == current:
                result.unchanged.append(relative_target)
            else:
                result.files_written.append(relative_target)
                if not dry_run:
                    target.write_text(updated, encoding="utf-8")
        except OSError as exc:
            result.errors.append(f"{target}: {exc}")

    if unity:
        _remove_stale_managed_maps(output_root, directories, dry_run, result)

    return result


def _is_unity_project(root: Path) -> bool:
    return (root / "Assets").is_dir() and (
        root / "ProjectSettings" / "ProjectVersion.txt"
    ).is_file()


def _collect_directories(manifest: Manifest, unity: bool, max_depth: int) -> set[str]:
    directories = {""}
    for entry in manifest.files:
        path = PurePosixPath(entry.path)
        if path.name == "AGENTS.md" or not path.parts:
            continue
        if unity and path.parts[0] not in UNITY_ROOTS:
            continue
        if unity and not _is_map_signal_file(path):
            continue
        boundary = _map_boundary(path.parent) if unity else None
        parent = path.parent
        while str(parent) != ".":
            is_below_boundary = bool(
                boundary
                and parent.as_posix() != boundary
                and parent.as_posix().startswith(boundary + "/")
            )
            if not is_below_boundary and (max_depth < 0 or len(parent.parts) <= max_depth):
                directories.add(parent.as_posix())
            parent = parent.parent
    if unity:
        for scene in manifest.project.get("scenes", []):
            if scene.get("ownership") != "project-owned" or not scene.get("path"):
                continue
            parent = PurePosixPath(scene["path"]).parent
            while str(parent) != ".":
                if max_depth < 0 or len(parent.parts) <= max_depth:
                    directories.add(parent.as_posix())
                parent = parent.parent
    return directories


def _is_map_signal_file(path: PurePosixPath) -> bool:
    if path.parts[0] in {"Packages", "ProjectSettings"}:
        return path.suffix.lower() != ".meta"
    return path.suffix.lower() in {
        ".cs",
        ".asmdef",
        ".asmref",
        ".unity",
        ".json",
        ".uxml",
        ".uss",
    }


def _map_boundary(parent: PurePosixPath) -> str | None:
    parts = parent.parts
    for depth in range(1, len(parts) + 1):
        candidate = "/".join(parts[:depth])
        ownership = classify_ownership(candidate + "/__context__.cs")
        if ownership in {"vendor", "generated"}:
            return candidate
    return None


def _remove_stale_managed_maps(
    output_root: Path,
    directories: set[str],
    dry_run: bool,
    result: MapResult,
) -> None:
    for root_name in sorted(UNITY_ROOTS):
        root = output_root / root_name
        if not root.is_dir():
            continue
        for target in root.rglob("AGENTS.md"):
            rel_dir = target.parent.relative_to(output_root).as_posix()
            if rel_dir in directories:
                continue
            try:
                current = target.read_text(encoding="utf-8")
            except OSError as exc:
                result.errors.append(f"{target}: {exc}")
                continue
            if not MANAGED_PATTERN.search(current):
                continue
            result.files_removed.append(target.relative_to(output_root).as_posix())
            if not dry_run:
                remove_managed_map(target)


def _render_directory(
    rel_dir: str,
    directories: set[str],
    manifest: Manifest,
    graph: DependencyGraph,
    unity: bool,
    summaries: Mapping[str, str],
) -> str:
    direct_files = [
        entry
        for entry in manifest.files
        if _parent(entry.path) == rel_dir and PurePosixPath(entry.path).name != "AGENTS.md"
    ]
    visible_files = [entry for entry in direct_files if not entry.path.endswith(".meta")]
    metadata_count = len(direct_files) - len(visible_files)
    children = sorted(value for value in directories if value and _parent(value) == rel_dir)
    title = (
        "Unity project map" if not rel_dir and unity else f"Folder map: {rel_dir or 'repository'}"
    )
    lines = [BEGIN, f"## {title}", "", _directory_purpose(rel_dir, manifest, unity), ""]
    if rel_dir in summaries:
        lines.extend([f"**Verified responsibility:** {_summary_cell(summaries[rel_dir])}", ""])

    if not rel_dir:
        lines.extend(_root_intelligence(manifest))
    else:
        lines.extend(_module_intelligence(rel_dir, manifest))

    if children:
        has_summaries = any(child in summaries for child in children)
        header = "| Folder | Purpose | Summary |" if has_summaries else "| Folder | Purpose |"
        divider = "|---|---|---|" if has_summaries else "|---|---|"
        lines.extend(["### Child folders", "", header, divider])
        for child in children:
            name = PurePosixPath(child).name
            destination = quote(name, safe="") + "/AGENTS.md"
            row = f"| [`{name}/`]({destination}) | {_directory_purpose(child, manifest, unity)}"
            if has_summaries:
                row += f" | {_summary_cell(summaries.get(child, '—'))}"
            lines.append(row + " |")
        lines.append("")

    if visible_files or metadata_count:
        lines.extend(
            [
                "### Files and public surface",
                "",
                "| File | Boundary | Verified responsibility | Key public API | "
                "Named dependencies / dependents | Ca/Ce/I/A/D |",
                "|---|---|---|---|---|---|",
            ]
        )
        ordered_files = sorted(
            visible_files,
            key=lambda entry: (
                entry.path not in summaries,
                -manifest.graph.centrality.get(entry.path, 0.0),
                entry.path,
            ),
        )
        visible_limit = max(30, sum(entry.path in summaries for entry in visible_files))
        for entry in ordered_files[:visible_limit]:
            filename = PurePosixPath(entry.path).name
            destination = quote(filename, safe="._-~")
            responsibility = summaries.get(entry.path) or _verified_responsibility(entry)
            lines.append(
                f"| [`{_cell(filename)}`]({destination}) | "
                f"{_cell(entry.metadata.get('ownership', 'repository'))} | "
                f"{_cell(responsibility)} | {_cell(_public_api(entry))} | "
                f"{_cell(_named_relations(entry, graph, manifest))} | "
                f"{_cell(_coupling(entry))} |"
            )
        if len(visible_files) > visible_limit:
            remaining = len(visible_files) - visible_limit
            lines.append(
                f"| … | — | {remaining} lower-signal files omitted from this token-optimized map; "
                "inspect the directory or manifest on demand. | — | — | — |"
            )
        if metadata_count:
            lines.append(
                f"| Unity `.meta` files | generated metadata | {metadata_count} sidecar files are "
                "intentionally hidden from the table. | — | Never treated as C# dependencies. | — |"
            )
        lines.append("")

    lines.extend(_local_calls(rel_dir, manifest))
    lines.extend(_local_asset_references(rel_dir, manifest))
    lines.extend(_local_violations(rel_dir, manifest))

    if rel_dir:
        lines.extend(["Parent map: [`../AGENTS.md`](../AGENTS.md)", ""])
    else:
        lines.extend(
            [
                "Read the maps from the repository root down to the target folder "
                "before editing there.",
                "Keep handwritten instructions outside this managed block; "
                "regeneration preserves them.",
                "",
            ]
        )

    lines.extend([END, ""])
    return "\n".join(lines)


def _parent(path: str) -> str:
    parent = PurePosixPath(path).parent
    return "" if str(parent) == "." else parent.as_posix()


def _directory_purpose(path: str, manifest: Manifest, unity: bool) -> str:
    name = PurePosixPath(path).name.lower() if path else ""
    ownership = classify_ownership(path.rstrip("/") + "/__context__.cs") if path else "repository"
    if ownership == "vendor":
        return (
            "Vendor/third-party boundary; inspect as dependency and avoid project "
            "feature edits here."
        )
    if ownership == "generated":
        return (
            "Generated boundary; change the source/generator rather than files under this folder."
        )
    purposes = {
        "assets": "Project-owned Unity assets and source code.",
        "packages": "Unity package declarations and embedded project packages.",
        "projectsettings": "Unity project configuration.",
        "scripts": "C# source code.",
        "runtime": "Runtime code and assets.",
        "editor": "Unity Editor-only tooling.",
        "tests": "Automated tests and their fixtures.",
        "gameplay": "Gameplay feature implementations.",
        "ui": "User interface code and assets.",
        "data": "Authored data and serialized configuration.",
        "resources": "Assets loaded through Unity Resources APIs.",
        "scenes": "Unity scenes.",
        "prefabs": "Reusable Unity prefab assets.",
        "art": "Visual art assets.",
        "audio": "Audio assets and configuration.",
    }
    if not path:
        return (
            "Navigation map for the Unity project."
            if unity
            else "Navigation map for the repository."
        )
    if name in purposes:
        return purposes[name]
    prefix = path.rstrip("/") + "/" if path else ""
    source_files = [
        entry
        for entry in manifest.files
        if entry.path.startswith(prefix) and entry.language and not entry.path.endswith("AGENTS.md")
    ]
    declarations = [
        chunk.name
        for entry in source_files
        for chunk in entry.chunks
        if chunk.type in {"class", "interface", "struct", "record", "enum", "delegate"}
    ]
    if declarations:
        listed = ", ".join(declarations[:4])
        suffix = "…" if len(declarations) > 4 else ""
        operations = [
            chunk.name
            for entry in source_files
            for chunk in entry.chunks
            if chunk.type in {"method", "operator"} and chunk.name not in UNITY_LIFECYCLE_METHODS
        ]
        operation_text = ""
        if operations:
            unique = list(dict.fromkeys(operations))
            operation_text = "; verified operations include " + ", ".join(unique[:5])
        return f"Unity source module defining {listed}{suffix}{operation_text}."
    files = [
        entry
        for entry in manifest.files
        if entry.path.startswith(prefix) and not entry.path.endswith("AGENTS.md")
    ]
    if files:
        kinds = Counter(
            PurePosixPath(entry.path).suffix.lower() or "extensionless" for entry in files
        )
        common = ", ".join(f"{count} `{kind}`" for kind, count in kinds.most_common(3))
        return f"Asset/configuration module containing {common}."
    return f"Repository module at `{path}`."


def _file_role(entry: FileEntry, graph: DependencyGraph) -> str:
    suffix = PurePosixPath(entry.path).suffix.lower()
    if suffix == ".cs":
        types = [chunk for chunk in entry.chunks if chunk.type != "method"]
        labels = []
        for chunk in types[:3]:
            unity_type = chunk.metadata.get("unity_type")
            labels.append(f"{chunk.name} ({unity_type})" if unity_type else chunk.name)
        role = ", ".join(labels) if labels else "C# source"
        dependents = graph.in_degree(entry.path)
        return f"{role}; {dependents} dependent file(s)." if dependents else f"{role}."
    roles = {
        ".asmdef": "Unity assembly definition.",
        ".asmref": "Unity assembly reference.",
        ".unity": "Unity scene.",
        ".prefab": "Unity prefab.",
        ".asset": "Serialized Unity asset.",
        ".meta": "Unity asset identity and importer metadata.",
        ".json": "JSON configuration or package metadata.",
    }
    return roles.get(suffix, "Project file.")


def _root_intelligence(manifest: Manifest) -> list[str]:
    project = manifest.project
    metrics = project.get("metrics", {})
    lines = ["### Project overview", ""]
    if project.get("kind") == "unity":
        lines.append(
            f"- Unity `{project.get('unity_version', 'unknown')}`; analyzer: "
            f"`{project.get('analysis_engine', 'unknown')}`."
        )
        if project.get("product_name") or project.get("bundle_version"):
            lines.append(
                f"- Product: `{project.get('product_name', 'unknown')}`; version: "
                f"`{project.get('bundle_version', 'unknown')}`."
            )
        scenes = project.get("scenes", [])
        if scenes:
            enabled = [item["path"] for item in scenes if item.get("enabled")]
            owned = [item["path"] for item in scenes if item.get("ownership") == "project-owned"]
            lines.append(
                f"- Scene assets: {len(scenes)} total, {len(owned)} project-owned, "
                f"{len(enabled)} enabled in Build Settings"
                + ("; project scenes: " + ", ".join(f"`{p}`" for p in owned[:8]) if owned else "")
                + "."
            )
        asmdefs = project.get("asmdefs", [])
        if asmdefs:
            lines.append(
                f"- Assembly definitions ({len(asmdefs)}): "
                + ", ".join(f"`{item.get('name')}`" for item in asmdefs[:12])
                + "."
            )
        packages = project.get("packages", [])
        if packages:
            package_text = ", ".join(
                f"`{item['name']}@{item['version']}`" for item in packages[:12]
            )
            lines.append(f"- Declared packages ({len(packages)}): {package_text}.")
    lines.extend(["", "### Metrics", ""])
    lines.append(
        "- "
        + ", ".join(
            [
                f"{metrics.get('files', len(manifest.files))} files",
                f"{metrics.get('source_files', 0)} source files",
                f"{metrics.get('symbols', 0)} symbols",
                f"{metrics.get('public_symbols', 0)} public symbols",
                f"{metrics.get('dependencies', len(manifest.graph.edges))} verified/resolved edges",
                f"{metrics.get('call_sites', len(manifest.graph.call_graph))} resolved call sites",
            ]
        )
        + "."
    )
    lines.append(
        f"- Exact Unity serialized GUID edges: {metrics.get('serialized_dependencies', 0)}; "
        f"project-owned edges: {metrics.get('project_owned_dependencies', 0)}; "
        f"project-owned circular components: {metrics.get('project_owned_cycles', 0)}."
    )
    lines.extend(_key_files(manifest))
    lines.extend(_architecture_summary(manifest))
    lines.extend(_cycle_summary(manifest))
    lines.extend(_feature_flows(manifest))
    lines.extend(_ownership_summary(manifest))
    lines.extend(_testing_rules(manifest))
    lines.extend(
        [
            "### Focus and token controls",
            "",
            "- Deep neighborhood: `better-context-unity focus <relative-file> --depth 3`.",
            '- Token budget: `better-context-unity optimize --budget 8000 --task "<task>"`.',
                "- Semantic anchors shown beside public APIs remain stable across file "
                "moves when logic is unchanged.",
                "- Asset-only prefab/material/data directories are collapsed from the map; "
                "their exact GUID relationships remain available in the manifest and focus output.",
                "",
            ]
        )
    return lines


def _module_intelligence(rel_dir: str, manifest: Manifest) -> list[str]:
    prefix = rel_dir.rstrip("/") + "/"
    source_files = [
        entry
        for entry in manifest.files
        if entry.path.startswith(prefix) and entry.language and not entry.path.endswith("AGENTS.md")
    ]
    if not source_files:
        return []
    layers = Counter(
        entry.metadata.get("architecture", {}).get("layer", "unclassified")
        for entry in source_files
    )
    key = sorted(
        source_files,
        key=lambda entry: manifest.graph.centrality.get(entry.path, 0.0),
        reverse=True,
    )[:5]
    public_count = sum(sum(1 for chunk in entry.chunks if chunk.exported) for entry in source_files)
    return [
        "### Module intelligence",
        "",
        f"- {len(source_files)} source files; {public_count} public symbols.",
        "- Heuristic layers: "
        + ", ".join(f"{name}={count}" for name, count in sorted(layers.items()))
        + ".",
        "- Key files by PageRank: "
        + ", ".join(
            f"`{entry.path}` ({manifest.graph.centrality.get(entry.path, 0.0):.4f})"
            for entry in key
        )
        + ".",
        "",
    ]


def _key_files(manifest: Manifest) -> list[str]:
    entries = {entry.path: entry for entry in manifest.files}
    ranked = [
        (path, score)
        for path, score in manifest.graph.centrality.items()
        if path in entries
        and entries[path].metadata.get("ownership") in {"project-owned", "repository"}
        and entries[path].language
        and not path.endswith(".meta")
    ]
    ranked.sort(key=lambda item: item[1], reverse=True)
    lines = [
        "",
        "### Key files (PageRank)",
        "",
        "| File | Score | Verified responsibility |",
        "|---|---:|---|",
    ]
    for path, score in ranked[:12]:
        lines.append(
            f"| `{_cell(path)}` | {score:.6f} | {_cell(_verified_responsibility(entries[path]))} |"
        )
    if not ranked:
        lines.append("| — | — | No dependency centrality data. |")
    lines.append("")
    return lines


def _architecture_summary(manifest: Manifest) -> list[str]:
    architecture = manifest.graph.architecture
    layers = architecture.get("layers", {})
    violations = architecture.get("violations", [])
    lines = ["### Architecture layers (heuristic)", ""]
    lines.append("- " + ", ".join(f"{name}: {len(paths)}" for name, paths in layers.items()) + ".")
    if violations:
        lines.extend(
            [
                f"- Detailed layer violations ({len(violations)}):",
                "",
                "| Source | Layer | Forbidden target | Layer |",
                "|---|---|---|---|",
            ]
        )
        for item in violations[:20]:
            lines.append(
                f"| `{_cell(item['source_path'])}` | {item['source_layer']} | "
                f"`{_cell(item['target_path'])}` | {item['target_layer']} |"
            )
    else:
        lines.append("- No violation was found under the inferred layer model.")
    lines.append("")
    return lines


def _cycle_summary(manifest: Manifest) -> list[str]:
    lines = ["### Circular dependencies", ""]
    cycles = manifest.project.get("project_cycles", manifest.graph.cycles)
    if not cycles:
        return lines + ["No circular file dependency component was detected.", ""]
    for index, cycle in enumerate(cycles[:10], 1):
        shown = cycle[:20]
        suffix = f" → … (+{len(cycle) - 20})" if len(cycle) > 20 else ""
        lines.append(f"{index}. " + " → ".join(f"`{path}`" for path in shown) + suffix)
    if len(cycles) > 10:
        lines.append(f"- {len(cycles) - 10} additional components are in the manifest.")
    lines.append("")
    return lines


def _feature_flows(manifest: Manifest) -> list[str]:
    ownership = {entry.path: entry.metadata.get("ownership") for entry in manifest.files}
    calls = [
        item
        for item in manifest.graph.call_graph
        if item.get("source") != item.get("target")
        and ownership.get(item.get("source")) in {"project-owned", "repository"}
        and ownership.get(item.get("target")) in {"project-owned", "repository"}
    ]
    lines = ["### Observed feature flow (resolved calls)", ""]
    if not calls:
        return lines + ["No cross-file call chain was resolved.", ""]
    by_source: dict[str, list[dict[str, object]]] = {}
    for item in calls:
        by_source.setdefault(str(item.get("source", "")), []).append(item)
    preferred = (
        "FirebaseService",
        "IaaService",
        "IapService",
        "ProductRewardService",
        "UIPresenter",
        "ShopView",
    )
    source_paths = sorted(
        by_source,
        key=lambda path: (
            next((index for index, value in enumerate(preferred) if value in path), len(preferred)),
            path,
        ),
    )
    selected: list[dict[str, object]] = []
    round_index = 0
    while len(selected) < 15:
        added = False
        for source in source_paths:
            values = by_source[source]
            if round_index < len(values):
                selected.append(values[round_index])
                added = True
                if len(selected) == 15:
                    break
        if not added:
            break
        round_index += 1
    for item in selected:
        lines.append(
            f"- `{_short_symbol(item.get('callerName', ''))}` → "
            f"`{_short_symbol(item.get('calleeName', ''))}` "
            f"(`{item.get('source')}`:{item.get('line')} → `{item.get('target')}`)."
        )
    lines.extend(
        [
            "",
            "Direction is caller → callee; this is code evidence, not an inferred "
            "business narrative.",
            "",
        ]
    )
    return lines


def _ownership_summary(manifest: Manifest) -> list[str]:
    project = manifest.project
    counts = project.get("ownership_counts", {})
    lines = ["### Ownership boundaries", ""]
    if counts:
        lines.append("- " + ", ".join(f"{name}: {count}" for name, count in counts.items()) + ".")
    vendor = project.get("vendor_roots", [])
    generated = project.get("generated_roots", [])
    if vendor:
        lines.append(
            "- Vendor/third-party roots (avoid edits unless explicitly intended): "
            + ", ".join(f"`{p}`" for p in vendor)
            + "."
        )
    if generated:
        lines.append(
            "- Generated roots (regenerate; do not hand-edit): "
            + ", ".join(f"`{p}`" for p in generated)
            + "."
        )
    lines.extend(
        [
            "- `.csproj`, `.sln`, and `.slnx` are Unity-generated even when present "
            "at repository root.",
            "",
        ]
    )
    return lines


def _testing_rules(manifest: Manifest) -> list[str]:
    project = manifest.project
    tests = project.get("test_files", [])
    version = project.get("unity_version", "the recorded Unity version")
    lines = ["### Testing and change rules", ""]
    if project.get("kind") == "unity":
        lines.extend(
            [
                f"- Validate C# changes by compiling in Unity `{version}`; run relevant "
                "EditMode/PlayMode tests in Unity Test Runner.",
                "- For CLI automation, use Unity `-batchmode -runTests` with the intended "
                "test platform and capture its result XML.",
                "- Change `Packages/manifest.json` through Unity Package Manager when "
                "possible; review `packages-lock.json` together.",
                "- Prefer Unity Editor changes for `ProjectSettings`; do not hand-edit "
                "generated solution/project files.",
                "- Treat vendor, package, and generated boundaries above as read-only "
                "unless the task explicitly owns them.",
            ]
        )
    else:
        lines.append(
            "- Run the repository's detected test/build commands before changing public APIs."
        )
    if tests:
        lines.append(
            "- Detected test files: " + ", ".join(f"`{path}`" for path in tests[:12]) + "."
        )
    else:
        lines.append(
            "- No project test file was detected; Unity compilation and targeted "
            "manual validation remain required."
        )
    lines.append("")
    return lines


def _verified_responsibility(entry: FileEntry) -> str:
    ownership = entry.metadata.get("ownership")
    if ownership == "unity-generated":
        return "Unity-generated project/solution file; regenerate instead of hand-editing."
    if ownership == "generated":
        return "Generated content; change its source or generator instead of hand-editing."
    documented = next((chunk.docstring for chunk in entry.chunks if chunk.docstring), None)
    if documented:
        return documented
    suffix = PurePosixPath(entry.path).suffix.lower()
    if suffix == ".cs":
        types = [
            chunk
            for chunk in entry.chunks
            if chunk.type in {"class", "interface", "struct", "record", "enum", "delegate"}
        ]
        if types:
            labels = [f"`{chunk.name}`" for chunk in types[:3]]
            unity_types = {
                chunk.metadata.get("unity_type")
                for chunk in types
                if chunk.metadata.get("unity_type")
            }
            if "MonoBehaviour" in unity_types:
                subject = "Unity component"
            elif "ScriptableObject" in unity_types:
                subject = "Unity data asset type"
            elif "StateMachineBehaviour" in unity_types:
                subject = "Unity Animator state behaviour"
            elif all(chunk.type == "interface" for chunk in types):
                subject = "Contract"
            else:
                subject = "C# type"
            methods = [chunk.name for chunk in entry.chunks if chunk.type in {"method", "operator"}]
            lifecycle = list(
                dict.fromkeys(name for name in methods if name in UNITY_LIFECYCLE_METHODS)
            )
            operations = list(
                dict.fromkeys(name for name in methods if name not in UNITY_LIFECYCLE_METHODS)
            )
            facts = [f"{subject} defining {', '.join(labels)}"]
            if lifecycle:
                facts.append("lifecycle " + ", ".join(f"`{name}`" for name in lifecycle[:4]))
            if operations:
                facts.append("implements " + ", ".join(f"`{name}`" for name in operations[:5]))
            public_members = [
                chunk for chunk in entry.chunks if chunk.exported and chunk not in types
            ]
            if not lifecycle and not operations and public_members:
                facts.append(f"exposes {len(public_members)} public/protected data members")
            return "; ".join(facts) + "."
        return "C# source with no declaration resolved by the active analyzer."
    return _file_role(entry, _EmptyGraph())


def _public_api(entry: FileEntry) -> str:
    public = [chunk for chunk in entry.chunks if chunk.exported]
    if not public:
        return "—"
    ordered = sorted(public, key=lambda chunk: (chunk.parent is not None, chunk.start_line))
    values = []
    for chunk in ordered[:6]:
        anchor = f" @{chunk.semantic_anchor[:8]}" if chunk.semantic_anchor else ""
        extension = " extension" if chunk.metadata.get("extension") else ""
        unity_type = chunk.metadata.get("unity_type")
        unity_label = f" ({unity_type})" if unity_type else ""
        values.append(f"{chunk.type}{extension} `{chunk.name}`{unity_label}{anchor}")
    if len(public) > 6:
        values.append(f"+{len(public) - 6} more")
    return "; ".join(values)


def _named_relations(entry: FileEntry, graph: DependencyGraph, manifest: Manifest) -> str:
    details = {
        (item.get("source"), item.get("target")): item for item in manifest.graph.edge_details
    }
    dependencies = sorted(graph.get_dependencies(entry.path))
    dependents = sorted(graph.get_dependents(entry.path))
    pieces = []
    if dependencies:
        values = []
        for target in dependencies[:3]:
            kinds = ",".join(details.get((entry.path, target), {}).get("kinds", []))
            values.append(f"{target} ({kinds or 'resolved'})")
        pieces.append("uses " + ", ".join(values))
    if dependents:
        pieces.append("used by " + ", ".join(dependents[:3]))
    return "; ".join(pieces) or "—"


def _coupling(entry: FileEntry) -> str:
    value = entry.metadata.get("coupling")
    if not value:
        return "—"
    return (
        f"{value.get('ca', 0)}/{value.get('ce', 0)}/"
        f"{value.get('i', 0):.2f}/{value.get('a', 0):.2f}/{value.get('d', 0):.2f}"
    )


def _local_calls(rel_dir: str, manifest: Manifest) -> list[str]:
    calls = [
        item for item in manifest.graph.call_graph if _parent(item.get("source", "")) == rel_dir
    ]
    if not calls:
        return []
    lines = ["### Resolved function calls", ""]
    for item in calls[:12]:
        lines.append(
            f"- `{_short_symbol(item.get('callerName', ''))}` → "
            f"`{_short_symbol(item.get('calleeName', ''))}` at line {item.get('line')} "
            f"({item.get('kind', 'call')})."
        )
    if len(calls) > 12:
        lines.append(f"- +{len(calls) - 12} more call sites in the manifest.")
    lines.append("")
    return lines


def _local_asset_references(rel_dir: str, manifest: Manifest) -> list[str]:
    refs = [
        item
        for item in manifest.graph.edge_details
        if _parent(item.get("source", "")) == rel_dir and "serialized_guid" in item.get("kinds", [])
    ]
    if not refs:
        return []
    lines = ["### Unity serialized references", ""]
    for item in refs[:15]:
        lines.append(f"- `{item['source']}` → `{item['target']}` (exact GUID).")
    if len(refs) > 15:
        lines.append(f"- +{len(refs) - 15} more exact GUID references in the manifest.")
    lines.append("")
    return lines


def _local_violations(rel_dir: str, manifest: Manifest) -> list[str]:
    violations = [
        item
        for item in manifest.graph.architecture.get("violations", [])
        if _parent(item.get("source_path", "")) == rel_dir
    ]
    if not violations:
        return []
    lines = ["### Layer violations affecting this folder", ""]
    for item in violations:
        lines.append(f"- {item.get('message')}")
    lines.append("")
    return lines


def _short_symbol(value: str) -> str:
    if not value:
        return "unknown"
    head, separator, _parameters = value.partition("(")
    name = head.rsplit(".", 1)[-1]
    return name + "()" if separator else name


def _cell(value: object) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ").strip()


class _EmptyGraph:
    def in_degree(self, _path: str) -> int:
        return 0


def parse_summary_assignment(value: str) -> tuple[str, str]:
    """Parse a CLI PATH=TEXT summary assignment."""
    if "=" not in value:
        raise ValueError("Summary must use PATH=TEXT format")
    raw_path, raw_text = value.split("=", 1)
    return normalize_summary_path(raw_path), normalize_summary_text(raw_text)


def normalize_summary_path(value: str) -> str:
    """Normalize and validate a project-relative summary target."""
    normalized = value.strip().replace("\\", "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    normalized = normalized.rstrip("/")
    if normalized in {"", "."}:
        return ""
    path = PurePosixPath(normalized)
    if path.is_absolute() or ".." in path.parts or re.match(r"^[A-Za-z]:", normalized):
        raise ValueError("Summary path must be relative to the project root")
    return path.as_posix()


def normalize_summary_text(value: str) -> str:
    """Keep summaries compact enough for navigation maps."""
    normalized = " ".join(value.split())
    if not normalized:
        raise ValueError("Summary text cannot be empty")
    if len(normalized) > MAX_SUMMARY_LENGTH:
        raise ValueError(f"Summary text cannot exceed {MAX_SUMMARY_LENGTH} characters")
    return normalized


def load_summaries(root: Path) -> dict[str, str]:
    """Load optional persisted summaries from the project root."""
    path = root / SUMMARY_FILE
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Cannot read {SUMMARY_FILE}: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"{SUMMARY_FILE} must contain a JSON object")

    summaries: dict[str, str] = {}
    for raw_path, raw_text in data.items():
        if not isinstance(raw_path, str) or not isinstance(raw_text, str):
            raise ValueError(f"{SUMMARY_FILE} keys and values must be strings")
        summaries[normalize_summary_path(raw_path)] = normalize_summary_text(raw_text)
    return summaries


def save_summaries(root: Path, summaries: Mapping[str, str]) -> Path:
    """Persist optional summaries, or remove the empty ledger."""
    path = root / SUMMARY_FILE
    if summaries:
        ordered = {path or ".": text for path, text in sorted(summaries.items())}
        path.write_text(
            json.dumps(ordered, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    elif path.exists():
        path.unlink()
    return path


def summary_targets(manifest: Manifest, root: Path, max_depth: int = -1) -> set[str]:
    """Return file and folder paths that can appear in generated maps."""
    directories = _collect_directories(manifest, _is_unity_project(root), max_depth)
    files = {
        entry.path
        for entry in manifest.files
        if _parent(entry.path) in directories and PurePosixPath(entry.path).name != "AGENTS.md"
    }
    return directories | files


def _summary_cell(value: str) -> str:
    return " ".join(value.split()).replace("|", r"\|")


def _merge_managed_block(current: str, managed: str) -> str:
    if MANAGED_PATTERN.search(current):
        return MANAGED_PATTERN.sub(managed.rstrip(), current).rstrip() + "\n"
    if "Auto-generated context for AI agents" in current:
        return managed
    if not current.strip():
        return managed
    return current.rstrip() + "\n\n" + managed


def remove_managed_map(path: Path) -> bool:
    """Remove only this tool's block, preserving handwritten instructions."""
    try:
        current = path.read_text(encoding="utf-8")
    except OSError:
        return False
    if not MANAGED_PATTERN.search(current):
        return False
    updated = MANAGED_PATTERN.sub("", current).strip()
    if updated:
        path.write_text(updated + "\n", encoding="utf-8")
    else:
        path.unlink()
    return True


__all__ = [
    "BEGIN",
    "END",
    "MAX_SUMMARY_LENGTH",
    "MapResult",
    "SUMMARY_FILE",
    "generate_agents_map",
    "load_summaries",
    "normalize_summary_path",
    "parse_summary_assignment",
    "remove_managed_map",
    "save_summaries",
    "summary_targets",
]
