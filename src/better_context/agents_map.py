"""Safe hierarchical AGENTS.md maps for Unity repositories."""

from __future__ import annotations

import json
import re
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import quote

from .graph import DependencyGraph
from .manifest import FileEntry, Manifest
from .unity_intelligence import classify_ownership

BEGIN = "<!-- better-context-unity:begin -->"
END = "<!-- better-context-unity:end -->"
MANAGED_PATTERN = re.compile(re.escape(BEGIN) + r".*?" + re.escape(END), re.DOTALL)
UNITY_ROOTS = {"Assets", "Packages", "ProjectSettings"}
UNITY_RUNTIME_SUFFIXES = {".asset", ".controller", ".overridecontroller", ".prefab", ".unity"}
SUMMARY_FILE = ".ctx-summaries.json"
MAX_SUMMARY_LENGTH = 240
DEFAULT_UNITY_ASSET_LIMIT = 12
DEFAULT_UNITY_OBJECT_LIMIT = 8
ROOT_UNITY_ASSET_LIMIT = 8
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
        if unity and not (
            _is_map_signal_file(path) or _has_unity_runtime_signal(entry, manifest)
        ):
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
            if (
                scene.get("ownership") != "project-owned"
                or not scene.get("path")
                or not scene.get("enabled")
            ):
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
        ".json",
        ".uxml",
        ".uss",
    }


def _unity_runtime(entry: FileEntry) -> Mapping[str, Any]:
    value = entry.metadata.get("unity_runtime")
    return value if isinstance(value, Mapping) else {}


def _unity_runtime_project(manifest: Manifest) -> Mapping[str, Any]:
    value = manifest.project.get("unity_runtime")
    return value if isinstance(value, Mapping) else {}


def _runtime_asset_entries(manifest: Manifest) -> list[tuple[FileEntry, Mapping[str, Any]]]:
    """Return full per-file records, supplemented by compact project records."""
    compact: dict[str, Mapping[str, Any]] = {}
    raw_assets = _unity_runtime_project(manifest).get("assets", [])
    if isinstance(raw_assets, Mapping):
        for path, value in raw_assets.items():
            if isinstance(path, str) and isinstance(value, Mapping):
                compact[path] = value
    elif isinstance(raw_assets, list):
        for value in raw_assets:
            if isinstance(value, Mapping) and isinstance(value.get("path"), str):
                compact[str(value["path"])] = value

    values: list[tuple[FileEntry, Mapping[str, Any]]] = []
    for entry in manifest.files:
        detail = _unity_runtime(entry)
        if not detail:
            detail = compact.get(entry.path, {})
        if detail:
            values.append((entry, detail))
    return values


def _runtime_ownership(entry: FileEntry, detail: Mapping[str, Any]) -> str:
    value = detail.get("ownership") or entry.metadata.get("ownership")
    return str(value or classify_ownership(entry.path))


def _runtime_scope_allows(
    entry: FileEntry,
    detail: Mapping[str, Any],
    manifest: Manifest,
) -> bool:
    ownership = _runtime_ownership(entry, detail)
    scope = str(_unity_runtime_project(manifest).get("scope", "project-owned"))
    if scope == "all":
        return ownership not in {"generated", "package", "unity-generated"}
    return ownership in {"project-owned", "repository"}


def _runtime_list(value: object) -> list[Mapping[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, Mapping)]


def _runtime_animator(detail: Mapping[str, Any]) -> Mapping[str, Any]:
    value = detail.get("animator")
    return value if isinstance(value, Mapping) else {}


def _runtime_script(detail: Mapping[str, Any]) -> Mapping[str, Any]:
    value = detail.get("script")
    return value if isinstance(value, Mapping) else {}


def _runtime_script_names(detail: Mapping[str, Any]) -> list[str]:
    scripts: list[str] = []
    direct_script = _runtime_script(detail)
    if direct_script:
        scripts.append(_script_name(direct_script))
    for obj in _runtime_list(detail.get("objects")):
        for component in _runtime_list(obj.get("components")):
            script = component.get("script")
            if isinstance(script, Mapping):
                scripts.append(_script_name(script))
    return list(dict.fromkeys(value for value in scripts if value))


def _script_name(script: Mapping[str, Any]) -> str:
    for key in ("qualified_name", "type", "path"):
        value = script.get(key)
        if value:
            if key == "path":
                return PurePosixPath(str(value)).stem
            return str(value)
    return ""


