"""Safe hierarchical AGENTS.md maps for Unity repositories."""

from __future__ import annotations

import json
import posixpath
import re
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import quote

from .graph import DependencyGraph
from .manifest import FileEntry, Manifest
from .project_kind import COCOS_KIND, UNITY_KIND, detect_project_kind
from .project_profile import (
    COCOS_PROFILE,
    UNITY_PROFILE,
    ProjectKindProfile,
    profile_for_kind,
)
from .unity_intelligence import classify_ownership

BEGIN = "<!-- better-context-unity:begin -->"
END = "<!-- better-context-unity:end -->"
MANAGED_PATTERN = re.compile(re.escape(BEGIN) + r".*?" + re.escape(END), re.DOTALL)

# Instruction files that may carry a managed map block: ``AGENTS.md`` is read by
# Codex-style agents, ``CLAUDE.md`` by Claude Code. Both names are always
# *recognized* (never analysed as project source, always cleanable); which ones
# are *written* comes from ``map_files`` in ``.ctx.json`` or ``--map-file``.
MAP_FILENAMES: tuple[str, ...] = ("AGENTS.md", "CLAUDE.md")
DEFAULT_MAP_FILENAMES: tuple[str, ...] = ("AGENTS.md",)
_MAP_FILENAMES_CF = {name.casefold() for name in MAP_FILENAMES}
_MAP_META_FILENAMES_CF = {f"{name}.meta".casefold() for name in MAP_FILENAMES}


def is_map_filename(name: str) -> bool:
    """Return True when ``name`` is a managed instruction-map file name."""
    return name.casefold() in _MAP_FILENAMES_CF


def is_map_path(path: str) -> bool:
    """Return True when ``path`` points at a managed instruction-map file."""
    return is_map_filename(PurePosixPath(path).name)


def is_map_meta_filename(name: str) -> bool:
    """Return True when ``name`` is a Unity ``.meta`` sidecar of a map file."""
    return name.casefold() in _MAP_META_FILENAMES_CF


def resolve_map_filenames(values: Sequence[str] | None) -> tuple[str, ...]:
    """Validate and normalize requested map file names, preserving order.

    An empty or missing selection falls back to ``DEFAULT_MAP_FILENAMES`` so
    existing callers and configurations keep writing ``AGENTS.md`` only.
    """
    if not values:
        return DEFAULT_MAP_FILENAMES
    canonical = {name.casefold(): name for name in MAP_FILENAMES}
    selected: list[str] = []
    for value in values:
        key = str(value).strip().casefold()
        if key not in canonical:
            supported = ", ".join(MAP_FILENAMES)
            raise ValueError(f"Unsupported map file '{value}'; supported: {supported}")
        name = canonical[key]
        if name not in selected:
            selected.append(name)
    return tuple(selected)
