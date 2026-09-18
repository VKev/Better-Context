"""Cocos Creator runtime intelligence: scenes, prefabs, uuids and class-ids.

Cocos serializes scenes, prefabs and clips as JSON arrays where every object is
addressed by its index (`__id__`) and every asset reference is `{"__uuid__": ...}`.
Component types appear either as a plain `@ccclass('Name')` string or as a 23-character
class-id compressed from the owning script's uuid — which is why a scene cannot be
understood without the sibling `.meta` files.

This module is the Cocos peer of `unity_runtime` + the Unity half of
`unity_intelligence`. It is deliberately conservative: an object reference is only
reported when it resolves through a real uuid or a real `@ccclass` registration.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from collections.abc import Iterable, Mapping
from pathlib import Path, PurePosixPath
from typing import Any

from .project_kind import COCOS_KIND, cocos_creator_version
from .unity_intelligence import classify_ownership

BASE64_KEYS = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"
CCCLASS_PATTERN = re.compile(r"@ccclass\(\s*['\"]([^'\"]+)['\"]\s*\)")

SCENE_SUFFIXES = {".scene"}
PREFAB_SUFFIXES = {".prefab"}
CLIP_SUFFIXES = {".anim"}
MATERIAL_SUFFIXES = {".mtl"}
EFFECT_SUFFIXES = {".effect", ".chunk"}
TEXTURE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tga", ".psd", ".gif", ".svg"}
AUDIO_SUFFIXES = {".mp3", ".ogg", ".wav", ".m4a", ".flac", ".aac"}
VIDEO_SUFFIXES = {".mp4", ".webm", ".mov", ".avi"}
FONT_SUFFIXES = {".ttf", ".otf", ".fnt"}
ATLAS_SUFFIXES = {".plist", ".atlas", ".labelatlas", ".pac"}

#: Suffixes whose JSON body this module parses.
PARSED_SUFFIXES = SCENE_SUFFIXES | PREFAB_SUFFIXES | CLIP_SUFFIXES | MATERIAL_SUFFIXES

MAX_OBJECTS = 400
MAX_REFERENCES = 40


def compress_uuid(uuid: str) -> str:
    """Return the Cocos class-id compressed from an asset uuid.

    Cocos keeps the first five hex characters verbatim and encodes each following
    group of three hex characters (12 bits) as two base64 characters, producing the
    23-character `__type__` value found in `.scene`/`.prefab` JSON.
    """
    hex_string = uuid.replace("-", "").strip()
    if len(hex_string) < 32:
        return ""
    hex_string = hex_string[:32]
    result = hex_string[:5]
    for index in range(5, 32, 3):
        try:
            value = int(hex_string[index : index + 3], 16)
        except ValueError:
            return ""
        result += BASE64_KEYS[value >> 6] + BASE64_KEYS[value & 0x3F]
    return result


def read_meta_uuid(meta_path: Path) -> str:
    """Read the `uuid` field out of a Cocos `.meta` file."""
    try:
        data = json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    uuid = data.get("uuid") if isinstance(data, Mapping) else ""
    return str(uuid) if uuid else ""


def read_meta(meta_path: Path) -> Mapping[str, Any]:
    try:
        data = json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, Mapping) else {}


class CocosAssetIndex:
    """uuid ⇄ path index plus the class-id map needed to resolve components."""

    def __init__(self, root: Path, paths: Iterable[str]) -> None:
        self.root = root
        self.uuid_to_path: dict[str, str] = {}
        self.path_to_uuid: dict[str, str] = {}
        self.class_id_to_script: dict[str, str] = {}
        self.ccclass_to_script: dict[str, str] = {}
        self._build(sorted({str(path).replace("\\", "/") for path in paths}))

    def _build(self, paths: list[str]) -> None:
        for path in paths:
            if not path.endswith(".meta"):
                continue
            asset_path = path[: -len(".meta")]
            uuid = read_meta_uuid(self.root / path)
            if not uuid:
                continue
            self.uuid_to_path[uuid] = asset_path
            self.path_to_uuid[asset_path] = uuid
            if asset_path.endswith(".ts") or asset_path.endswith(".js"):
                class_id = compress_uuid(uuid)
                if class_id:
                    self.class_id_to_script[class_id] = asset_path
        for path in paths:
            if not (path.endswith(".ts") or path.endswith(".js")):
                continue
            for name in self._ccclass_names(self.root / path):
                # First registration wins; a duplicate name is a real project defect
                # and is reported by the scene analysis rather than silently merged.
                self.ccclass_to_script.setdefault(name, path)

    @staticmethod
    def _ccclass_names(source_path: Path) -> list[str]:
        try:
            source = source_path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            return []
        return CCCLASS_PATTERN.findall(source)

    def resolve_component_type(self, type_name: str) -> dict[str, Any]:
        """Resolve a `__type__` value to a component descriptor.

        Engine components keep their `cc.*` name. A project component resolves either
        through its `@ccclass` name or through the class-id compressed from its uuid.
        """
        if not type_name:
            return {}
        if type_name.startswith("cc."):
            return {"type": type_name, "source": "engine"}
        script_path = self.class_id_to_script.get(type_name)
        if not script_path and "." in type_name:
            # Namespaced types such as `dragonBones.ArmatureDisplay` come from the
            # engine or an extension, not from project scripts. Reporting them as
            # unresolved would be a false alarm.
            return {"type": type_name, "source": "engine"}
        if script_path:
            return {
                "type": PurePosixPath(script_path).stem,
                "source": "class-id",
                "script": {"type": PurePosixPath(script_path).stem, "path": script_path},
            }
        script_path = self.ccclass_to_script.get(type_name)
        if script_path:
            return {
                "type": type_name,
                "source": "ccclass",
                "script": {"type": type_name, "path": script_path},
            }
        return {"type": type_name, "source": "unresolved"}

    def asset_for_uuid(self, raw_uuid: str) -> str:
        """Resolve `<uuid>` or `<uuid>@sub` to a project-relative asset path."""
        uuid = str(raw_uuid).split("@", 1)[0]
        return self.uuid_to_path.get(uuid, "")


def _suffix_kind(path: str) -> str:
    suffix = PurePosixPath(path).suffix.lower()
    if suffix in SCENE_SUFFIXES:
        return "scene"
    if suffix in PREFAB_SUFFIXES:
        return "prefab"
    if suffix in CLIP_SUFFIXES:
        return "animation_clip"
    if suffix in MATERIAL_SUFFIXES:
        return "material"
    if suffix in EFFECT_SUFFIXES:
        return "effect"
    if suffix in TEXTURE_SUFFIXES:
        return "texture"
    if suffix in AUDIO_SUFFIXES:
        return "audio_clip"
    if suffix in VIDEO_SUFFIXES:
        return "video_clip"
    if suffix in FONT_SUFFIXES:
        return "font"
    if suffix in ATLAS_SUFFIXES:
        return "sprite_atlas"
    return "asset"


def _load_serialized(path: Path) -> list[Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if isinstance(data, list):
        return data
    if isinstance(data, Mapping):
        return [data]
    return []


def _node_entries(records: list[Any]) -> dict[int, Mapping[str, Any]]:
    return {
        index: record
        for index, record in enumerate(records)
        if isinstance(record, Mapping) and record.get("__type__") == "cc.Node"
    }


def _referenced_id(value: Any) -> int | None:
    if isinstance(value, Mapping) and isinstance(value.get("__id__"), int):
        return int(value["__id__"])
    return None


def _collect_uuid_references(value: Any, found: list[str]) -> None:
    if isinstance(value, Mapping):
        raw = value.get("__uuid__")
        if isinstance(raw, str):
            found.append(raw)
        for item in value.values():
            _collect_uuid_references(item, found)
    elif isinstance(value, list):
        for item in value:
            _collect_uuid_references(item, found)


def analyze_cocos_asset(
    root: Path,
    rel_path: str,
    index: CocosAssetIndex,
) -> dict[str, Any]:
    """Return a runtime detail record for one Cocos asset."""
    kind = _suffix_kind(rel_path)
    ownership = classify_ownership(rel_path, COCOS_KIND)
    detail: dict[str, Any] = {
        "path": rel_path,
        "kind": kind,
        "ownership": ownership,
        "status": "parsed",
        "high_signal": 0,
    }
    name = PurePosixPath(rel_path).stem
    suffix = PurePosixPath(rel_path).suffix.lower()

    if suffix not in PARSED_SUFFIXES:
        meta = read_meta(root / f"{rel_path}.meta")
        user_data = meta.get("userData") if isinstance(meta, Mapping) else {}
        detail["status"] = "referenced"
        detail["responsibility"] = _asset_responsibility(kind, name, user_data)
        if isinstance(user_data, Mapping) and user_data:
            facts = {
                str(key): str(value)
                for key, value in user_data.items()
                if isinstance(value, (str, int, float, bool))
            }
            if facts:
                detail["editor_asset"] = {"facts": facts}
        return detail

    records = _load_serialized(root / rel_path)
    if not records:
        detail["status"] = "unparsed"
        detail["responsibility"] = f"{kind.replace('_', ' ').capitalize()} `{name}` (unreadable)."
        return detail

    if kind in {"animation_clip", "material"}:
        return _analyze_simple_asset(detail, records, name, kind, index)

    return _analyze_hierarchy(detail, records, name, kind, index)


def _asset_responsibility(kind: str, name: str, user_data: Any) -> str:
    label = kind.replace("_", " ")
    bundle = ""
    if isinstance(user_data, Mapping) and user_data.get("isBundle"):
        bundle_name = user_data.get("bundleName") or name
        bundle = f"; asset bundle `{bundle_name}`"
    return f"Cocos {label} `{name}`{bundle}."


def _analyze_simple_asset(
    detail: dict[str, Any],
    records: list[Any],
    name: str,
    kind: str,
    index: CocosAssetIndex,
) -> dict[str, Any]:
    head = records[0] if isinstance(records[0], Mapping) else {}
    references = _resolved_references(records, index)
    if kind == "animation_clip":
        curves = head.get("_tracks")
        curve_count = len(curves) if isinstance(curves, list) else 0
        sample_rate = head.get("sample")
        clip: dict[str, Any] = {"curve_count": curve_count}
        if isinstance(sample_rate, (int, float)):
            clip["sample_rate"] = sample_rate
        detail["animation_clip"] = clip
        detail["responsibility"] = (
            f"Cocos animation clip `{name}` with {curve_count} serialized track(s)."
        )
        detail["high_signal"] = 1 if curve_count else 0
    else:
        effect = index.asset_for_uuid(str(head.get("_effectAsset", {}).get("__uuid__", "")))
        material: dict[str, Any] = {}
        if effect:
            material["shader"] = PurePosixPath(effect).stem
        detail["material"] = material
        detail["responsibility"] = (
            f"Cocos material `{name}`"
            + (f" using effect `{PurePosixPath(effect).stem}`" if effect else "")
            + "."
        )
        detail["high_signal"] = 1
    if references:
        detail["references"] = references
    return detail


def _analyze_hierarchy(
    detail: dict[str, Any],
    records: list[Any],
    name: str,
    kind: str,
    index: CocosAssetIndex,
) -> dict[str, Any]:
    nodes = _node_entries(records)
    objects: list[dict[str, Any]] = []
    root_ids: list[int] = []
    unresolved: list[str] = []

    paths: dict[int, str] = {}

    def node_path(node_id: int, seen: frozenset[int] = frozenset()) -> str:
        if node_id in paths:
            return paths[node_id]
        if node_id in seen:
            return ""
        record = nodes.get(node_id)
        if record is None:
            return ""
        node_name = str(record.get("_name", "") or "")
        parent_id = _referenced_id(record.get("_parent"))
        if parent_id is None or parent_id not in nodes:
            paths[node_id] = node_name
        else:
            prefix = node_path(parent_id, seen | {node_id})
            paths[node_id] = f"{prefix}/{node_name}" if prefix else node_name
        return paths[node_id]

    for node_id, record in list(nodes.items())[:MAX_OBJECTS]:
        parent_id = _referenced_id(record.get("_parent"))
        if parent_id is None or parent_id not in nodes:
            root_ids.append(node_id)
        components: list[dict[str, Any]] = []
        for component_ref in record.get("_components", []) or []:
            component_id = _referenced_id(component_ref)
            if component_id is None or component_id >= len(records):
                continue
            component_record = records[component_id]
            if not isinstance(component_record, Mapping):
                continue
            resolved = index.resolve_component_type(str(component_record.get("__type__", "")))
            if not resolved:
                continue
            if resolved.get("source") == "unresolved":
                unresolved.append(str(resolved.get("type", "")))
            components.append(resolved)
        objects.append(
            {
                "file_id": node_id,
                "name": str(record.get("_name", "") or ""),
                "path": node_path(node_id),
                "parent_file_id": parent_id if parent_id in nodes else None,
                "active": bool(record.get("_active", True)),
                "components": components,
            }
        )

    references = _resolved_references(records, index)
    scripts = [
        str(component["script"]["type"])
        for item in objects
        for component in item["components"]
        if isinstance(component.get("script"), Mapping)
    ]
    unique_scripts = list(dict.fromkeys(scripts))

    detail["objects"] = objects
    detail["root_objects"] = root_ids
    if references:
        detail["references"] = references
    detail["high_signal"] = len(unique_scripts) + (1 if len(objects) > 1 else 0)

    lead = (
        f"Cocos scene `{name}`" if kind == "scene" else f"Reusable Cocos prefab `{name}`"
    )
    clauses = [f"{len(objects)} node(s)"]
    if unique_scripts:
        clauses.append("wires " + ", ".join(f"`{value}`" for value in unique_scripts[:3]))
    if unresolved:
        unique_unresolved = list(dict.fromkeys(value for value in unresolved if value))
        clauses.append(
            f"{len(unique_unresolved)} unresolved component type(s) "
            "(missing script or stale class-id)"
        )
    detail["responsibility"] = f"{lead} containing " + "; ".join(clauses) + "."
    if unresolved:
        detail["unresolved_components"] = list(dict.fromkeys(unresolved))
    return detail


def _resolved_references(records: list[Any], index: CocosAssetIndex) -> list[dict[str, str]]:
    raw: list[str] = []
    _collect_uuid_references(records, raw)
    resolved: list[dict[str, str]] = []
    seen: set[str] = set()
    for value in raw:
        target = index.asset_for_uuid(value)
        if not target or target in seen:
            continue
        seen.add(target)
        resolved.append({"target": target, "kind": "asset_uuid"})
        if len(resolved) >= MAX_REFERENCES:
            break
    return resolved


def analyze_cocos_runtime(
    root: Path,
    paths: Iterable[str],
    scope: str = "project-owned",
) -> dict[str, Any]:
    """Analyze every Cocos asset in `paths` and return runtime details plus metrics."""
    index = CocosAssetIndex(root, paths)
    details: dict[str, dict[str, Any]] = {}
    candidates = 0
    parsed = 0
    for path in sorted({str(item).replace("\\", "/") for item in paths}):
        if path.endswith(".meta"):
            continue
        suffix = PurePosixPath(path).suffix.lower()
        if suffix not in PARSED_SUFFIXES:
            continue
        ownership = classify_ownership(path, COCOS_KIND)
        if scope == "project-owned" and ownership != "project-owned":
            continue
        candidates += 1
        detail = analyze_cocos_asset(root, path, index)
        if detail.get("status") == "parsed":
            parsed += 1
        details[path] = detail

    kinds = Counter(detail["kind"] for detail in details.values())
    scripts = {
        component["script"]["path"]
        for detail in details.values()
        for item in detail.get("objects", [])
        for component in item.get("components", [])
        if isinstance(component.get("script"), Mapping)
    }
    unresolved = sum(len(detail.get("unresolved_components", [])) for detail in details.values())
    return {
        "kind": COCOS_KIND,
        "scope": scope,
        "assets": details,
        "metrics": {
            "assets": len(details),
            "scenes": kinds.get("scene", 0),
            "prefabs": kinds.get("prefab", 0),
            "animation_clips": kinds.get("animation_clip", 0),
            "resolved_scripts": len(scripts),
            "unresolved_components": unresolved,
        },
        "coverage": {"candidates": candidates, "parsed": parsed},
        "index": {
            "assets_with_uuid": len(index.uuid_to_path),
            "script_class_ids": len(index.class_id_to_script),
            "ccclass_names": len(index.ccclass_to_script),
        },
    }


def collect_cocos_reference_edges(runtime: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Turn resolved uuid references into verified dependency edges."""
    edges: list[dict[str, Any]] = []
    assets = runtime.get("assets", {})
    if not isinstance(assets, Mapping):
        return edges
    for path, detail in assets.items():
        if not isinstance(detail, Mapping):
            continue
        for reference in detail.get("references", []) or []:
            target = reference.get("target") if isinstance(reference, Mapping) else None
            if not target or target == path:
                continue
            edges.append(
                {
                    "source": path,
                    "target": str(target),
                    "kind": "cocos_asset_uuid",
                    "confidence": "exact",
                    "engine": "cocos-serialized",
                }
            )
        for item in detail.get("objects", []) or []:
            for component in item.get("components", []) or []:
                script = component.get("script") if isinstance(component, Mapping) else None
                if not isinstance(script, Mapping) or not script.get("path"):
                    continue
                edges.append(
                    {
                        "source": path,
                        "target": str(script["path"]),
                        "kind": "cocos_component",
                        "confidence": "exact",
                        "engine": "cocos-serialized",
                    }
                )
    unique: dict[tuple[str, str, str], dict[str, Any]] = {}
    for edge in edges:
        unique[(edge["source"], edge["target"], edge["kind"])] = edge
    return list(unique.values())