def _runtime_event_names(detail: Mapping[str, Any]) -> list[str]:
    values: list[str] = []
    raw_events = detail.get("event_bindings", detail.get("unity_events"))
    for event in _runtime_list(raw_events):
        owner = event.get("owner_path") or event.get("target_path") or "object"
        target_type = event.get("target_type") or event.get("target_script")
        method = event.get("method")
        if method:
            callee = f"{target_type}.{method}()" if target_type else f"{method}()"
            values.append(f"{owner} → {callee}")
    return list(dict.fromkeys(values))


def _build_scene_paths(manifest: Manifest) -> set[str]:
    return {
        str(scene.get("path"))
        for scene in manifest.project.get("scenes", [])
        if scene.get("enabled") and scene.get("path")
    }


def _detail_has_unity_runtime_signal(
    entry: FileEntry,
    detail: Mapping[str, Any],
    manifest: Manifest,
) -> bool:
    if PurePosixPath(entry.path).suffix.lower() not in UNITY_RUNTIME_SUFFIXES:
        return False
    if not detail or not _runtime_scope_allows(entry, detail, manifest):
        return False
    if detail.get("status", "parsed") != "parsed":
        return False

    kind = str(detail.get("kind", ""))
    if entry.path in _build_scene_paths(manifest):
        return True
    if _runtime_script_names(detail) or _runtime_event_names(detail):
        return True
    try:
        if int(detail.get("script_component_count", 0) or 0) > 0:
            return True
    except (TypeError, ValueError):
        pass
    if kind in {"script", "scriptable_object"} and _runtime_script(detail):
        return True
    animator = _runtime_animator(detail)
    if kind in {"animator_controller", "override_controller"} and any(
        _runtime_list(animator.get(key)) for key in ("layers", "states", "blend_trees")
    ):
        return True
    try:
        return int(detail.get("high_signal", 0) or 0) > 0
    except (TypeError, ValueError):
        return False


def _has_unity_runtime_signal(entry: FileEntry, manifest: Manifest) -> bool:
    return _detail_has_unity_runtime_signal(entry, _unity_runtime(entry), manifest)


def _unity_output_limits(manifest: Manifest) -> tuple[int, int]:
    runtime = _unity_runtime_project(manifest)
    candidates = [
        runtime.get("config"),
        runtime.get("agents_limits"),
        runtime.get("limits"),
        manifest.project.get("config"),
        manifest.project,
    ]

    def configured(name: str, short_name: str, compact_name: str, default: int) -> int:
        for candidate in candidates:
            if not isinstance(candidate, Mapping):
                continue
            raw = candidate.get(name, candidate.get(short_name, candidate.get(compact_name)))
            if isinstance(raw, bool):
                continue
            if isinstance(raw, int):
                value = raw
            elif isinstance(raw, str) and raw.isdigit():
                value = int(raw)
            else:
                continue
            if value > 0:
                return value
        return default

    return (
        configured(
            "unity_agents_asset_limit",
            "asset_limit",
            "assets",
            DEFAULT_UNITY_ASSET_LIMIT,
        ),
        configured(
            "unity_agents_object_limit",
            "object_limit",
            "objects",
            DEFAULT_UNITY_OBJECT_LIMIT,
        ),
    )


def _runtime_kind_label(detail: Mapping[str, Any]) -> str:
    labels = {
        "scene": "Scene",
        "prefab": "Prefab",
        "script": "ScriptableObject",
        "scriptable_object": "ScriptableObject",
        "animator_controller": "Animator Controller",
        "override_controller": "Animator Override Controller",
    }
    kind = str(detail.get("kind", "asset"))
    return labels.get(kind, kind.replace("_", " ").title())