# Kept as module-level views on the Unity profile so existing callers and
# generated references keep working; the renderer itself reads the active profile.
UNITY_ROOTS = set(UNITY_PROFILE.roots)
UNITY_RUNTIME_SUFFIXES = set(UNITY_PROFILE.runtime_suffixes)
UNITY_ASSET_PATH_SUFFIXES = set(UNITY_PROFILE.asset_path_suffixes)
UNITY_LIFECYCLE_METHODS = set(UNITY_PROFILE.lifecycle_methods)
SUMMARY_FILE = ".ctx-summaries.json"
MAX_SUMMARY_LENGTH = 240
DEFAULT_UNITY_ASSET_LIMIT = 12
DEFAULT_UNITY_OBJECT_LIMIT = 8
DEFAULT_UNITY_PATH_LIMIT = 24
ROOT_UNITY_ASSET_LIMIT = 8
UNITY_ART_MAP_MAX_DEPTH = 3


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
    map_filenames: Sequence[str] | None = None,
) -> MapResult:
    """Create or refresh only the marked map block in each instruction map.

    ``map_filenames`` selects which instruction files receive the managed block
    (``AGENTS.md`` for Codex-style agents, ``CLAUDE.md`` for Claude Code). Every
    selected file receives the same scan result, so client maps cannot drift.
    """
    output_root = output_root.resolve()
    filenames = resolve_map_filenames(map_filenames)
    profile = resolve_profile(output_root, manifest)
    directories = _collect_directories(manifest, profile, max_depth)
    summaries = summaries or {}
    result = MapResult()

    for rel_dir in sorted(directories, key=lambda value: (value.count("/"), value)):
        for filename in filenames:
            target = (
                output_root / Path(rel_dir) / filename if rel_dir else output_root / filename
            )
            managed = _render_directory(
                rel_dir,
                directories,
                manifest,
                graph,
                profile,
                summaries,
                map_filename=filename,
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

    if profile.roots:
        _remove_stale_managed_maps(
            output_root, directories, dry_run, result, filenames, profile
        )

    return result


def resolve_profile(root: Path, manifest: Manifest | None = None) -> ProjectKindProfile:
    """Pick the engine profile for a project root.

    A manifest produced by a previous scan already records the kind, so trust it
    when present; otherwise detect from the filesystem.
    """
    kind = ""
    if manifest is not None:
        kind = str(manifest.project.get("kind", "") or "")
        if kind not in {UNITY_KIND, COCOS_KIND}:
            # A scan that produced engine runtime facts is authoritative even when the
            # manifest predates the `kind` field or the root markers are unavailable.
            runtime = manifest.project.get("engine_runtime")
            if isinstance(runtime, Mapping) and runtime.get("kind") in {UNITY_KIND, COCOS_KIND}:
                kind = str(runtime["kind"])
            elif isinstance(manifest.project.get("unity_runtime"), Mapping):
                kind = UNITY_KIND
    if kind not in {UNITY_KIND, COCOS_KIND}:
        kind = detect_project_kind(root)
    return profile_for_kind(kind)


def _is_unity_project(root: Path) -> bool:
    return detect_project_kind(root) == UNITY_KIND


def _collect_directories(
    manifest: Manifest, profile: ProjectKindProfile, max_depth: int
) -> set[str]:
    directories = {""}
    known_paths = {entry.path for entry in manifest.files}
    for entry in manifest.files:
        path = PurePosixPath(entry.path)
        if is_map_filename(path.name) or not path.parts:
            continue
        if profile.roots and path.parts[0] not in profile.roots:
            continue
        engine = profile.is_engine
        source_signal = engine and _is_map_signal_file(path, profile)
        runtime_signal = engine and _has_unity_runtime_signal(entry, manifest, profile)
        semantic_signal = source_signal or runtime_signal
        asset_path = _logical_unity_asset_path(entry.path, profile) if engine else ""
        if (
            asset_path
            and entry.path.endswith(".meta")
            and asset_path not in known_paths
            and not (Path(manifest.meta.root_path) / Path(asset_path)).is_file()
        ):
            asset_path = ""
        if engine and not semantic_signal and not asset_path:
            continue
        boundary = _map_boundary(path.parent) if engine else None
        parent = PurePosixPath(asset_path).parent if asset_path else path.parent
        depth_limit = max_depth
        runtime_kind = str(_unity_runtime(entry).get("kind", ""))
        bounded_art_signal = asset_path and (
            not semantic_signal
            or (
                not source_signal
                and runtime_kind in {"animation_clip", "material", "mesh", "model"}
            )
        )
        if bounded_art_signal:
            depth_limit = (
                UNITY_ART_MAP_MAX_DEPTH
                if max_depth < 0
                else min(max_depth, UNITY_ART_MAP_MAX_DEPTH)
            )
        while str(parent) != ".":
            is_below_boundary = bool(
                boundary
                and parent.as_posix() != boundary
                and parent.as_posix().startswith(boundary + "/")
            )
            if not is_below_boundary and (depth_limit < 0 or len(parent.parts) <= depth_limit):
                directories.add(parent.as_posix())
            parent = parent.parent
    if profile.kind == UNITY_KIND:
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


def _is_map_signal_file(path: PurePosixPath, profile: ProjectKindProfile) -> bool:
    if path.parts[0] in profile.config_roots:
        return path.suffix.lower() != ".meta"
    return profile.map_signal_suffix(path.suffix)


def _logical_unity_asset_path(path: str, profile: ProjectKindProfile = UNITY_PROFILE) -> str:
    candidate = path[:-5] if path.lower().endswith(".meta") else path
    if profile.asset_path_suffix(PurePosixPath(candidate).suffix):
        return candidate
    return ""


def _unity_runtime(entry: FileEntry) -> Mapping[str, Any]:
    """Per-file engine runtime detail, whichever engine produced it."""
    for slot in ("unity_runtime", "engine_runtime"):
        value = entry.metadata.get(slot)
        if isinstance(value, Mapping):
            return value
    return {}


def _unity_runtime_project(manifest: Manifest) -> Mapping[str, Any]:
    """Project-level engine runtime summary, whichever engine produced it."""
    for slot in ("unity_runtime", "engine_runtime"):
        value = manifest.project.get(slot)
        if isinstance(value, Mapping):
            return value
    return {}


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
    profile: ProjectKindProfile = UNITY_PROFILE,
) -> bool:
    if not profile.runtime_suffix(PurePosixPath(entry.path).suffix):
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
    if kind == "animation_clip" and isinstance(detail.get("animation_clip"), Mapping):
        return True
    if kind == "material" and isinstance(detail.get("material"), Mapping):
        return True
    if kind == "mesh" and isinstance(detail.get("mesh"), Mapping):
        return True
    if kind == "model" and isinstance(detail.get("model"), Mapping):
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