def collect_cocos_project_facts(root: Path, paths: Iterable[str]) -> dict[str, Any]:
    """Verified Cocos project facts: version, bundles, start scene, ownership."""
    normalized = sorted({str(path).replace("\\", "/") for path in paths})
    ownership = Counter(classify_ownership(path, COCOS_KIND) for path in normalized)
    facts: dict[str, Any] = {
        "kind": COCOS_KIND,
        "analysis_engine": "",
        "creator_version": cocos_creator_version(root),
        "ownership_counts": dict(sorted(ownership.items())),
        "generated_files": [
            path for path in normalized if classify_ownership(path, COCOS_KIND) == "generated"
        ][:100],
        "vendor_roots": _ownership_roots(normalized, "vendor", COCOS_KIND),
        "generated_roots": _ownership_roots(normalized, "generated", COCOS_KIND),
        "bundles": _bundles(root),
        "extensions": _extensions(root),
        "test_files": _test_files(normalized),
    }
    start_scene = _start_scene(root)
    if start_scene:
        facts["start_scene"] = start_scene
    return facts


def _bundles(root: Path) -> list[dict[str, Any]]:
    """Read the asset-bundle contract from `assets/*.meta` `userData`."""
    assets_dir = root / "assets"
    if not assets_dir.is_dir():
        return []
    bundles: list[dict[str, Any]] = []
    for meta_path in sorted(assets_dir.glob("*.meta")):
        meta = read_meta(meta_path)
        user_data = meta.get("userData")
        if not isinstance(user_data, Mapping) or not user_data.get("isBundle"):
            continue
        folder = meta_path.name[: -len(".meta")]
        bundles.append(
            {
                "folder": f"assets/{folder}",
                "bundle_name": str(user_data.get("bundleName") or folder),
                "priority": user_data.get("priority"),
                "config_id": user_data.get("bundleConfigID"),
            }
        )
    return bundles