def _runtime_responsibility(entry: FileEntry, detail: Mapping[str, Any]) -> str:
    documented = detail.get("responsibility")
    if documented:
        return str(documented)

    kind = str(detail.get("kind", "asset"))
    name = PurePosixPath(entry.path).stem
    roots = _runtime_root_names(detail)
    scripts = _runtime_script_names(detail)
    events = _runtime_event_names(detail)
    animator = _runtime_animator(detail)
    clauses: list[str] = []
    if roots:
        clauses.append("root objects " + ", ".join(f"`{value}`" for value in roots[:3]))
    if scripts:
        clauses.append("wires " + ", ".join(f"`{value}`" for value in scripts[:3]))
    if events:
        clauses.append("binds " + ", ".join(f"`{value}`" for value in events[:2]))

    if kind == "scene":
        lead = f"Unity scene `{name}` defining the serialized runtime hierarchy"
    elif kind == "prefab":
        lead = f"Reusable Unity prefab `{name}` defining a serialized object hierarchy"
    elif kind in {"script", "scriptable_object"}:
        script = _script_name(_runtime_script(detail)) or "resolved ScriptableObject type"
        lead = f"Serialized `{script}` data instance `{name}`"
    elif kind in {"animator_controller", "override_controller"}:
        state_count = len(_runtime_list(animator.get("states")))
        layer_count = len(_runtime_list(animator.get("layers")))
        lead = (
            f"Animator controller `{name}` defining {layer_count} layer(s), "
            f"{state_count} state(s)"
        )
    else:
        lead = f"Serialized Unity runtime asset `{name}`"
    return lead + ("; " + "; ".join(clauses) if clauses else "") + "."


def _runtime_root_names(detail: Mapping[str, Any]) -> list[str]:
    objects = _runtime_list(detail.get("objects"))
    objects_by_id = {str(item.get("file_id")): item for item in objects if item.get("file_id")}
    raw_roots = detail.get("root_objects", detail.get("roots"))
    names: list[str] = []
    if isinstance(raw_roots, list):
        for raw in raw_roots:
            item: Mapping[str, Any] | None
            item = raw if isinstance(raw, Mapping) else objects_by_id.get(str(raw))
            if item:
                name = item.get("path") or item.get("name")
                if name:
                    names.append(str(name))
    if not names:
        names = [
            str(item.get("path") or item.get("name"))
            for item in objects
            if item.get("parent_file_id") is None and (item.get("path") or item.get("name"))
        ]
    return list(dict.fromkeys(names))


def _runtime_asset_score(
    entry: FileEntry,
    detail: Mapping[str, Any],
    manifest: Manifest,
) -> int:
    try:
        score = int(detail.get("high_signal", 0) or 0)
    except (TypeError, ValueError):
        score = 0
    score += len(_runtime_script_names(detail)) * 20
    score += len(_runtime_event_names(detail)) * 30
    animator = _runtime_animator(detail)
    score += len(_runtime_list(animator.get("states"))) * 2
    score += len(_runtime_list(animator.get("transitions")))
    if entry.path in _build_scene_paths(manifest):
        score += 50
    return score


def _runtime_asset_preview(detail: Mapping[str, Any], limit: int) -> str:
    items: list[str] = []
    objects = _runtime_list(detail.get("objects"))
    object_names = [str(item.get("path") or item.get("name")) for item in objects]
    scripts = _runtime_script_names(detail)
    components = [
        str(component.get("type"))
        for item in objects
        for component in _runtime_list(item.get("components"))
        if component.get("type")
    ]
    events = _runtime_event_names(detail)
    animator = _runtime_animator(detail)
    states = [str(item.get("name")) for item in _runtime_list(animator.get("states"))]
    parameters = [str(item.get("name")) for item in _runtime_list(animator.get("parameters"))]
    references = [
        str(item.get("target"))
        for item in _runtime_list(detail.get("references"))
        if item.get("target")
    ]

    sources = [
        ("events", events),
        ("scripts", scripts),
        ("states", states),
        ("parameters", parameters),
        ("objects", object_names),
        ("components", components),
        ("references", references),
    ]
    remaining = max(1, limit)
    for label, values in sources:
        unique = list(dict.fromkeys(value for value in values if value))
        if not unique or remaining <= 0:
            continue
        take = min(len(unique), 2, remaining)
        shown = ", ".join(f"`{value}`" for value in unique[:take])
        items.append(f"{label}: {shown}")
        remaining -= take

    counts = []
    for key, label in (
        ("object_count", "objects"),
        ("component_count", "components"),
        ("script_component_count", "project scripts"),
    ):
        value = detail.get(key)
        if value:
            counts.append(f"{value} {label}")
    prefix = ", ".join(counts)
    if prefix and items:
        return prefix + "; " + "; ".join(items)
    return prefix or "; ".join(items) or "Parsed runtime asset; no named semantic preview."