def _has_unity_runtime_signal(
    entry: FileEntry, manifest: Manifest, profile: ProjectKindProfile = UNITY_PROFILE
) -> bool:
    return _detail_has_unity_runtime_signal(entry, _unity_runtime(entry), manifest, profile)


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
        "animation_clip": "Animation Clip",
        "material": "Material",
        "mesh": "Mesh",
        "model": "FBX Model",
        "texture": "Texture / Sprite",
        "sprite_atlas": "Sprite Atlas",
        "shader": "Shader",
        "audio_clip": "Audio Clip",
        "video_clip": "Video Clip",
        "font": "Font",
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
            f"Animator controller `{name}` defining {layer_count} layer(s), {state_count} state(s)"
        )
    elif kind == "animation_clip":
        clip = detail.get("animation_clip", {})
        rate = clip.get("sample_rate") if isinstance(clip, Mapping) else None
        curve_count = clip.get("curve_count", 0) if isinstance(clip, Mapping) else 0
        lead = f"Animation clip `{name}`"
        if rate is not None:
            lead += f" sampled at {rate} fps"
        lead += f" with {curve_count} serialized curve(s)"
    elif kind == "material":
        material = detail.get("material", {})
        shader = material.get("shader") if isinstance(material, Mapping) else ""
        lead = f"Material `{name}`"
        if shader:
            lead += f" using `{shader}`"
    elif kind == "mesh":
        mesh = detail.get("mesh", {})
        vertices = mesh.get("vertex_count", 0) if isinstance(mesh, Mapping) else 0
        submeshes = mesh.get("submesh_count", 0) if isinstance(mesh, Mapping) else 0
        lead = f"Mesh `{name}` containing {vertices} vertices across {submeshes} submesh(es)"
    elif kind == "model":
        model = detail.get("model", {})
        importer = detail.get("model_importer", {})
        node_count = model.get("node_count", 0) if isinstance(model, Mapping) else 0
        mesh_count = model.get("mesh_count", 0) if isinstance(model, Mapping) else 0
        skeleton = model.get("skeleton", {}) if isinstance(model, Mapping) else {}
        bone_count = skeleton.get("bone_count", 0) if isinstance(skeleton, Mapping) else 0
        clips = importer.get("clips", []) if isinstance(importer, Mapping) else []
        lead = (
            f"FBX model `{name}` defining {node_count} node(s), {mesh_count} mesh(es), "
            f"{bone_count} bone(s), and {len(clips) if isinstance(clips, list) else 0} "
            "Unity clip split(s)"
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

    clip = detail.get("animation_clip")
    if isinstance(clip, Mapping):
        if clip.get("sample_rate") is not None:
            items.append(f"sample rate: `{clip['sample_rate']} fps`")
        if clip.get("curve_count"):
            items.append(f"curves: `{clip['curve_count']}`")
        event_names = [str(value) for value in clip.get("events", []) if value]
        if event_names:
            items.append("animation events: " + ", ".join(f"`{v}`" for v in event_names[:2]))
    material = detail.get("material")
    if isinstance(material, Mapping):
        if material.get("shader"):
            items.append(f"shader: `{material['shader']}`")
        textures = [str(value) for value in material.get("textures", []) if value]
        if textures:
            items.append("textures: " + ", ".join(f"`{v}`" for v in textures[:2]))
        references = []
    mesh = detail.get("mesh")
    if isinstance(mesh, Mapping):
        items.append(
            f"geometry: `{mesh.get('vertex_count', 0)} vertices`, "
            f"`{mesh.get('submesh_count', 0)} submeshes`"
        )
    model = detail.get("model")
    if isinstance(model, Mapping):
        items.append(
            f"FBX: `{model.get('format', 'unknown')} {model.get('fbx_version', 0)}`, "
            f"`{model.get('node_count', 0)} nodes`, `{model.get('mesh_count', 0)} meshes`"
        )
        skeleton = model.get("skeleton", {})
        if isinstance(skeleton, Mapping) and skeleton.get("bone_count"):
            items.append(f"skeleton: `{skeleton['bone_count']} bones`")
        stacks = _runtime_list(model.get("animation_stacks"))
        if stacks:
            items.append(
                "takes: " + ", ".join(f"`{value.get('name', '')}`" for value in stacks[:2])
            )
    importer = detail.get("model_importer")
    if isinstance(importer, Mapping):
        rig = importer.get("rig", {})
        if isinstance(rig, Mapping) and rig.get("animation_type"):
            items.append(f"rig: `{rig['animation_type']}`")
        clips = _runtime_list(importer.get("clips"))
        if clips:
            items.append(
                "Unity clips: " + ", ".join(f"`{value.get('name', '')}`" for value in clips[:2])
            )
    editor_asset = detail.get("editor_asset")
    if isinstance(editor_asset, Mapping):
        facts = editor_asset.get("facts", {})
        if isinstance(facts, Mapping):
            source_width = facts.get("source_width")
            source_height = facts.get("source_height")
            imported_width = facts.get("width")
            imported_height = facts.get("height")
            if source_width and source_height:
                items.append(f"source: `{source_width}×{source_height}`")
            elif imported_width and imported_height:
                items.append(f"size: `{imported_width}×{imported_height}`")
            if (
                imported_width
                and imported_height
                and (imported_width, imported_height) != (source_width, source_height)
            ):
                items.append(f"imported: `{imported_width}×{imported_height}`")
            if facts.get("pixels_per_unit") and facts.get("sprite_mode") not in {None, "None"}:
                items.append(f"PPU: `{facts['pixels_per_unit']}`")
            if facts.get("mipmaps"):
                items.append(f"mipmaps: `{facts['mipmaps']}`")
            if str(facts.get("platform.Android.overridden", "false")).casefold() == "true":
                maximum = facts.get("platform.Android.max_texture_size", "?")
                items.append(f"Android override: `max {maximum}`")
        subassets = _runtime_list(editor_asset.get("subassets"))
        if subassets:
            items.append(
                "subassets: "
                + ", ".join(f"`{value.get('name', '')}`" for value in subassets[:3])
            )

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
    rel_dir: str,
    profile: ProjectKindProfile = UNITY_PROFILE,
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
        f"### {profile.label} runtime assets",
        "",
        "| Asset | Kind | Verified responsibility | Runtime topology and bindings |",
        "|---|---|---|---|",
    ]
    for entry in ranked[:asset_limit]:
        detail = _unity_runtime(entry)
        filename = posixpath.relpath(entry.path, rel_dir or ".")
        destination = _markdown_path(filename)
        lines.append(
            f"| [`{_cell(filename)}`]({destination}) | {_cell(_runtime_kind_label(detail))} | "
            f"{_cell(_runtime_responsibility(entry, detail))} | "
            f"{_cell(_runtime_asset_preview(detail, object_limit))} |"
        )
    if len(ranked) > asset_limit:
        lines.append(
            f"| … | — | {len(ranked) - asset_limit} lower-signal runtime assets omitted "
            "from this token-optimized map. | Use "
            f"`better-context-unity {profile.asset_command} list` or "
            f"`{profile.asset_command} show <project-relative-asset>` for full detail. |"
        )
    lines.extend(
        [
            "",
            "Full hierarchy and serialized evidence: "
            f"`better-context-unity {profile.asset_command} show "
            "<project-relative-asset> --depth -1`.",
            "",
        ]
    )
    return lines