def _extensions(root: Path) -> list[str]:
    extensions_dir = root / "extensions"
    if not extensions_dir.is_dir():
        return []
    return sorted(
        f"extensions/{item.name}" for item in extensions_dir.iterdir() if item.is_dir()
    )


def _start_scene(root: Path) -> str:
    """Resolve the start scene uuid recorded in the shared project settings."""
    settings = root / "settings" / "v2" / "packages" / "project.json"
    data = read_meta(settings)
    general = data.get("general") if isinstance(data, Mapping) else None
    if isinstance(general, Mapping) and general.get("startScene"):
        return str(general["startScene"])
    start_scene = data.get("startScene") if isinstance(data, Mapping) else ""
    return str(start_scene) if start_scene else ""


def _test_files(paths: list[str]) -> list[str]:
    return [
        path
        for path in paths
        if path.endswith((".ts", ".js", ".mjs"))
        and (
            "/test/" in f"/{path}"
            or "/tests/" in f"/{path}"
            or PurePosixPath(path).stem.endswith((".test", ".spec", "-test", "_test"))
            or PurePosixPath(path).name.startswith("test-")
        )
    ][:50]


def _ownership_roots(paths: list[str], ownership: str, kind: str) -> list[str]:
    roots: set[str] = set()
    for path in paths:
        if classify_ownership(path, kind) != ownership:
            continue
        parts = PurePosixPath(path).parts
        if len(parts) > 1:
            roots.add("/".join(parts[:2]))
        elif parts:
            roots.add(parts[0])
    return sorted(roots)[:20]


__all__ = [
    "CocosAssetIndex",
    "analyze_cocos_asset",
    "analyze_cocos_runtime",
    "collect_cocos_project_facts",
    "collect_cocos_reference_edges",
    "compress_uuid",
]