def _markdown_path(path: str) -> str:
    return "/".join(quote(part, safe="._-~") for part in PurePosixPath(path).parts)


def _unity_runtime_assets_section(
    entries: list[FileEntry],
    manifest: Manifest,
) -> list[str]:
    asset_limit, object_limit = _unity_output_limits(manifest)
    ranked = sorted(
        entries,
        key=lambda entry: (
            -_runtime_asset_score(entry, _unity_runtime(entry), manifest),
            entry.path,
        ),
    )
    lines = [
        "### Unity runtime assets",
        "",
        "| Asset | Kind | Verified responsibility | Runtime topology and bindings |",
        "|---|---|---|---|",
    ]
    for entry in ranked[:asset_limit]:
        detail = _unity_runtime(entry)
        filename = PurePosixPath(entry.path).name
        destination = quote(filename, safe="._-~")
        lines.append(
            f"| [`{_cell(filename)}`]({destination}) | {_cell(_runtime_kind_label(detail))} | "
            f"{_cell(_runtime_responsibility(entry, detail))} | "
            f"{_cell(_runtime_asset_preview(detail, object_limit))} |"
        )
    if len(ranked) > asset_limit:
        lines.append(
            f"| … | — | {len(ranked) - asset_limit} lower-signal runtime assets omitted "
            "from this token-optimized map. | Use `better-context-unity unity list` "
            "or `unity show <project-relative-asset>` for full detail. |"
        )
    lines.extend(
        [
            "",
            "Full hierarchy and serialized evidence: "
            "`better-context-unity unity show <project-relative-asset> --depth -1`.",
            "",
        ]
    )
    return lines