def _asset_path_owner(asset_path: str, directories: set[str]) -> str:
    parent = _parent(asset_path)
    candidates = [
        directory
        for directory in directories
        if not directory or parent == directory or parent.startswith(directory + "/")
    ]
    return max(candidates, key=lambda value: (len(PurePosixPath(value).parts), value))


def _unity_runtime_entries_for_map(
    rel_dir: str,
    directories: set[str],
    manifest: Manifest,
    profile: ProjectKindProfile = UNITY_PROFILE,
) -> list[FileEntry]:
    return [
        entry
        for entry in manifest.files
        if _has_unity_runtime_signal(entry, manifest, profile)
        and _asset_path_owner(entry.path, directories) == rel_dir
    ]


def _unity_asset_path_records(
    rel_dir: str,
    directories: set[str],
    manifest: Manifest,
    profile: ProjectKindProfile = UNITY_PROFILE,
) -> list[tuple[str, str, str]]:
    entries_by_path = {entry.path: entry for entry in manifest.files}
    logical_paths: dict[str, FileEntry] = {}
    for entry in manifest.files:
        logical = _logical_unity_asset_path(entry.path, profile)
        if not logical:
            continue
        if (
            entry.path.endswith(".meta")
            and logical not in entries_by_path
            and not (Path(manifest.meta.root_path) / Path(logical)).is_file()
        ):
            continue
        current = logical_paths.get(logical)
        if current is None or (current.path.endswith(".meta") and not entry.path.endswith(".meta")):
            logical_paths[logical] = entry

    records: list[tuple[str, str, str]] = []
    kind_labels = {
        ".anim": "Animation clip",
        ".asset": "Serialized asset",
        ".controller": "Animator controller",
        ".mat": "Material",
        ".overridecontroller": "Animator override controller",
        ".prefab": "Prefab",
        ".unity": "Scene",
        ".fbx": "Model",
        ".obj": "Model",
        ".blend": "Model",
        ".dae": "Model",
        ".3ds": "Model",
        ".png": "Texture",
        ".jpg": "Texture",
        ".jpeg": "Texture",
        ".tga": "Texture",
        ".psd": "Texture",
        ".exr": "Texture",
        ".hdr": "Texture",
        ".wav": "Audio",
        ".mp3": "Audio",
        ".ogg": "Audio",
        ".mp4": "Video",
    }
    for logical, fallback_entry in sorted(logical_paths.items()):
        asset_entry = entries_by_path.get(logical, fallback_entry)
        if _has_unity_runtime_signal(asset_entry, manifest, profile):
            continue
        if _asset_path_owner(logical, directories) != rel_dir:
            continue
        relative = posixpath.relpath(logical, rel_dir or ".")
        suffix = PurePosixPath(logical).suffix.lower()
        records.append((logical, relative, kind_labels.get(suffix, f"{profile.label} asset")))
    return records