def _root_unity_runtime(manifest: Manifest) -> list[str]:
    runtime = _unity_runtime_project(manifest)
    if not runtime:
        return []
    metrics_value = runtime.get("metrics")
    coverage_value = runtime.get("coverage")
    metrics = metrics_value if isinstance(metrics_value, Mapping) else {}
    coverage = coverage_value if isinstance(coverage_value, Mapping) else {}
    lines = ["", "### Unity runtime intelligence", ""]
    lines.append(
        "- "
        + ", ".join(
            [
                f"{metrics.get('scenes', 0)} scenes",
                f"{metrics.get('prefabs', 0)} prefabs",
                f"{metrics.get('scriptable_objects', 0)} ScriptableObjects",
                f"{metrics.get('animator_controllers', 0)} Animator controllers",
                f"{metrics.get('game_objects', 0)} GameObjects",
                f"{metrics.get('components', 0)} components",
                f"{metrics.get('script_components', 0)} project-script usages",
                f"{metrics.get('unity_events', metrics.get('event_bindings', 0))} "
                "UnityEvent bindings",
                f"{metrics.get('animator_states', 0)} Animator states",
            ]
        )
        + "."
    )
    candidates = coverage.get("candidates", 0)
    parsed = coverage.get("parsed", 0)
    unsupported = coverage.get("unsupported", coverage.get("unsupported_serialization", 0))
    errors = coverage.get("errors", 0)
    lines.append(
        f"- Parse coverage: {parsed}/{candidates} candidate assets parsed; "
        f"{unsupported} unsupported serialization; {errors} parse errors."
    )

    ranked = [
        (entry, detail)
        for entry, detail in _runtime_asset_entries(manifest)
        if _detail_has_unity_runtime_signal(entry, detail, manifest)
    ]
    ranked.sort(
        key=lambda item: (-_runtime_asset_score(item[0], item[1], manifest), item[0].path)
    )
    if ranked:
        lines.extend(
            [
                "",
                "#### Key Unity runtime assets",
                "",
                "| Asset | Kind | Verified responsibility | Runtime signal |",
                "|---|---|---|---|",
            ]
        )
        _asset_limit, object_limit = _unity_output_limits(manifest)
        for entry, detail in ranked[:ROOT_UNITY_ASSET_LIMIT]:
            lines.append(
                f"| [`{_cell(entry.path)}`]({_markdown_path(entry.path)}) | "
                f"{_cell(_runtime_kind_label(detail))} | "
                f"{_cell(_runtime_responsibility(entry, detail))} | "
                f"{_cell(_runtime_asset_preview(detail, object_limit))} |"
            )
        if len(ranked) > ROOT_UNITY_ASSET_LIMIT:
            lines.append(
                f"| … | — | {len(ranked) - ROOT_UNITY_ASSET_LIMIT} additional semantic "
                "runtime assets are available on demand. | "
                "`better-context-unity unity list --limit 50` |"
            )

    lines.extend(
        [
            "",
            "- Browse assets: `better-context-unity unity list "
            "[--kind KIND] [--limit 50] [--format json|human|markdown]`.",
            "- Inspect one hierarchy: `better-context-unity unity show "
            "<project-relative-asset> [--depth 2|-1] [--format ...]`.",
            "- Find persistent calls: `better-context-unity unity bindings "
            "[--asset PATH] [--type TYPE] [--method METHOD] [--format ...]`.",
            "",
        ]
    )
    return lines


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
    runtime_files = [
        entry
        for entry in direct_files
        if _has_unity_runtime_signal(entry, manifest)
    ]
    visible_files = [
        entry
        for entry in direct_files
        if not entry.path.endswith(".meta") and not _unity_runtime(entry)
    ]
    metadata_count = sum(entry.path.endswith(".meta") for entry in direct_files)
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

    if runtime_files:
        lines.extend(_unity_runtime_assets_section(runtime_files, manifest))

    if visible_files or metadata_count:
        lines.extend(
            [
                "### Source and configuration surface",
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
    runtime_assets = [
        (entry, _unity_runtime(entry))
        for entry in files
        if _has_unity_runtime_signal(entry, manifest)
    ]
    if runtime_assets:
        kinds = Counter(_runtime_kind_label(detail) for _entry, detail in runtime_assets)
        scripts = list(
            dict.fromkeys(
                script
                for _entry, detail in runtime_assets
                for script in _runtime_script_names(detail)
            )
        )
        purpose = "Unity runtime asset module containing " + ", ".join(
            f"{count} {kind}" for kind, count in kinds.most_common(4)
        )
        if scripts:
            purpose += "; verified project scripts include " + ", ".join(scripts[:5])
        return purpose + "."
    if name in purposes:
        return purposes[name]
    if files:
        kinds = Counter(
            PurePosixPath(entry.path).suffix.lower() or "extensionless" for entry in files
        )
        common = ", ".join(f"{count} `{kind}`" for kind, count in kinds.most_common(3))
        return f"Asset/configuration module containing {common}."
    return f"Repository module at `{path}`."


def _file_role(entry: FileEntry, graph: DependencyGraph | _EmptyGraph) -> str:
    runtime = _unity_runtime(entry)
    if runtime:
        return _runtime_responsibility(entry, runtime)
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
    lines.extend(_root_unity_runtime(manifest))
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
                "- Pure art, vendor, and runtime assets without semantic signal are collapsed; "
                "use the `unity` commands above for complete object-level evidence.",
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
    calls: list[dict[str, object]] = []
    for item in manifest.graph.call_graph:
        source = item.get("source")
        target = item.get("target")
        if not isinstance(source, str) or not isinstance(target, str) or source == target:
            continue
        if ownership.get(source) not in {"project-owned", "repository"}:
            continue
        if ownership.get(target) not in {"project-owned", "repository"}:
            continue
        calls.append(item)
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
            f"- `{_short_symbol(str(item.get('callerName', '')))}` → "
            f"`{_short_symbol(str(item.get('calleeName', '')))}` "
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
    runtime = _unity_runtime(entry)
    if runtime:
        return _runtime_responsibility(entry, runtime)
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
    runtime_kinds = {
        "animator_motion",
        "prefab_instance",
        "scriptable_object_type",
        "serialized_guid",
        "unity_component",
        "unity_event",
    }
    refs = [
        item
        for item in manifest.graph.edge_details
        if _parent(item.get("source", "")) == rel_dir
        and runtime_kinds.intersection(item.get("kinds", []))
    ]
    if not refs:
        return []
    lines = ["### Unity runtime references", ""]
    for item in refs[:15]:
        kinds = ", ".join(sorted(runtime_kinds.intersection(item.get("kinds", []))))
        evidence = item.get("field") or item.get("owner_path") or item.get("symbol")
        evidence_text = f"; `{evidence}`" if evidence else ""
        lines.append(
            f"- `{item['source']}` → `{item['target']}` ({kinds or 'resolved'}{evidence_text})."
        )
    if len(refs) > 15:
        lines.append(f"- +{len(refs) - 15} more verified Unity references in the manifest.")
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