def _unity_asset_paths_section(
    records: list[tuple[str, str, str]], profile: ProjectKindProfile = UNITY_PROFILE
) -> list[str]:
    lines = [
        f"### {profile.label} asset paths",
        "",
        "Path-only navigation for art/media or low-signal serialized assets; no "
        "code-like responsibility is inferred.",
        "",
        "| Asset | Kind |",
        "|---|---|",
    ]
    for _logical, relative, kind in records[:DEFAULT_UNITY_PATH_LIMIT]:
        destination = _markdown_path(relative)
        lines.append(f"| [`{_cell(relative)}`]({destination}) | {_cell(kind)} |")
    if len(records) > DEFAULT_UNITY_PATH_LIMIT:
        lines.append(
            f"| … | {len(records) - DEFAULT_UNITY_PATH_LIMIT} additional paths omitted; "
            "inspect the directory or manifest on demand. |"
        )
    lines.append("")
    return lines


def _cocos_project_overview(project: Mapping[str, Any]) -> list[str]:
    """Verified Cocos facts: engine version, bundle contract, start scene."""
    lines = [
        f"- Cocos Creator `{project.get('creator_version', 'unknown')}`; analyzer: "
        f"`{project.get('analysis_engine', 'unknown')}`."
    ]
    bundles = project.get("bundles") or []
    if isinstance(bundles, list) and bundles:
        rendered = ", ".join(
            f"`{bundle.get('bundle_name')}` ({bundle.get('folder')})"
            for bundle in bundles
            if isinstance(bundle, Mapping)
        )
        lines.append(
            "- Asset bundles (the folder-to-bundle contract `loadBundle` depends on): "
            + rendered
            + "."
        )
    start_scene = project.get("start_scene")
    if start_scene:
        lines.append(f"- Start scene uuid: `{start_scene}`.")
    extensions = project.get("extensions") or []
    if isinstance(extensions, list) and extensions:
        lines.append(
            "- Editor extensions: " + ", ".join(f"`{item}`" for item in extensions) + "."
        )
    return lines


def _root_cocos_runtime(
    manifest: Manifest, profile: ProjectKindProfile = COCOS_PROFILE
) -> list[str]:
    """Root-level Cocos serialized-asset intelligence."""
    runtime = _unity_runtime_project(manifest)
    if not runtime or str(runtime.get("kind", "")) != COCOS_KIND:
        return []
    metrics = runtime.get("metrics") if isinstance(runtime.get("metrics"), Mapping) else {}
    coverage = runtime.get("coverage") if isinstance(runtime.get("coverage"), Mapping) else {}
    index = runtime.get("index") if isinstance(runtime.get("index"), Mapping) else {}
    lines = ["", f"### {profile.label} runtime intelligence", ""]
    lines.append(
        "- "
        + ", ".join(
            [
                f"{metrics.get('scenes', 0)} scenes",
                f"{metrics.get('prefabs', 0)} prefabs",
                f"{metrics.get('animation_clips', 0)} animation clips",
                f"{metrics.get('resolved_scripts', 0)} resolved component scripts",
                f"{metrics.get('unresolved_components', 0)} unresolved component types",
            ]
        )
        + "."
    )
    lines.append(
        f"- Parse coverage: {coverage.get('parsed', 0)}/{coverage.get('candidates', 0)} "
        "candidate serialized assets parsed."
    )
    lines.append(
        f"- Identity index: {index.get('assets_with_uuid', 0)} asset uuid(s), "
        f"{index.get('script_class_ids', 0)} script class-id(s), "
        f"{index.get('ccclass_names', 0)} `@ccclass` name(s)."
    )
    if metrics.get("unresolved_components"):
        lines.append(
            "- An unresolved component type means a missing script, a stale class-id, or a "
            "duplicate `@ccclass`; it renders as `MissingScript` at runtime."
        )
    lines.extend(
        [
            "",
            f"- Browse assets: `better-context-unity {profile.asset_command} list "
            "[--kind KIND] [--limit 50] [--format json|human|markdown]`.",
            f"- Inspect one hierarchy: `better-context-unity {profile.asset_command} show "
            "<project-relative-asset> [--depth 2|-1] [--format ...]`.",
            f"- Inspect resolved components: `better-context-unity {profile.asset_command} "
            "components [--asset PATH] [--type TYPE] [--object PATH] [--format ...]`.",
            "",
        ]
    )
    return lines


def _root_unity_runtime(
    manifest: Manifest, profile: ProjectKindProfile = UNITY_PROFILE
) -> list[str]:
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
                f"{metrics.get('animation_clips', 0)} animation clips",
                f"{metrics.get('materials', 0)} materials",
                f"{metrics.get('meshes', 0)} meshes",
                f"{metrics.get('models', 0)} FBX models",
                f"{metrics.get('textures', 0)} textures",
                f"{metrics.get('sprites', 0)} Sprite subassets",
                f"{metrics.get('sprite_atlases', 0)} Sprite Atlases",
                f"{metrics.get('shaders', 0)} shaders",
                f"{metrics.get('audio_clips', 0)} audio clips",
                f"{metrics.get('video_clips', 0)} video clips",
                f"{metrics.get('game_objects', 0)} GameObjects",
                f"{metrics.get('components', 0)} components",
                f"{metrics.get('resolved_components', 0)} resolved components",
                f"{metrics.get('project_script_usages', metrics.get('script_components', 0))} "
                "project-script usages",
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
    editor_value = runtime.get("editor_snapshot")
    editor = editor_value if isinstance(editor_value, Mapping) else {}
    editor_status = str(editor.get("status", "missing"))
    if editor_status == "fresh":
        editor_coverage = editor.get("coverage", {})
        exported = (
            editor_coverage.get("assets_exported", 0)
            if isinstance(editor_coverage, Mapping)
            else 0
        )
        lines.append(
            f"- Unity Editor snapshot: fresh via `{editor.get('mode', 'unknown')}`; "
            f"{exported} importer/static asset record(s) exported."
        )
    else:
        lines.append(
            f"- Unity Editor snapshot: `{editor_status}`; importer, hidden subasset, and exact "
            "package-component coverage may be incomplete."
        )

    ranked = [
        (entry, detail)
        for entry, detail in _runtime_asset_entries(manifest)
        if _detail_has_unity_runtime_signal(entry, detail, manifest)
    ]
    ranked.sort(key=lambda item: (-_runtime_asset_score(item[0], item[1], manifest), item[0].path))
    if ranked:
        lines.extend(
            [
                "",
                f"#### Key {profile.label} runtime assets",
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
                f"`better-context-unity {profile.asset_command} list --limit 50` |"
            )

    lines.extend(
        [
            "",
            f"- Browse assets: `better-context-unity {profile.asset_command} list "
            "[--kind KIND] [--limit 50] [--format json|human|markdown]`.",
            f"- Inspect one hierarchy: `better-context-unity {profile.asset_command} show "
            "<project-relative-asset> [--depth 2|-1] [--format ...]`.",
            f"- Find persistent calls: `better-context-unity {profile.asset_command} bindings "
            "[--asset PATH] [--type TYPE] [--method METHOD] [--format ...]`.",
            f"- Inspect resolved components: `better-context-unity {profile.asset_command} "
            "components [--asset PATH] [--type TYPE] [--object PATH] [--format ...]`.",
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
    map_filenames: Sequence[str] = DEFAULT_MAP_FILENAMES,
    profile: ProjectKindProfile = UNITY_PROFILE,
) -> None:
    for root_name in sorted(profile.roots):
        root = output_root / root_name
        if not root.is_dir():
            continue
        stale_candidates = [
            target for filename in map_filenames for target in sorted(root.rglob(filename))
        ]
        for target in stale_candidates:
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
    profile: ProjectKindProfile,
    summaries: Mapping[str, str],
    map_filename: str = "AGENTS.md",
) -> str:
    direct_files = [
        entry
        for entry in manifest.files
        if _parent(entry.path) == rel_dir and not is_map_filename(PurePosixPath(entry.path).name)
    ]
    runtime_files = _unity_runtime_entries_for_map(rel_dir, directories, manifest, profile)
    asset_path_records = _unity_asset_path_records(rel_dir, directories, manifest, profile)
    visible_files = [
        entry
        for entry in direct_files
        if not entry.path.endswith(".meta")
        and not _unity_runtime(entry)
        and not _logical_unity_asset_path(entry.path, profile)
    ]
    metadata_count = sum(
        entry.path.endswith(".meta")
        and not is_map_meta_filename(PurePosixPath(entry.path).name)
        for entry in direct_files
    )
    children = sorted(value for value in directories if value and _parent(value) == rel_dir)
    title = (
        f"{profile.label} project map"
        if not rel_dir and profile.is_engine
        else f"Folder map: {rel_dir or 'repository'}"
    )
    lines = [BEGIN, f"## {title}", "", _directory_purpose(rel_dir, manifest, profile), ""]
    if rel_dir in summaries:
        lines.extend([f"**Verified responsibility:** {_summary_cell(summaries[rel_dir])}", ""])

    if not rel_dir:
        lines.extend(_root_intelligence(manifest, profile))
    else:
        lines.extend(_module_intelligence(rel_dir, manifest))

    if children:
        has_summaries = any(child in summaries for child in children)
        header = "| Folder | Purpose | Summary |" if has_summaries else "| Folder | Purpose |"
        divider = "|---|---|---|" if has_summaries else "|---|---|"
        lines.extend(["### Child folders", "", header, divider])
        for child in children:
            name = PurePosixPath(child).name
            destination = quote(name, safe="") + "/" + map_filename
            row = f"| [`{name}/`]({destination}) | {_directory_purpose(child, manifest, profile)}"
            if has_summaries:
                row += f" | {_summary_cell(summaries.get(child, '—'))}"
            lines.append(row + " |")
        lines.append("")

    if runtime_files:
        lines.extend(_unity_runtime_assets_section(runtime_files, manifest, rel_dir, profile))

    if asset_path_records:
        lines.extend(_unity_asset_paths_section(asset_path_records, profile))

    if metadata_count and not visible_files:
        lines.extend(
            [
                f"{profile.label} metadata: {metadata_count} `.meta` sidecar file(s) "
                f"hidden. Never treated as {profile.source_language_label} dependencies.",
                "",
            ]
        )

    if visible_files:
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
            responsibility = summaries.get(entry.path) or _verified_responsibility(entry, profile)
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
                f"| {profile.label} `.meta` files | generated metadata | {metadata_count} "
                "sidecar files are intentionally hidden from the table. | — | Never treated "
                f"as {profile.source_language_label} dependencies. | — |"
            )
        lines.append("")

    lines.extend(_local_calls(rel_dir, manifest))
    lines.extend(_local_asset_references(rel_dir, manifest, profile))
    lines.extend(_local_violations(rel_dir, manifest))

    if rel_dir:
        parent_link = f"../{map_filename}"
        lines.extend([f"Parent map: [`{parent_link}`]({parent_link})", ""])
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


def _directory_purpose(path: str, manifest: Manifest, profile: ProjectKindProfile) -> str:
    name = PurePosixPath(path).name.lower() if path else ""
    ownership = (
        classify_ownership(path.rstrip("/") + "/__context__.cs", profile.kind)
        if path
        else "repository"
    )
    if ownership == "vendor":
        return (
            "Vendor/third-party boundary; inspect as dependency and avoid project "
            "feature edits here."
        )
    if ownership == "generated":
        return (
            "Generated boundary; change the source/generator rather than files under this folder."
        )
    purposes = profile.directory_purposes
    if not path:
        return (
            f"Navigation map for the {profile.label} project."
            if profile.is_engine
            else "Navigation map for the repository."
        )
    prefix = path.rstrip("/") + "/" if path else ""
    source_files = [
        entry
        for entry in manifest.files
        if entry.path.startswith(prefix) and entry.language and not is_map_path(entry.path)
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
            if chunk.type in {"method", "operator"} and chunk.name not in profile.lifecycle_methods
        ]
        operation_text = ""
        if operations:
            unique = list(dict.fromkeys(operations))
            operation_text = "; verified operations include " + ", ".join(unique[:5])
        return f"{profile.label} source module defining {listed}{suffix}{operation_text}."
    files = [
        entry
        for entry in manifest.files
        if entry.path.startswith(prefix) and not is_map_path(entry.path)
    ]
    runtime_assets = [
        (entry, _unity_runtime(entry))
        for entry in files
        if _has_unity_runtime_signal(entry, manifest, profile)
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
        purpose = f"{profile.label} runtime asset module containing " + ", ".join(
            f"{count} {kind}" for kind, count in kinds.most_common(4)
        )
        if scripts:
            purpose += "; verified project scripts include " + ", ".join(scripts[:5])
        return purpose + "."
    asset_paths = {
        logical
        for entry in files
        if (logical := _logical_unity_asset_path(entry.path, profile))
    }
    if asset_paths:
        return (
            f"Path-only navigation for {len(asset_paths)} {profile.label} art/media "
            "asset(s); "
            "no code responsibility is inferred."
        )
    if name in purposes:
        return purposes[name]
    if files:
        kinds = Counter(
            PurePosixPath(entry.path).suffix.lower() or "extensionless" for entry in files
        )
        common = ", ".join(f"{count} `{kind}`" for kind, count in kinds.most_common(3))
        return f"Asset/configuration module containing {common}."
    return f"Repository module at `{path}`."


def _file_role(
    entry: FileEntry,
    graph: DependencyGraph | _EmptyGraph,
    profile: ProjectKindProfile = UNITY_PROFILE,
) -> str:
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
    return profile.file_roles.get(suffix, "Project file.")


def _root_intelligence(
    manifest: Manifest, profile: ProjectKindProfile = UNITY_PROFILE
) -> list[str]:
    project = manifest.project
    metrics = project.get("metrics", {})
    lines = ["### Project overview", ""]
    if project.get("kind") == COCOS_KIND:
        lines.extend(_cocos_project_overview(project))
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
    if profile.is_engine:
        lines.append(
            f"- Exact {profile.label} serialized {profile.serialized_id_label} edges: "
            f"{metrics.get('serialized_dependencies', 0)}; "
            f"project-owned edges: {metrics.get('project_owned_dependencies', 0)}; "
            f"project-owned circular components: {metrics.get('project_owned_cycles', 0)}."
        )
    if profile.kind == COCOS_KIND:
        lines.extend(_root_cocos_runtime(manifest, profile))
    else:
        lines.extend(_root_unity_runtime(manifest, profile))
    lines.extend(_key_files(manifest))
    lines.extend(_architecture_summary(manifest))
    lines.extend(_cycle_summary(manifest))
    lines.extend(_feature_flows(manifest))
    lines.extend(_ownership_summary(manifest, profile))
    lines.extend(_testing_rules(manifest, profile))
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
        if entry.path.startswith(prefix) and entry.language and not is_map_path(entry.path)
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
    ranked.sort(key=lambda item: (-item[1], item[0]))
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
    violations = sorted(
        architecture.get("violations", []),
        key=lambda item: (
            str(item.get("source_path", "")),
            str(item.get("target_path", "")),
            str(item.get("source_layer", "")),
            str(item.get("target_layer", "")),
        ),
    )
    lines = ["### Architecture layers (heuristic)", ""]
    lines.append("- " + ", ".join(f"{name}: {len(layers[name])}" for name in sorted(layers)) + ".")
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
    cycles = sorted(
        (sorted(cycle) for cycle in manifest.project.get("project_cycles", manifest.graph.cycles)),
        key=lambda cycle: tuple(cycle),
    )
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


def _ownership_summary(
    manifest: Manifest, profile: ProjectKindProfile = UNITY_PROFILE
) -> list[str]:
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
    lines.extend([*profile.ownership_notes, ""])
    return lines


def _testing_rules(
    manifest: Manifest, profile: ProjectKindProfile = UNITY_PROFILE
) -> list[str]:
    project = manifest.project
    tests = project.get("test_files", [])
    version = project.get("unity_version", "the recorded Unity version")
    lines = ["### Testing and change rules", ""]
    lines.extend(rule.format(version=version) for rule in profile.testing_rules)
    if tests:
        lines.append(
            "- Detected test files: " + ", ".join(f"`{path}`" for path in tests[:12]) + "."
        )
    else:
        lines.append(profile.no_test_note)
    lines.append("")
    return lines


def _verified_responsibility(
    entry: FileEntry, profile: ProjectKindProfile = UNITY_PROFILE
) -> str:
    ownership = entry.metadata.get("ownership")
    if ownership == "unity-generated":
        return "Unity-generated project/solution file; regenerate instead of hand-editing."
    if ownership == "generated":
        return "Generated content; change its source or generator instead of hand-editing."
    documented = next((chunk.docstring for chunk in entry.chunks if chunk.docstring), None)
    if documented:
        return str(documented)
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
                dict.fromkeys(name for name in methods if name in profile.lifecycle_methods)
            )
            operations = list(
                dict.fromkeys(
                    name for name in methods if name not in profile.lifecycle_methods
                )
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


def _local_asset_references(
    rel_dir: str, manifest: Manifest, profile: ProjectKindProfile = UNITY_PROFILE
) -> list[str]:
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
    lines = [f"### {profile.label} runtime references", ""]
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
    violations = sorted(
        (
            item
            for item in manifest.graph.architecture.get("violations", [])
            if _parent(item.get("source_path", "")) == rel_dir
        ),
        key=lambda item: (
            str(item.get("source_path", "")),
            str(item.get("target_path", "")),
            str(item.get("message", "")),
        ),
    )
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
    directories = _collect_directories(manifest, resolve_profile(root, manifest), max_depth)
    files = {
        entry.path
        for entry in manifest.files
        if _parent(entry.path) in directories
        and not is_map_filename(PurePosixPath(entry.path).name)
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
    "DEFAULT_MAP_FILENAMES",
    "END",
    "MAP_FILENAMES",
    "MAX_SUMMARY_LENGTH",
    "MapResult",
    "SUMMARY_FILE",
    "generate_agents_map",
    "is_map_filename",
    "is_map_meta_filename",
    "is_map_path",
    "load_summaries",
    "normalize_summary_path",
    "parse_summary_assignment",
    "remove_managed_map",
    "resolve_map_filenames",
    "resolve_profile",
    "save_summaries",
    "summary_targets",
]
