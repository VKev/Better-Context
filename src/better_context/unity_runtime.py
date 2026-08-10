"""Structured Unity YAML runtime-object intelligence.

The parser intentionally understands only Unity's serialized YAML envelope and
well-known fields.  It does not attempt to be a general YAML parser.  That keeps
quoted strings and comments from becoming dependency evidence and lets every
edge retain the exact serialized field that produced it.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

from .fbx_runtime import inspect_fbx
from .unity_intelligence import classify_ownership

_ASSET_SUFFIXES = {
    ".aif",
    ".aiff",
    ".anim",
    ".asset",
    ".avi",
    ".bmp",
    ".controller",
    ".cubemap",
    ".exr",
    ".fbx",
    ".flac",
    ".gif",
    ".hdr",
    ".jpeg",
    ".jpg",
    ".lighting",
    ".mat",
    ".mixer",
    ".mov",
    ".mp3",
    ".mp4",
    ".ogg",
    ".otf",
    ".overridecontroller",
    ".physicsmaterial2d",
    ".physicmaterial",
    ".playable",
    ".png",
    ".prefab",
    ".psd",
    ".rendertexture",
    ".shader",
    ".shadergraph",
    ".shadersubgraph",
    ".spriteatlas",
    ".svg",
    ".terrainlayer",
    ".tga",
    ".tif",
    ".tiff",
    ".ttf",
    ".unity",
    ".wav",
    ".webm",
}
_YAML_SUFFIXES = {
    ".anim",
    ".asset",
    ".controller",
    ".cubemap",
    ".lighting",
    ".mat",
    ".mixer",
    ".overridecontroller",
    ".physicsmaterial2d",
    ".physicmaterial",
    ".playable",
    ".prefab",
    ".rendertexture",
    ".spriteatlas",
    ".terrainlayer",
    ".unity",
}
_DOCUMENT_HEADER = re.compile(
    r"^---\s+!u!(?P<class_id>-?\d+)\s+&(?P<file_id>-?\d+)"
    r"(?P<stripped>\s+stripped)?\s*$"
)
_TYPE_LINE = re.compile(r"^(?P<name>[A-Za-z_][A-Za-z0-9_]*):\s*$")
_FIELD = re.compile(
    r"^(?P<indent>\s*)(?P<key>[A-Za-z_][A-Za-z0-9_ ]*):\s*(?P<value>.*)$"
)
_LIST_FIELD = re.compile(
    r"^(?P<indent>\s*)-\s+(?P<key>[A-Za-z_][A-Za-z0-9_ ]*):\s*(?P<value>.*)$"
)
_BARE_LIST = re.compile(r"^(?P<indent>\s*)-\s+(?P<value>\{.*\})\s*$")
_BARE_LIST_START = re.compile(r"^(?P<indent>\s*)-\s+(?P<value>\{.*)$")
_META_GUID = re.compile(r"^guid:\s*([0-9a-fA-F]{32})\s*$", re.MULTILINE)
_GUID = re.compile(r"^[0-9a-fA-F]{32}$")
_CLASS_NAMES = {
    1: "GameObject",
    4: "Transform",
    21: "Material",
    43: "Mesh",
    74: "AnimationClip",
    91: "AnimatorController",
    95: "Animator",
    1001: "PrefabInstance",
    1101: "AnimatorStateTransition",
    1102: "AnimatorState",
    1107: "AnimatorStateMachine",
    114: "MonoBehaviour",
    206: "BlendTree",
    224: "RectTransform",
}
_ANIMATOR_PARAMETER_TYPES = {1: "float", 3: "int", 4: "bool", 9: "trigger"}
_COMPONENT_FIELDS: dict[str, tuple[str, ...]] = {
    "Transform": ("m_LocalPosition", "m_LocalRotation", "m_LocalScale"),
    "RectTransform": (
        "m_AnchorMin",
        "m_AnchorMax",
        "m_AnchoredPosition",
        "m_SizeDelta",
        "m_Pivot",
    ),
    "MeshFilter": ("m_Mesh",),
    "MeshRenderer": ("m_Enabled", "m_CastShadows", "m_ReceiveShadows", "m_Materials"),
    "SkinnedMeshRenderer": (
        "m_Enabled",
        "m_Mesh",
        "m_RootBone",
        "m_Materials",
        "m_UpdateWhenOffscreen",
    ),
    "LODGroup": ("m_Enabled", "m_Size", "m_LocalReferencePoint", "m_FadeMode"),
    "Rigidbody": ("m_Mass", "m_Drag", "m_AngularDrag", "m_UseGravity", "m_IsKinematic"),
    "Rigidbody2D": ("m_BodyType", "m_Mass", "m_LinearDrag", "m_GravityScale"),
    "BoxCollider": ("m_Enabled", "m_IsTrigger", "m_Material", "m_Center", "m_Size"),
    "SphereCollider": ("m_Enabled", "m_IsTrigger", "m_Material", "m_Center", "m_Radius"),
    "CapsuleCollider": (
        "m_Enabled",
        "m_IsTrigger",
        "m_Material",
        "m_Center",
        "m_Radius",
        "m_Height",
        "m_Direction",
    ),
    "MeshCollider": ("m_Enabled", "m_IsTrigger", "m_Material", "m_Convex", "m_Mesh"),
    "Animator": ("m_Enabled", "m_Avatar", "m_Controller", "m_CullingMode", "m_UpdateMode"),
    "Animation": ("m_Enabled", "m_Animation", "m_WrapMode", "m_PlayAutomatically"),
    "NavMeshAgent": ("m_Enabled", "m_Radius", "m_Speed", "m_Acceleration", "m_StoppingDistance"),
    "NavMeshObstacle": ("m_Enabled", "m_Shape", "m_Carving", "m_Size", "m_Center"),
    "Camera": ("m_Enabled", "m_ClearFlags", "near clip plane", "far clip plane", "field of view"),
    "Light": ("m_Enabled", "m_Type", "m_Color", "m_Intensity", "m_Range", "m_SpotAngle"),
    "ReflectionProbe": ("m_Enabled", "m_Type", "m_Mode", "m_Importance", "m_BoxSize"),
    "AudioSource": (
        "m_Enabled",
        "m_audioClip",
        "m_PlayOnAwake",
        "m_Volume",
        "m_Loop",
        "m_SpatialBlend",
    ),
    "ParticleSystem": ("m_Enabled", "lengthInSec", "simulationSpeed", "looping", "playOnAwake"),
    "Canvas": ("m_Enabled", "m_RenderMode", "m_Camera", "m_PlaneDistance", "m_SortingOrder"),
    "CanvasGroup": ("m_Enabled", "m_Alpha", "m_Interactable", "m_BlocksRaycasts"),
    "Image": ("m_Enabled", "m_Sprite", "m_Type", "m_PreserveAspect", "m_FillMethod", "m_Color"),
    "RawImage": ("m_Enabled", "m_Texture", "m_UVRect", "m_Color"),
    "Button": ("m_Enabled", "m_Interactable", "m_Transition", "m_TargetGraphic", "m_OnClick"),
    "Selectable": ("m_Enabled", "m_Interactable", "m_Transition", "m_TargetGraphic"),
    "Text": ("m_Enabled", "m_Text", "m_FontData", "m_Color"),
    "TMP_Text": (
        "m_Enabled",
        "m_text",
        "m_fontAsset",
        "m_fontSize",
        "m_color",
        "m_enableWordWrapping",
    ),
    "TextMeshProUGUI": ("m_Enabled", "m_text", "m_fontAsset", "m_fontSize", "m_color"),
    "LayoutGroup": ("m_Enabled", "m_Padding", "m_ChildAlignment", "m_Spacing"),
    "HorizontalLayoutGroup": ("m_Enabled", "m_Padding", "m_ChildAlignment", "m_Spacing"),
    "VerticalLayoutGroup": ("m_Enabled", "m_Padding", "m_ChildAlignment", "m_Spacing"),
    "GridLayoutGroup": (
        "m_Enabled",
        "m_CellSize",
        "m_Spacing",
        "m_Constraint",
        "m_ConstraintCount",
    ),
    "ScrollRect": ("m_Enabled", "m_Content", "m_Viewport", "m_Horizontal", "m_Vertical"),
    "Slider": (
        "m_Enabled",
        "m_MinValue",
        "m_MaxValue",
        "m_Value",
        "m_WholeNumbers",
        "m_OnValueChanged",
    ),
    "Toggle": ("m_Enabled", "m_IsOn", "m_Graphic", "m_Group", "onValueChanged"),
    "PlayableDirector": (
        "m_Enabled",
        "m_PlayableAsset",
        "m_InitialState",
        "m_WrapMode",
        "m_DirectorUpdateMode",
    ),
}
_BOOLEAN_COMPONENT_FIELDS = {
    "looping",
    "m_BlocksRaycasts",
    "m_Carving",
    "m_Convex",
    "m_Enabled",
    "m_Horizontal",
    "m_Interactable",
    "m_IsKinematic",
    "m_IsOn",
    "m_IsTrigger",
    "m_Loop",
    "m_PlayAutomatically",
    "m_PlayOnAwake",
    "m_PreserveAspect",
    "m_UpdateWhenOffscreen",
    "m_UseGravity",
    "m_Vertical",
    "m_WholeNumbers",
    "m_enableWordWrapping",
    "playOnAwake",
}
_GENERIC_COMPONENT_SKIP_FIELDS = {
    "m_CorrespondingSourceObject",
    "m_GameObject",
    "m_ObjectHideFlags",
    "m_PrefabAsset",
    "m_PrefabInstance",
    "m_Script",
}


@dataclass
class UnityRuntimeAnalysis:
    """Normalized Unity data ready for the manifest, graph, and CLI."""

    assets: dict[str, dict[str, Any]] = field(default_factory=dict)
    edge_details: list[dict[str, Any]] = field(default_factory=list)
    call_graph: list[dict[str, Any]] = field(default_factory=list)
    summary: dict[str, Any] = field(default_factory=dict)
    errors: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class _Document:
    class_id: int
    file_id: str
    stripped: bool
    type_name: str
    lines: list[tuple[int, str]]


def analyze_unity_runtime(
    root: Path,
    inventory: Any,
    file_entries: Iterable[Any],
    scope: str = "project-owned",
    editor_snapshot: dict[str, Any] | None = None,
) -> UnityRuntimeAnalysis:
    """Analyze serialized Unity runtime assets using exact GUID and Roslyn evidence.

    ``file_entries`` must be the already parsed manifest entries.  In
    particular, C# type identity is accepted only from chunks whose
    ``metadata['unity_type']`` was produced by Roslyn.
    """
    entries = list(file_entries)
    entries_by_path = {_normalize(item.path): item for item in entries}
    inventory_by_path = {_normalize(item.path): item for item in inventory.files}
    # The general source scanner enforces a small text-file budget.  Unity
    # scenes routinely exceed it, while still being valid streamed YAML.  Its
    # explicit skipped lists retain ignore decisions, so only known non-ignored
    # runtime assets are admitted here.
    for attribute in (
        "skipped_too_large",
        "skipped_binary",
        "skipped_permission",
        "skipped_read_error",
    ):
        for raw_path in getattr(inventory, attribute, []):
            path = _normalize(str(raw_path))
            if PurePosixPath(path).suffix.lower() in _ASSET_SUFFIXES:
                inventory_by_path.setdefault(path, None)
    guid_to_assets = _build_guid_index(inventory_by_path)
    editor_assets = (
        editor_snapshot.get("assets_by_path", {})
        if isinstance(editor_snapshot, dict)
        else {}
    )
    editor_scripts = (
        editor_snapshot.get("scripts_by_guid", {})
        if isinstance(editor_snapshot, dict)
        else {}
    )
    for editor_path, editor_asset in editor_assets.items():
        if not isinstance(editor_asset, dict):
            continue
        guid = str(editor_asset.get("guid", "")).lower()
        if _GUID.fullmatch(guid):
            guid_to_assets.setdefault(guid, []).append(_normalize(editor_path))
    for guid, script in editor_scripts.items():
        path = _normalize(str(script.get("path", ""))) if isinstance(script, dict) else ""
        if path and _GUID.fullmatch(guid):
            guid_to_assets.setdefault(guid, []).append(path)
    guid_to_assets = {
        guid: sorted(set(paths)) for guid, paths in guid_to_assets.items()
    }
    script_symbols = _build_script_symbol_index(entries_by_path)

    analysis = UnityRuntimeAnalysis()
    candidates = []
    skipped_non_owned = 0
    for path, item in inventory_by_path.items():
        if PurePosixPath(path).suffix.lower() not in _ASSET_SUFFIXES:
            continue
        ownership = _ownership(path, entries_by_path.get(path))
        if scope != "all" and ownership != scope:
            skipped_non_owned += 1
            continue
        candidates.append((path, item, ownership))

    for path, item, ownership in sorted(candidates):
        asset = _analyze_asset(
            root,
            path,
            item,
            ownership,
            guid_to_assets,
            script_symbols,
            entries_by_path,
            analysis,
            editor_assets.get(path),
            editor_scripts,
            editor_snapshot or {},
        )
        analysis.assets[path] = asset

    analysis.edge_details = _merge_edges(analysis.edge_details)
    analysis.call_graph.sort(
        key=lambda item: (item.get("source", ""), item.get("callerId", ""), item.get("line", 0))
    )
    analysis.summary = _build_summary(
        analysis.assets,
        eligible=len(candidates),
        skipped_non_owned=skipped_non_owned,
    )
    analysis.summary["errors"] = list(analysis.errors)
    return analysis


def _analyze_asset(
    root: Path,
    path: str,
    inventory_entry: Any,
    ownership: str,
    guid_to_assets: dict[str, list[str]],
    script_symbols: dict[str, dict[str, Any]],
    entries_by_path: dict[str, Any],
    analysis: UnityRuntimeAnalysis,
    editor_asset: dict[str, Any] | None,
    editor_scripts: dict[str, dict[str, Any]],
    editor_snapshot: dict[str, Any],
) -> dict[str, Any]:
    base: dict[str, Any] = {
        "path": path,
        "kind": _kind_for_path(path),
        "status": "parsed",
        "ownership": ownership,
        "confidence": "exact",
        "objects": [],
        "roots": [],
        "root_objects": [],
        "unity_events": [],
        "event_bindings": [],
        "prefab_instances": [],
        "script_types": [],
        "references": [],
        "object_count": 0,
        "component_count": 0,
        "script_component_count": 0,
        "project_script_component_count": 0,
    }
    absolute = getattr(inventory_entry, "absolute_path", root / Path(path))
    suffix = PurePosixPath(path).suffix.lower()
    if editor_asset is not None and suffix not in _YAML_SUFFIXES and suffix != ".fbx":
        return _analyze_editor_asset(base, editor_asset, guid_to_assets, analysis)
    if PurePosixPath(path).suffix.lower() == ".fbx":
        return _analyze_fbx_asset(
            base,
            Path(absolute),
            root / Path(path + ".meta"),
            guid_to_assets,
            analysis,
        )
    try:
        raw = Path(absolute).read_bytes()
    except OSError as error:
        return _failed_asset(base, analysis, path, "read_error", str(error), "parse_error")
    if b"\x00" in raw[:4096]:
        return _failed_asset(
            base,
            analysis,
            path,
            "unsupported_serialization",
            "Binary Unity serialization is not parsed.",
            "unsupported_serialization",
        )
    try:
        source = raw.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        return _failed_asset(
            base,
            analysis,
            path,
            "unsupported_serialization",
            f"Non-UTF-8 Unity serialization: {error}",
            "unsupported_serialization",
        )

    documents = _split_documents(source)
    if not documents:
        return _failed_asset(
            base,
            analysis,
            path,
            "malformed_yaml",
            "No structural Unity YAML documents were found.",
            "parse_error",
        )

    docs = {document.file_id: document for document in documents}
    object_context = _build_object_hierarchy(documents)
    base.update(object_context)
    _resolve_components(
        base,
        documents,
        docs,
        guid_to_assets,
        script_symbols,
        editor_scripts,
        editor_snapshot,
    )
    _collect_structured_references(base, documents, guid_to_assets, editor_snapshot)
    _collect_serialized_asset_semantics(base, documents)
    _collect_prefab_instances(base, documents, guid_to_assets)
    _collect_events(
        root,
        base,
        documents,
        docs,
        guid_to_assets,
        script_symbols,
        entries_by_path,
        analysis,
    )
    _collect_animator(
        base,
        documents,
        docs,
        guid_to_assets,
        script_symbols,
        editor_scripts,
    )

    if base["kind"] == "asset":
        script = _scriptable_object_script(
            documents,
            guid_to_assets,
            script_symbols,
            editor_scripts,
        )
        if script and script.get("unity_type") == "ScriptableObject":
            base["kind"] = "scriptable_object"
            base["script"] = script
            base["scriptable_object"] = {
                "name": _asset_name(documents) or PurePosixPath(path).stem,
                "type": script.get("qualified_name") or script.get("type", ""),
                "script_path": script.get("path", ""),
                "confidence": script.get("confidence", "unresolved"),
            }
    if editor_asset is not None:
        _merge_editor_asset(base, editor_asset, guid_to_assets)
    base["script_types"] = _script_types(base)
    root_ids = set(base["roots"])
    base["root_objects"] = [
        item for item in base["objects"] if item["file_id"] in root_ids
    ]
    base["event_bindings"] = base["unity_events"]
    base["confidence"] = _asset_confidence(base)
    _emit_edges(base, analysis)
    base["responsibility"] = _responsibility(base)
    base["high_signal"] = _high_signal(base)
    return base


def _analyze_fbx_asset(
    base: dict[str, Any],
    absolute: Path,
    meta_path: Path,
    guid_to_assets: dict[str, list[str]],
    analysis: UnityRuntimeAnalysis,
) -> dict[str, Any]:
    try:
        inspected = inspect_fbx(absolute, meta_path, guid_to_assets)
    except OSError as error:
        return _failed_asset(
            base,
            analysis,
            base["path"],
            "read_error",
            str(error),
            "parse_error",
        )
    base.update(inspected)
    if base.get("status") != "parsed":
        base["responsibility"] = "FBX model; binary and ModelImporter data could not be inspected."
        base["high_signal"] = 0
        return base
    _emit_edges(base, analysis)
    base["responsibility"] = _responsibility(base)
    base["high_signal"] = _high_signal(base)
    return base


def _editor_references(
    source: str,
    editor_asset: dict[str, Any],
    guid_to_assets: dict[str, list[str]],
) -> list[dict[str, Any]]:
    references: list[dict[str, Any]] = []
    for index, raw_target in enumerate(editor_asset.get("dependencies", []), start=1):
        target = _normalize(str(raw_target))
        if (
            not target
            or target == source
            or target.endswith(".meta")
            or target.startswith(("Library/", "Temp/", "obj/", ".better-context/"))
        ):
            continue
        target_guid = ""
        for guid, paths in guid_to_assets.items():
            if target in paths:
                target_guid = guid
                break
        references.append(
            {
                "document_file_id": "0",
                "file_id": "0",
                "guid": target_guid,
                "field": "AssetDatabase.GetDependencies",
                "line": index,
                "target": target,
                "confidence": "exact",
                "reason": "asset_database_direct_dependency",
                "edge_kind": "asset_database_direct",
                "provenance": "unity-editor",
            }
        )
    return references


def _editor_has_non_default_importer(editor_asset: dict[str, Any]) -> bool:
    facts = editor_asset.get("facts", {})
    if not isinstance(facts, dict):
        return False
    if str(facts.get("readable", "false")).casefold() == "true":
        return True
    return any(
        key.startswith("platform.")
        and key.endswith(".overridden")
        and str(value).casefold() == "true"
        for key, value in facts.items()
    )


def _merge_editor_asset(
    asset: dict[str, Any],
    editor_asset: dict[str, Any],
    guid_to_assets: dict[str, list[str]],
) -> None:
    editor_kind = str(editor_asset.get("kind", ""))
    if editor_kind and asset.get("kind") not in {
        "scene",
        "prefab",
        "scriptable_object",
        "animator_controller",
        "animation_clip",
        "material",
        "mesh",
        "model",
    }:
        asset["kind"] = editor_kind
    asset["editor_asset"] = {
        **editor_asset,
        "provenance": "unity-editor",
        "confidence": "exact",
    }
    asset["non_default_importer"] = _editor_has_non_default_importer(editor_asset)
    existing = {
        (str(item.get("field", "")), str(item.get("target", "")))
        for item in asset.get("references", [])
    }
    for reference in _editor_references(asset["path"], editor_asset, guid_to_assets):
        key = (reference["field"], reference["target"])
        if key not in existing:
            asset.setdefault("references", []).append(reference)
            existing.add(key)


def _analyze_editor_asset(
    base: dict[str, Any],
    editor_asset: dict[str, Any],
    guid_to_assets: dict[str, list[str]],
    analysis: UnityRuntimeAnalysis,
) -> dict[str, Any]:
    base["kind"] = str(editor_asset.get("kind") or base["kind"])
    base["editor_asset"] = {
        **editor_asset,
        "provenance": "unity-editor",
        "confidence": "exact",
    }
    base["references"] = _editor_references(base["path"], editor_asset, guid_to_assets)
    subassets = [
        item for item in editor_asset.get("subassets", []) if isinstance(item, dict)
    ]
    base["subasset_count"] = len(subassets)
    base["non_default_importer"] = _editor_has_non_default_importer(editor_asset)
    _emit_edges(base, analysis)
    base["responsibility"] = _responsibility(base)
    base["high_signal"] = _high_signal(base)
    return base


def _failed_asset(
    asset: dict[str, Any],
    analysis: UnityRuntimeAnalysis,
    path: str,
    error_type: str,
    message: str,
    status: str,
) -> dict[str, Any]:
    asset["status"] = status
    asset["confidence"] = "unresolved"
    asset["responsibility"] = "Unity asset; runtime serialization could not be inspected."
    asset["high_signal"] = 0
    if status != "unsupported_serialization":
        analysis.errors.append({"path": path, "error_type": error_type, "message": message})
    return asset


def _split_documents(source: str) -> list[_Document]:
    numbered = list(enumerate(source.splitlines(), start=1))
    markers: list[tuple[int, re.Match[str]]] = []
    for index, (_, line) in enumerate(numbered):
        match = _DOCUMENT_HEADER.match(line)
        if match:
            markers.append((index, match))
    documents: list[_Document] = []
    for marker_index, (start, match) in enumerate(markers):
        end = markers[marker_index + 1][0] if marker_index + 1 < len(markers) else len(numbered)
        lines = numbered[start + 1 : end]
        type_name = ""
        for _, line in lines:
            type_match = _TYPE_LINE.match(line)
            if type_match:
                type_name = type_match.group("name")
                break
            if line.strip():
                break
        class_id = int(match.group("class_id"))
        documents.append(
            _Document(
                class_id=class_id,
                file_id=match.group("file_id"),
                stripped=bool(match.group("stripped")),
                type_name=type_name or _CLASS_NAMES.get(class_id, f"ClassID{class_id}"),
                lines=lines,
            )
        )
    return documents


def _build_guid_index(inventory_by_path: dict[str, Any]) -> dict[str, list[str]]:
    index: dict[str, list[str]] = defaultdict(list)
    for path, item in inventory_by_path.items():
        if not path.endswith(".meta"):
            continue
        asset_path = path[:-5]
        absolute_meta = getattr(item, "absolute_path", None)
        absolute_asset = Path(str(absolute_meta)[:-5]) if absolute_meta else None
        if asset_path not in inventory_by_path and not (
            absolute_asset and absolute_asset.is_file()
        ):
            continue
        try:
            source = Path(item.absolute_path).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        match = _META_GUID.search(source)
        if match:
            index[match.group(1).lower()].append(asset_path)
    return {guid: sorted(set(paths)) for guid, paths in index.items()}


def _collect_serialized_asset_semantics(
    asset: dict[str, Any],
    documents: list[_Document],
) -> None:
    """Record compact facts only for asset formats with a known Unity schema."""
    suffix = PurePosixPath(asset["path"]).suffix.lower()
    if suffix == ".anim":
        document = next(
            (item for item in documents if item.type_name == "AnimationClip"), None
        )
        if document is None:
            return
        curve_sections = (
            "m_FloatCurves",
            "m_PositionCurves",
            "m_RotationCurves",
            "m_ScaleCurves",
            "m_PPtrCurves",
            "m_EditorCurves",
        )
        curve_maps = [
            item
            for section in curve_sections
            for item in _list_maps(document, section)
        ]
        event_maps = _list_maps(document, "m_Events")
        asset["kind"] = "animation_clip"
        asset["animation_clip"] = {
            "name": _scalar(document, "m_Name") or PurePosixPath(asset["path"]).stem,
            "sample_rate": _as_number(_scalar(document, "m_SampleRate")),
            "legacy": _as_bool(_scalar(document, "m_Legacy"), False),
            "wrap_mode": _as_int(_scalar(document, "m_WrapMode"), 0),
            "curve_count": sum(
                _list_item_count(document, section) for section in curve_sections
            ),
            "binding_paths": sorted(
                {item["path"] for item in curve_maps if item.get("path")}
            ),
            "properties": sorted(
                {item["attribute"] for item in curve_maps if item.get("attribute")}
            ),
            "events": sorted(
                {
                    item["functionName"]
                    for item in event_maps
                    if item.get("functionName")
                }
            ),
        }
        return

    if suffix == ".mat":
        document = next((item for item in documents if item.type_name == "Material"), None)
        if document is None:
            return
        shader: dict[str, Any] = next(
            (
                item
                for item in asset.get("references", [])
                if item.get("field") == "m_Shader"
            ),
            {},
        )
        texture_refs = [
            item
            for item in asset.get("references", [])
            if item.get("field") == "m_Texture"
        ]
        asset["kind"] = "material"
        asset["material"] = {
            "name": _scalar(document, "m_Name") or PurePosixPath(asset["path"]).stem,
            "shader": shader.get("target", ""),
            "shader_guid": shader.get("guid", ""),
            "textures": sorted(
                {item["target"] for item in texture_refs if item.get("target")}
            ),
            "texture_reference_count": len(texture_refs),
        }
        return

    if suffix == ".asset":
        document = next((item for item in documents if item.type_name == "Mesh"), None)
        if document is None:
            return
        asset["kind"] = "mesh"
        asset["mesh"] = {
            "name": _scalar(document, "m_Name") or PurePosixPath(asset["path"]).stem,
            "vertex_count": _as_int(_scalar(document, "m_VertexCount"), 0),
            "submesh_count": _list_item_count(document, "m_SubMeshes"),
            "bounds_center": _scalar(document, "m_Center"),
            "bounds_extent": _scalar(document, "m_Extent"),
        }


def _build_script_symbol_index(entries_by_path: dict[str, Any]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for path, entry in entries_by_path.items():
        if not path.endswith(".cs"):
            continue
        chunks = list(getattr(entry, "chunks", []))
        unity_types = [
            chunk
            for chunk in chunks
            if getattr(chunk, "metadata", {}).get("unity_type")
            in {"MonoBehaviour", "ScriptableObject", "StateMachineBehaviour"}
            and getattr(chunk, "metadata", {}).get("analysis_engine") == "roslyn"
        ]
        result[path] = {"types": unity_types, "chunks": chunks}
    return result


def _build_object_hierarchy(documents: list[_Document]) -> dict[str, Any]:
    game_objects: dict[str, dict[str, Any]] = {}
    transform_to_object: dict[str, str] = {}
    transforms: dict[str, dict[str, Any]] = {}
    components_by_object: dict[str, list[str]] = defaultdict(list)

    for document in documents:
        if document.type_name == "GameObject":
            component_ids = [
                reference.get("file_id", "0")
                for _, _, reference in _reference_fields(document)
                if reference.get("field") == "component" and reference.get("file_id") != "0"
            ]
            game_objects[document.file_id] = {
                "file_id": document.file_id,
                "name": _scalar(document, "m_Name") or f"GameObject {document.file_id}",
                "path": "",
                "active": _as_bool(_scalar(document, "m_IsActive"), True),
                "tag": _scalar(document, "m_TagString") or "Untagged",
                "layer": _as_int(_scalar(document, "m_Layer"), 0),
                "parent_file_id": "0",
                "children": [],
                "components": [],
                "component_file_ids": component_ids,
                "stripped": document.stripped,
            }

    for document in documents:
        game_object_id = _local_reference(document, "m_GameObject")
        if game_object_id and game_object_id != "0":
            components_by_object[game_object_id].append(document.file_id)
        if document.type_name not in {"Transform", "RectTransform"}:
            continue
        transform_to_object[document.file_id] = game_object_id
        transforms[document.file_id] = {
            "game_object": game_object_id,
            "father": _local_reference(document, "m_Father"),
            "children": _local_references_in_block(document, "m_Children"),
        }

    for transform in transforms.values():
        object_id = transform["game_object"]
        if not object_id or object_id not in game_objects:
            continue
        father_object = transform_to_object.get(transform["father"], "0")
        game_objects[object_id]["parent_file_id"] = father_object or "0"
        child_objects = [
            transform_to_object[child]
            for child in transform["children"]
            if child in transform_to_object and transform_to_object[child] in game_objects
        ]
        game_objects[object_id]["children"] = child_objects

    def object_path(file_id: str, visiting: set[str]) -> str:
        item = game_objects[file_id]
        if item["path"]:
            return str(item["path"])
        if file_id in visiting:
            item["path"] = item["name"]
            return str(item["path"])
        parent = item["parent_file_id"]
        if parent in game_objects:
            item["path"] = f"{object_path(parent, visiting | {file_id})}/{item['name']}"
        else:
            item["path"] = item["name"]
        return str(item["path"])

    for file_id in game_objects:
        object_path(file_id, set())
        if not game_objects[file_id]["component_file_ids"]:
            game_objects[file_id]["component_file_ids"] = components_by_object.get(file_id, [])

    roots = [
        file_id
        for file_id, item in game_objects.items()
        if item["parent_file_id"] not in game_objects
    ]
    objects = sorted(
        game_objects.values(), key=lambda item: (item["path"].lower(), item["file_id"])
    )
    return {
        "objects": objects,
        "roots": roots,
        "object_count": len(objects),
        "component_count": sum(len(item["component_file_ids"]) for item in objects),
    }


def _resolve_components(
    asset: dict[str, Any],
    documents: list[_Document],
    docs: dict[str, _Document],
    guid_to_assets: dict[str, list[str]],
    script_symbols: dict[str, dict[str, Any]],
    editor_scripts: dict[str, dict[str, Any]],
    editor_snapshot: dict[str, Any],
) -> None:
    object_by_id = {item["file_id"]: item for item in asset["objects"]}
    for item in asset["objects"]:
        components = []
        for component_id in item.pop("component_file_ids", []):
            document = docs.get(component_id)
            if not document:
                components.append(
                    {
                        "file_id": component_id,
                        "class_id": 0,
                        "type": "MissingComponent",
                        "confidence": "unresolved",
                    }
                )
                continue
            component = _component_fact(
                asset,
                document,
                guid_to_assets,
                script_symbols,
                editor_scripts,
                editor_snapshot,
            )
            components.append(component)
        item["components"] = components

    # Some malformed or stripped YAML omits GameObject.m_Component; retain exact
    # m_GameObject ownership without inventing hierarchy.
    attached = {
        component["file_id"]
        for item in asset["objects"]
        for component in item["components"]
    }
    for document in documents:
        if document.file_id in attached or document.type_name == "GameObject":
            continue
        object_id = _local_reference(document, "m_GameObject")
        if object_id not in object_by_id:
            continue
        component = _component_fact(
            asset,
            document,
            guid_to_assets,
            script_symbols,
            editor_scripts,
            editor_snapshot,
        )
        if document.stripped and component["confidence"] == "exact":
            component["confidence"] = "partial"
        object_by_id[object_id]["components"].append(component)
        asset["component_count"] += 1


def _component_fact(
    asset: dict[str, Any],
    document: _Document,
    guid_to_assets: dict[str, list[str]],
    script_symbols: dict[str, dict[str, Any]],
    editor_scripts: dict[str, dict[str, Any]],
    editor_snapshot: dict[str, Any],
) -> dict[str, Any]:
    component: dict[str, Any] = {
        "file_id": document.file_id,
        "class_id": document.class_id,
        "type": document.type_name,
        "qualified_type": f"UnityEngine.{document.type_name}",
        "assembly": "UnityEngine",
        "boundary": "builtin",
        "confidence": "exact",
        "provenance": "unity-yaml-class",
        "stripped": document.stripped,
        "fields": {},
        "references": [],
    }
    script_reference = _reference_for_field(document, "m_Script")
    if document.type_name == "MonoBehaviour" and script_reference:
        script = _resolve_script(
            script_reference,
            guid_to_assets,
            script_symbols,
            editor_scripts,
        )
        component["script"] = script
        component["type"] = script.get("type") or "MonoBehaviour"
        component["qualified_type"] = script.get("qualified_name") or component["type"]
        component["assembly"] = script.get("assembly", "")
        component["boundary"] = script.get("boundary") or _ownership(
            str(script.get("path", "")), None
        )
        component["confidence"] = script["confidence"]
        component["provenance"] = (
            "unity-editor-monoscript"
            if script.get("reason") == "unity_editor_monoscript_get_class"
            else "meta-guid-roslyn"
        )
        if script["confidence"] == "exact":
            asset["script_component_count"] += 1
            if component["boundary"] in {"project", "project-owned"}:
                asset["project_script_component_count"] += 1

    enabled = _scalar(document, "m_Enabled")
    if enabled:
        component["enabled"] = _as_bool(enabled, True)
    short_type = str(component.get("type", "")).rsplit(".", 1)[-1]
    selected = _COMPONENT_FIELDS.get(short_type)
    if selected is None:
        selected = _COMPONENT_FIELDS.get(document.type_name)
    component["fields"] = _selected_component_fields(document, selected)
    component["references"] = _component_references(
        document,
        guid_to_assets,
        editor_snapshot,
        selected,
    )
    return component


def _selected_component_fields(
    document: _Document,
    selected: tuple[str, ...] | None,
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    if selected is not None:
        for name in selected:
            value = _scalar(document, name)
            if value and not _inline_reference(value):
                result[name] = _typed_scalar(
                    value,
                    boolean=name in _BOOLEAN_COMPONENT_FIELDS,
                )
        return result

    for _line_number, line in document.lines:
        match = _FIELD.match(line)
        if not match or len(match.group("indent")) != 2:
            continue
        name = match.group("key")
        value = match.group("value").strip()
        if (
            name in _GENERIC_COMPONENT_SKIP_FIELDS
            or not value
            or _inline_reference(value)
        ):
            continue
        result[name] = _typed_scalar(value)
        if len(result) >= 12:
            break
    return result


def _typed_scalar(value: str, *, boolean: bool = False) -> Any:
    value = _unquote(value)
    if boolean and value in {"0", "1"}:
        return bool(int(value))
    number = _as_number(value)
    return number if number is not None else value


def _component_references(
    document: _Document,
    guid_to_assets: dict[str, list[str]],
    editor_snapshot: dict[str, Any],
    selected: tuple[str, ...] | None,
) -> list[dict[str, Any]]:
    references: list[dict[str, Any]] = []
    selected_set = set(selected or ())
    subassets = editor_snapshot.get("subassets_by_identity", {})
    for line, field_name, reference in _reference_fields(document):
        if field_name in {"m_GameObject", "m_Script"}:
            continue
        if selected is not None and field_name not in selected_set:
            continue
        guid = reference.get("guid", "").lower()
        file_id = reference.get("file_id", "0")
        if not guid and file_id == "0":
            continue
        targets = guid_to_assets.get(guid, []) if guid else []
        item: dict[str, Any] = {
            "field": field_name,
            "line": line,
            "guid": guid,
            "file_id": file_id,
            "confidence": "exact" if len(targets) == 1 else "unresolved",
            "provenance": "unity-yaml-object-reference",
        }
        if len(targets) == 1:
            item["target"] = targets[0]
            identity = f"{guid}:{file_id}"
            subasset = subassets.get(identity) if isinstance(subassets, dict) else None
            if isinstance(subasset, dict):
                item["subasset"] = {
                    "name": subasset.get("name", ""),
                    "type": subasset.get("type_name", ""),
                    "local_id": subasset.get("local_id", file_id),
                    "sprite_id": subasset.get("sprite_id", ""),
                }
        elif not guid and file_id != "0":
            item["confidence"] = "exact"
            item["target"] = f"local-fileID:{file_id}"
        elif len(targets) > 1:
            item["reason"] = "duplicate_guid"
            item["candidates"] = targets
        else:
            item["reason"] = "guid_not_in_inventory"
        references.append(item)
        if selected is None and len(references) >= 12:
            break
    return references


def _collect_structured_references(
    asset: dict[str, Any],
    documents: list[_Document],
    guid_to_assets: dict[str, list[str]],
    editor_snapshot: dict[str, Any] | None = None,
) -> None:
    references = []
    for document in documents:
        for line, field_name, reference in _reference_fields(document):
            guid = reference.get("guid", "").lower()
            if not guid or guid == "0" * 32 or guid.startswith("0000000000000000"):
                continue
            targets = guid_to_assets.get(guid, [])
            if len(targets) == 1:
                confidence = "exact"
                target = targets[0]
                reason = "meta_guid"
            elif len(targets) > 1:
                confidence = "partial"
                target = ""
                reason = "duplicate_guid"
            else:
                confidence = "unresolved"
                target = ""
                reason = "guid_not_in_inventory"
            item: dict[str, Any] = {
                "document_file_id": document.file_id,
                "field": field_name,
                "file_id": reference.get("file_id", "0"),
                "guid": guid,
                "target": target,
                "candidates": targets if len(targets) > 1 else [],
                "confidence": confidence,
                "reason": reason,
                "line": line,
            }
            subassets = (editor_snapshot or {}).get("subassets_by_identity", {})
            identity = f"{guid}:{reference.get('file_id', '0')}"
            subasset = subassets.get(identity) if isinstance(subassets, dict) else None
            if isinstance(subasset, dict):
                item["subasset"] = {
                    "name": subasset.get("name", ""),
                    "type": subasset.get("type_name", ""),
                    "local_id": subasset.get("local_id", reference.get("file_id", "0")),
                    "sprite_id": subasset.get("sprite_id", ""),
                }
            references.append(item)
    asset["references"] = references


def _collect_prefab_instances(
    asset: dict[str, Any],
    documents: list[_Document],
    guid_to_assets: dict[str, list[str]],
) -> None:
    instances = []
    stripped_refs = [
        {
            "file_id": document.file_id,
            "type": document.type_name,
            "source_object_file_id": _reference_for_field(
                document, "m_CorrespondingSourceObject"
            ).get("file_id", "0"),
        }
        for document in documents
        if document.stripped
    ]
    for document in documents:
        if document.type_name != "PrefabInstance":
            continue
        source = _reference_for_field(document, "m_SourcePrefab")
        guid = source.get("guid", "").lower()
        targets = guid_to_assets.get(guid, []) if guid else []
        if len(targets) == 1:
            confidence = "exact"
            target = targets[0]
        elif targets:
            confidence = "partial"
            target = ""
        else:
            confidence = "unresolved"
            target = ""
        instances.append(
            {
                "file_id": document.file_id,
                "source_prefab": {
                    "guid": guid,
                    "file_id": source.get("file_id", "0"),
                    "path": target,
                    "candidates": targets if len(targets) > 1 else [],
                    "confidence": confidence,
                },
                "modification_count": _list_item_count(document, "m_Modifications"),
                "transform_parent_file_id": _local_reference(document, "m_TransformParent"),
                "stripped_refs": stripped_refs,
            }
        )
    asset["prefab_instances"] = instances


def _collect_events(
    root: Path,
    asset: dict[str, Any],
    documents: list[_Document],
    docs: dict[str, _Document],
    guid_to_assets: dict[str, list[str]],
    script_symbols: dict[str, dict[str, Any]],
    _entries_by_path: dict[str, Any],
    analysis: UnityRuntimeAnalysis,
) -> None:
    object_by_component: dict[str, dict[str, Any]] = {}
    for obj in asset["objects"]:
        for component in obj["components"]:
            object_by_component[component["file_id"]] = obj

    events = []
    for document in documents:
        owner_object = object_by_component.get(document.file_id)
        for call in _persistent_calls(document):
            target_id = call["target"].get("file_id", "0")
            target_object = object_by_component.get(target_id)
            target_asset = asset["path"]
            target_script: dict[str, Any] = {}
            if call["target"].get("guid"):
                target_script, target_asset = _resolve_external_event_target(
                    root,
                    call["target"],
                    guid_to_assets,
                    script_symbols,
                )
                target_object = None
            else:
                target_document = docs.get(target_id)
                if target_document and _reference_for_field(target_document, "m_Script"):
                    # The target component was already resolved; reuse it to
                    # avoid a second filename- or assembly-name-based lookup.
                    for component in (target_object or {}).get("components", []):
                        if component["file_id"] == target_id:
                            target_script = component.get("script", {})
                            break

            confidence = "unresolved"
            reason = "target_component_not_resolved"
            method_chunk: Any = None
            method_name = call["method"]
            if target_script.get("confidence") == "exact" and method_name:
                script_path = target_script.get("path", "")
                type_id = target_script.get("chunk_id", "")
                symbols = script_symbols.get(script_path, {})
                methods = [
                    chunk
                    for chunk in symbols.get("chunks", [])
                    if getattr(chunk, "parent", None) == type_id
                    and getattr(chunk, "name", "") == method_name
                    and getattr(chunk, "metadata", {}).get("analysis_engine") == "roslyn"
                ]
                if len(methods) == 1:
                    method_chunk = methods[0]
                    confidence = "exact"
                    reason = "target_guid_and_roslyn_method"
                elif len(methods) > 1:
                    confidence = "partial"
                    reason = "ambiguous_method_overload"
                else:
                    reason = "method_not_found_in_roslyn_type"
            elif not method_name:
                reason = "empty_method_name"

            declared_type = call.get("assembly_type", "").split(",", 1)[0].strip()
            resolved_type = target_script.get("qualified_name") or target_script.get("type", "")
            if (
                confidence == "exact"
                and declared_type
                and declared_type not in {resolved_type, target_script.get("type", "")}
            ):
                confidence = "partial"
                reason = "serialized_type_disagrees_with_guid_target"
                method_chunk = None

            event = {
                "field": call["field"],
                "owner_file_id": document.file_id,
                "owner_path": owner_object.get("path", "") if owner_object else "",
                "owner_object": owner_object.get("path", "") if owner_object else "",
                "component_file_id": document.file_id,
                "target_file_id": target_id,
                "target_path": target_object.get("path", "") if target_object else target_asset,
                "target_asset": target_asset,
                "target_script": target_script.get("path", ""),
                "target_type": resolved_type or declared_type,
                "method": method_name,
                "mode": call.get("mode", 0),
                "call_state": call.get("call_state", 0),
                "confidence": confidence,
                "status": "disabled" if call.get("call_state", 0) == 0 else confidence,
                "reason": reason,
                "line": call["line"],
            }
            events.append(event)
            if method_chunk is not None and call.get("call_state", 0) != 0:
                analysis.call_graph.append(
                    {
                        "callerId": f"{asset['path']}:{document.file_id}:{call['field']}",
                        "callerName": f"{owner_object.get('path', asset['path'])}.{call['field']}"
                        if owner_object
                        else f"{asset['path']}.{call['field']}",
                        "source": asset["path"],
                        "calleeId": method_chunk.id,
                        "calleeName": getattr(method_chunk, "metadata", {}).get("qualified_name")
                        or f"{target_script.get('type', '')}.{method_name}",
                        "target": target_script["path"],
                        "line": call["line"],
                        "kind": "unity_event",
                        "confidence": "exact",
                        "evidence": {
                            "asset": asset["path"],
                            "component_file_id": document.file_id,
                            "target_file_id": target_id,
                            "field": call["field"],
                            "mode": call.get("mode", 0),
                        },
                    }
                )
    asset["unity_events"] = events


def _collect_animator(
    asset: dict[str, Any],
    documents: list[_Document],
    docs: dict[str, _Document],
    guid_to_assets: dict[str, list[str]],
    script_symbols: dict[str, dict[str, Any]],
    editor_scripts: dict[str, dict[str, Any]],
) -> None:
    if PurePosixPath(asset["path"]).suffix.lower() not in {".controller", ".overridecontroller"}:
        return
    controller = next((item for item in documents if item.type_name == "AnimatorController"), None)
    state_machines = {
        item.file_id: item for item in documents if item.type_name == "AnimatorStateMachine"
    }
    states = {item.file_id: item for item in documents if item.type_name == "AnimatorState"}
    transitions = {
        item.file_id: item for item in documents if item.type_name == "AnimatorStateTransition"
    }
    blend_trees = {item.file_id: item for item in documents if item.type_name == "BlendTree"}

    parameters = []
    layers = []
    if controller:
        for values in _list_maps(controller, "m_AnimatorParameters"):
            type_id = _as_int(values.get("m_Type", "0"), 0)
            default: Any = values.get("m_DefaultFloat", "0")
            if type_id == 3:
                default = values.get("m_DefaultInt", "0")
            elif type_id in {4, 9}:
                default = _as_bool(values.get("m_DefaultBool", "0"), False)
            parameters.append(
                {
                    "name": values.get("m_Name", ""),
                    "type": _ANIMATOR_PARAMETER_TYPES.get(type_id, str(type_id)),
                    "default": default,
                }
            )
        for values in _list_maps(controller, "m_AnimatorLayers"):
            state_machine = _inline_reference(values.get("m_StateMachine", ""))
            machine_id = state_machine.get("file_id", "0")
            default_state = "0"
            if machine_id in state_machines:
                default_state = _local_reference(state_machines[machine_id], "m_DefaultState")
            layers.append(
                {
                    "name": values.get("m_Name", ""),
                    "state_machine_file_id": machine_id,
                    "default_state_file_id": default_state,
                }
            )

    source_by_transition: dict[str, str] = {}
    for state_id, document in states.items():
        for transition_id in _local_references_in_block(document, "m_Transitions"):
            source_by_transition[transition_id] = state_id
    for machine_id, document in state_machines.items():
        for transition_id in _local_references_in_block(document, "m_AnyStateTransitions"):
            source_by_transition[transition_id] = f"AnyState:{machine_id}"
        for transition_id in _local_references_in_block(document, "m_EntryTransitions"):
            source_by_transition[transition_id] = f"Entry:{machine_id}"

    state_items = []
    for state_id, document in states.items():
        motion = _resolve_animator_reference(
            _reference_for_field(document, "m_Motion"), guid_to_assets, docs
        )
        behaviours = []
        for behaviour_id in _local_references_in_block(document, "m_StateMachineBehaviours"):
            behaviour_doc = docs.get(behaviour_id)
            if not behaviour_doc:
                continue
            reference = _reference_for_field(behaviour_doc, "m_Script")
            if reference:
                behaviours.append(
                    _resolve_script(
                        reference,
                        guid_to_assets,
                        script_symbols,
                        editor_scripts,
                    )
                )
        state_items.append(
            {
                "file_id": state_id,
                "name": _scalar(document, "m_Name"),
                "motion": motion,
                "behaviours": behaviours,
            }
        )

    transition_items = []
    for transition_id, document in transitions.items():
        conditions = []
        for values in _list_maps(document, "m_Conditions"):
            conditions.append(
                {
                    "parameter": values.get("m_ConditionEvent", ""),
                    "mode": _as_int(values.get("m_ConditionMode", "0"), 0),
                    "threshold": values.get("m_EventTreshold", "0"),
                }
            )
        transition_items.append(
            {
                "file_id": transition_id,
                "source_state_file_id": source_by_transition.get(transition_id, ""),
                "destination_state_file_id": _local_reference(document, "m_DstState"),
                "destination_state_machine_file_id": _local_reference(
                    document, "m_DstStateMachine"
                ),
                "exit_time": _scalar(document, "m_ExitTime"),
                "duration": _scalar(document, "m_TransitionDuration"),
                "has_exit_time": _as_bool(_scalar(document, "m_HasExitTime"), False),
                "is_exit": _as_bool(_scalar(document, "m_IsExit"), False),
                "conditions": conditions,
            }
        )

    blend_items = []
    for blend_id, document in blend_trees.items():
        children = []
        for values in _list_maps(document, "m_Childs"):
            reference = _inline_reference(values.get("m_Motion", ""))
            children.append(
                {
                    "motion": _resolve_animator_reference(reference, guid_to_assets, docs),
                    "threshold": values.get("m_Threshold", "0"),
                    "direct_parameter": values.get("m_DirectBlendParameter", ""),
                }
            )
        blend_items.append(
            {
                "file_id": blend_id,
                "name": _scalar(document, "m_Name"),
                "parameter": _scalar(document, "m_BlendParameter"),
                "parameter_y": _scalar(document, "m_BlendParameterY"),
                "children": children,
            }
        )

    asset["animator"] = {
        "parameters": parameters,
        "layers": layers,
        "states": sorted(state_items, key=lambda item: (item["name"], item["file_id"])),
        "transitions": sorted(transition_items, key=lambda item: item["file_id"]),
        "blend_trees": sorted(blend_items, key=lambda item: item["file_id"]),
    }


def _emit_edges(asset: dict[str, Any], analysis: UnityRuntimeAnalysis) -> None:
    for reference in asset.get("references", []):
        target = reference.get("target", "")
        if reference.get("confidence") != "exact" or not target or target.endswith(".meta"):
            continue
        kind = str(reference.get("edge_kind") or "serialized_guid")
        if reference["field"] == "m_Script":
            kind = "unity_component"
            if asset.get("kind") == "scriptable_object":
                kind = "scriptable_object_type"
        elif reference["field"] in {"m_SourcePrefab", "m_ParentPrefab"}:
            kind = "prefab_instance"
        elif reference["field"] == "m_Motion" and asset.get("animator"):
            kind = "animator_motion"
        analysis.edge_details.append(
            {
                "source": asset["path"],
                "target": target,
                "kinds": [kind],
                "symbols": [reference["field"]],
                "lines": [reference["line"]],
                "confidence": "exact",
                "engine": "unity-runtime",
                "evidence": [
                    {
                        "asset": asset["path"],
                        "document_file_id": reference["document_file_id"],
                        "file_id": reference["file_id"],
                        "guid": reference["guid"],
                        "field": reference["field"],
                        "line": reference["line"],
                        "reason": reference["reason"],
                        "provenance": reference.get("provenance", "unity-yaml"),
                        "subasset": reference.get("subasset"),
                    }
                ],
            }
        )
    for event in asset.get("unity_events", []):
        target = event.get("target_script", "")
        if (
            event.get("confidence") != "exact"
            or event.get("call_state", 0) == 0
            or not target
        ):
            continue
        analysis.edge_details.append(
            {
                "source": asset["path"],
                "target": target,
                "kinds": ["unity_event"],
                "symbols": [f"{event['target_type']}.{event['method']}"],
                "lines": [event["line"]],
                "confidence": "exact",
                "engine": "unity-runtime",
                "evidence": [
                    {
                        "asset": asset["path"],
                        "component_file_id": event["component_file_id"],
                        "target_file_id": event["target_file_id"],
                        "field": event["field"],
                        "method": event["method"],
                        "line": event["line"],
                        "reason": event["reason"],
                    }
                ],
            }
        )


def _merge_edges(edges: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[tuple[str, str], dict[str, Any]] = {}
    for edge in edges:
        key = (edge["source"], edge["target"])
        if key not in merged:
            merged[key] = {**edge}
            continue
        current = merged[key]
        current["kinds"] = sorted(set(current["kinds"]) | set(edge["kinds"]))
        current["symbols"] = sorted(set(current["symbols"]) | set(edge["symbols"]))
        current["lines"] = sorted(set(current["lines"]) | set(edge["lines"]))
        current.setdefault("evidence", []).extend(edge.get("evidence", []))
    return [merged[key] for key in sorted(merged)]


def _resolve_script(
    reference: dict[str, str],
    guid_to_assets: dict[str, list[str]],
    script_symbols: dict[str, dict[str, Any]],
    editor_scripts: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    guid = reference.get("guid", "").lower()
    result: dict[str, Any] = {
        "guid": guid,
        "file_id": reference.get("file_id", "0"),
        "path": "",
        "type": "",
        "qualified_name": "",
        "unity_type": "",
        "chunk_id": "",
        "confidence": "unresolved",
        "reason": "guid_not_in_inventory",
    }
    targets = guid_to_assets.get(guid, [])
    if len(targets) > 1:
        result["confidence"] = "partial"
        result["reason"] = "duplicate_guid"
        result["candidates"] = targets
        return result
    editor_script = (editor_scripts or {}).get(guid)
    if not targets:
        return _editor_script_result(result, editor_script)
    path = targets[0]
    result["path"] = path
    if not path.endswith(".cs"):
        result["reason"] = "guid_target_is_not_csharp"
        return _editor_script_result(result, editor_script)
    symbols = script_symbols.get(path)
    if not symbols:
        result["reason"] = "missing_roslyn_file_entry"
        return _editor_script_result(result, editor_script)
    types = symbols["types"]
    if len(types) > 1:
        concrete = [
            item
            for item in types
            if not getattr(item, "metadata", {}).get("is_abstract", False)
            and not getattr(item, "metadata", {}).get("abstract", False)
        ]
        if len(concrete) == 1:
            types = concrete
            result["reason"] = "unique_concrete_roslyn_unity_type"
        else:
            result["confidence"] = "partial"
            result["reason"] = "ambiguous_roslyn_unity_types"
            result["candidates"] = [getattr(item, "name", "") for item in types]
            return result
    if not types:
        result["reason"] = "no_roslyn_unity_type"
        return _editor_script_result(result, editor_script)
    chunk = types[0]
    metadata = getattr(chunk, "metadata", {})
    result.update(
        {
            "type": getattr(chunk, "name", ""),
            "qualified_name": metadata.get("qualified_name") or getattr(chunk, "name", ""),
            "unity_type": metadata.get("unity_type", ""),
            "chunk_id": getattr(chunk, "id", ""),
            "confidence": "exact",
            "reason": (
                result["reason"]
                if result["reason"] == "unique_concrete_roslyn_unity_type"
                else "meta_guid_and_roslyn_type"
            ),
        }
    )
    return result


def _editor_script_result(
    result: dict[str, Any],
    editor_script: dict[str, Any] | None,
) -> dict[str, Any]:
    if not isinstance(editor_script, dict) or not editor_script.get("resolved"):
        return result
    qualified = str(editor_script.get("qualified_type", ""))
    if not qualified:
        return result
    result.update(
        {
            "path": _normalize(str(editor_script.get("path", result.get("path", "")))),
            "type": qualified.rsplit(".", 1)[-1],
            "qualified_name": qualified,
            "unity_type": str(editor_script.get("base_type", "")).rsplit(".", 1)[-1],
            "assembly": str(editor_script.get("assembly", "")),
            "boundary": str(editor_script.get("boundary", "")),
            "confidence": "exact",
            "reason": "unity_editor_monoscript_get_class",
        }
    )
    return result


def _resolve_external_event_target(
    root: Path,
    reference: dict[str, str],
    guid_to_assets: dict[str, list[str]],
    script_symbols: dict[str, dict[str, Any]],
) -> tuple[dict[str, Any], str]:
    guid = reference.get("guid", "").lower()
    targets = guid_to_assets.get(guid, [])
    if len(targets) != 1:
        return (
            {
                "guid": guid,
                "file_id": reference.get("file_id", "0"),
                "path": "",
                "confidence": "partial" if targets else "unresolved",
                "reason": "duplicate_guid" if targets else "guid_not_in_inventory",
                "candidates": targets,
            },
            "",
        )
    target_path = targets[0]
    if target_path.endswith(".cs"):
        return _resolve_script(reference, guid_to_assets, script_symbols), target_path
    try:
        raw = (root / Path(target_path)).read_bytes()
        if b"\x00" in raw[:4096]:
            return {}, target_path
        documents = _split_documents(raw.decode("utf-8-sig"))
    except (OSError, UnicodeDecodeError):
        return {}, target_path
    target_document = next(
        (item for item in documents if item.file_id == reference.get("file_id", "0")),
        None,
    )
    if not target_document:
        return {}, target_path
    script_reference = _reference_for_field(target_document, "m_Script")
    if not script_reference:
        return {}, target_path
    return _resolve_script(script_reference, guid_to_assets, script_symbols), target_path


def _scriptable_object_script(
    documents: list[_Document],
    guid_to_assets: dict[str, list[str]],
    script_symbols: dict[str, dict[str, Any]],
    editor_scripts: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    for document in documents:
        game_object = _local_reference(document, "m_GameObject")
        if document.type_name != "MonoBehaviour" or game_object not in {"", "0"}:
            continue
        reference = _reference_for_field(document, "m_Script")
        if reference:
            return _resolve_script(
                reference,
                guid_to_assets,
                script_symbols,
                editor_scripts,
            )
    return {}


def _resolve_animator_reference(
    reference: dict[str, str],
    guid_to_assets: dict[str, list[str]],
    docs: dict[str, _Document],
) -> dict[str, Any]:
    if not reference:
        return {}
    file_id = reference.get("file_id", "0")
    guid = reference.get("guid", "").lower()
    if guid:
        targets = guid_to_assets.get(guid, [])
        if len(targets) == 1:
            return {
                "file_id": file_id,
                "guid": guid,
                "path": targets[0],
                "confidence": "exact",
            }
        return {
            "file_id": file_id,
            "guid": guid,
            "path": "",
            "candidates": targets,
            "confidence": "partial" if targets else "unresolved",
        }
    document = docs.get(file_id)
    return {
        "file_id": file_id,
        "local_type": document.type_name if document else "",
        "confidence": "exact" if document else "unresolved",
    }


def _persistent_calls(document: _Document) -> list[dict[str, Any]]:
    results = []
    lines = document.lines
    for persistent_index, (_, persistent_line) in enumerate(lines):
        persistent = _FIELD.match(persistent_line)
        if not persistent or persistent.group("key") != "m_PersistentCalls":
            continue
        persistent_indent = len(persistent.group("indent"))
        section_end = len(lines)
        for index in range(persistent_index + 1, len(lines)):
            following = lines[index][1]
            indentation = len(following) - len(following.lstrip())
            if following.strip() and indentation <= persistent_indent:
                section_end = index
                break
        calls_index = -1
        calls_indent = -1
        for index in range(persistent_index + 1, section_end):
            calls = _FIELD.match(lines[index][1])
            if calls and calls.group("key") == "m_Calls":
                calls_index = index
                calls_indent = len(calls.group("indent"))
                if calls.group("value").strip() == "[]":
                    calls_index = -1
                break
        if calls_index < 0:
            continue
        field_name = _event_field(lines, persistent_index)
        for target_index in range(calls_index + 1, section_end):
            line_number, line = lines[target_index]
            match = _LIST_FIELD.match(line)
            if (
                not match
                or match.group("key") != "m_Target"
                or len(match.group("indent")) < calls_indent
            ):
                continue
            target = _inline_reference(
                _continued_mapping_value(
                    lines,
                    target_index,
                    match.group("value"),
                    len(match.group("indent")),
                )
            )
            if not target or target.get("file_id") == "0":
                continue
            call_indent = len(match.group("indent"))
            values: dict[str, str] = {}
            for _, following in lines[target_index + 1 : section_end]:
                next_list = _LIST_FIELD.match(following)
                next_field = _FIELD.match(following)
                indentation = len(following) - len(following.lstrip())
                if next_list and len(next_list.group("indent")) == call_indent:
                    break
                if following.strip() and indentation < call_indent:
                    break
                value_match = next_list or next_field
                if value_match:
                    values[value_match.group("key")] = _unquote(value_match.group("value"))
            method = values.get("m_MethodName", "")
            if not method or method == "0":
                continue
            results.append(
                {
                    "target": target,
                    "assembly_type": values.get("m_TargetAssemblyTypeName", ""),
                    "method": method,
                    "mode": _as_int(values.get("m_Mode", "0"), 0),
                    "call_state": _as_int(values.get("m_CallState", "0"), 0),
                    "field": field_name,
                    "line": line_number,
                }
            )
    return results


def _event_field(lines: list[tuple[int, str]], persistent_index: int) -> str:
    match = _FIELD.match(lines[persistent_index][1])
    persistent_indent = len(match.group("indent")) if match else 10**6
    for index in range(persistent_index - 1, -1, -1):
        line = lines[index][1]
        field_match = _FIELD.match(line)
        if field_match and len(field_match.group("indent")) < persistent_indent:
            return field_match.group("key")
    return "UnityEvent"


def _reference_fields(document: _Document) -> list[tuple[int, str, dict[str, str]]]:
    references = []
    for index, (line_number, line) in enumerate(document.lines):
        stripped = line.lstrip()
        if not stripped or stripped.startswith("#"):
            continue
        match = _LIST_FIELD.match(line) or _FIELD.match(line)
        if match:
            value = _continued_mapping_value(
                document.lines,
                index,
                match.group("value"),
                len(match.group("indent")),
            )
            reference = _inline_reference(value)
            if reference:
                reference["field"] = match.group("key")
                references.append((line_number, match.group("key"), reference))
            continue
        bare = _BARE_LIST.match(line) or _BARE_LIST_START.match(line)
        if bare:
            value = _continued_mapping_value(
                document.lines,
                index,
                bare.group("value"),
                len(bare.group("indent")),
            )
            reference = _inline_reference(value)
            if reference:
                reference["field"] = "item"
                references.append((line_number, "item", reference))
    return references


def _continued_mapping_value(
    lines: list[tuple[int, str]],
    index: int,
    raw_value: str,
    base_indent: int,
) -> str:
    """Join only an indented continuation of an inline ``{fileID: ...}`` mapping."""
    value = raw_value.strip()
    if not value.startswith("{") or value.endswith("}"):
        return value
    parts = [value]
    for _, following in lines[index + 1 : index + 9]:
        stripped = following.strip()
        indentation = len(following) - len(following.lstrip())
        if not stripped or stripped.startswith("#") or indentation <= base_indent:
            break
        parts.append(stripped)
        if stripped.endswith("}"):
            return " ".join(parts)
    return value


def _inline_reference(value: str) -> dict[str, str]:
    value = value.strip()
    if not (value.startswith("{") and value.endswith("}")):
        return {}
    inner = value[1:-1].strip()
    fields: dict[str, str] = {}
    for part in inner.split(","):
        if ":" not in part:
            return {}
        key, raw = part.split(":", 1)
        key = key.strip()
        raw = raw.strip()
        if key not in {"fileID", "guid", "type"}:
            return {}
        fields[key] = raw
    file_id = fields.get("fileID")
    if file_id is None or not re.fullmatch(r"-?\d+", file_id):
        return {}
    guid = fields.get("guid", "")
    if guid and not _GUID.fullmatch(guid):
        return {}
    return {
        "file_id": file_id,
        "guid": guid.lower(),
        "type": fields.get("type", ""),
    }


def _reference_for_field(document: _Document, key: str) -> dict[str, str]:
    for _, field_name, reference in _reference_fields(document):
        if field_name == key:
            return reference
    return {}


def _local_reference(document: _Document, key: str) -> str:
    return _reference_for_field(document, key).get("file_id", "")


def _local_references_in_block(document: _Document, key: str) -> list[str]:
    lines = document.lines
    anchor = -1
    anchor_indent = -1
    for index, (_, line) in enumerate(lines):
        match = _FIELD.match(line)
        if match and match.group("key") == key:
            direct = _inline_reference(match.group("value"))
            if direct:
                return [direct["file_id"]]
            if match.group("value").strip() in {"[]", "{}"}:
                return []
            anchor = index
            anchor_indent = len(match.group("indent"))
            break
    if anchor < 0:
        return []
    results = []
    for index, (_, line) in enumerate(lines[anchor + 1 :], start=anchor + 1):
        indentation = len(line) - len(line.lstrip())
        if line.strip() and (
            indentation < anchor_indent
            or (indentation == anchor_indent and not line.lstrip().startswith("-"))
        ):
            break
        match = _LIST_FIELD.match(line)
        bare = _BARE_LIST.match(line) or _BARE_LIST_START.match(line)
        selected = match or bare
        value = (
            _continued_mapping_value(
                lines,
                index,
                selected.group("value"),
                len(selected.group("indent")),
            )
            if selected
            else ""
        )
        reference = _inline_reference(value)
        if reference:
            results.append(reference["file_id"])
    return results


def _scalar(document: _Document, key: str) -> str:
    for _, line in document.lines:
        match = _FIELD.match(line)
        if match and match.group("key") == key:
            return _unquote(match.group("value"))
    return ""


def _list_maps(document: _Document, key: str) -> list[dict[str, str]]:
    lines = document.lines
    anchor = -1
    anchor_indent = -1
    for index, (_, line) in enumerate(lines):
        match = _FIELD.match(line)
        if match and match.group("key") == key:
            if match.group("value").strip() in {"[]", "{}"}:
                return []
            anchor = index
            anchor_indent = len(match.group("indent"))
            break
    if anchor < 0:
        return []
    groups: list[dict[str, str]] = []
    current: dict[str, str] = {}
    item_indent = -1
    for index, (_, line) in enumerate(lines[anchor + 1 :], start=anchor + 1):
        indentation = len(line) - len(line.lstrip())
        if line.strip() and (
            indentation < anchor_indent
            or (indentation == anchor_indent and not line.lstrip().startswith("-"))
        ):
            break
        list_match = _LIST_FIELD.match(line)
        field_match = _FIELD.match(line)
        if list_match:
            if item_indent < 0:
                item_indent = len(list_match.group("indent"))
            if len(list_match.group("indent")) == item_indent:
                if current:
                    groups.append(current)
                current = {
                    list_match.group("key"): _unquote(
                        _continued_mapping_value(
                            lines,
                            index,
                            list_match.group("value"),
                            len(list_match.group("indent")),
                        )
                    )
                }
                continue
        if current and field_match:
            current[field_match.group("key")] = _unquote(
                _continued_mapping_value(
                    lines,
                    index,
                    field_match.group("value"),
                    len(field_match.group("indent")),
                )
            )
    if current:
        groups.append(current)
    return groups


def _list_item_count(document: _Document, key: str) -> int:
    lines = document.lines
    anchor = -1
    anchor_indent = -1
    for index, (_, line) in enumerate(lines):
        match = _FIELD.match(line)
        if match and match.group("key") == key:
            if match.group("value").strip() in {"[]", "{}"}:
                return 0
            anchor = index
            anchor_indent = len(match.group("indent"))
            break
    if anchor < 0:
        return 0
    count = 0
    item_indent = -1
    for _, line in lines[anchor + 1 :]:
        indentation = len(line) - len(line.lstrip())
        if line.strip() and (
            indentation < anchor_indent
            or (indentation == anchor_indent and not line.lstrip().startswith("-"))
        ):
            break
        match = _LIST_FIELD.match(line) or _BARE_LIST.match(line)
        if not match:
            continue
        indentation = len(match.group("indent"))
        if item_indent < 0:
            item_indent = indentation
        if indentation == item_indent:
            count += 1
    return count


def _build_summary(
    assets: dict[str, dict[str, Any]],
    eligible: int,
    skipped_non_owned: int,
) -> dict[str, Any]:
    metrics: Counter[str] = Counter()
    script_usages: dict[str, set[str]] = defaultdict(set)
    event_methods: dict[str, set[str]] = defaultdict(set)
    coverage: Counter[str] = Counter(
        {
            "eligible": eligible,
            "candidates": eligible,
            "skipped_non_owned": skipped_non_owned,
        }
    )
    compact_assets: list[dict[str, Any]] = []
    flattened_events: list[dict[str, Any]] = []
    for path, asset in assets.items():
        status = asset.get("status", "parse_error")
        if status == "parsed":
            coverage["parsed"] += 1
            if asset.get("confidence") == "partial":
                coverage["partial"] += 1
        elif status == "unsupported_serialization":
            coverage["unsupported"] += 1
        else:
            coverage["failed"] += 1
            coverage["errors"] += 1
        kind = asset.get("kind", "asset")
        plural = {
            "scene": "scenes",
            "prefab": "prefabs",
            "scriptable_object": "scriptable_objects",
            "animator_controller": "animator_controllers",
            "override_controller": "override_controllers",
            "animation_clip": "animation_clips",
            "material": "materials",
            "mesh": "meshes",
            "model": "models",
            "texture": "textures",
            "sprite_atlas": "sprite_atlases",
            "shader": "shaders",
            "cubemap": "cubemaps",
            "render_texture": "render_textures",
            "audio_clip": "audio_clips",
            "video_clip": "video_clips",
            "font": "fonts",
            "terrain_data": "terrain_assets",
            "terrain_layer": "terrain_assets",
            "physic_material": "physics_assets",
            "physics_material_2d": "physics_assets",
            "audio_mixer": "audio_mixers",
            "timeline": "timelines",
            "lighting_settings": "lighting_settings",
            "navmesh_data": "navmesh_assets",
        }.get(kind, "other_assets")
        metrics[plural] += 1
        editor_asset = asset.get("editor_asset", {})
        subassets = editor_asset.get("subassets", [])
        metrics["sprites"] += sum(
            1 for item in subassets if str(item.get("type_name", "")).endswith("Sprite")
        )
        if editor_asset:
            metrics["editor_assets"] += 1
        if asset.get("non_default_importer"):
            metrics["non_default_importers"] += 1
        metrics["game_objects"] += asset.get("object_count", 0)
        metrics["components"] += asset.get("component_count", 0)
        metrics["script_components"] += asset.get("script_component_count", 0)
        metrics["project_script_usages"] += asset.get(
            "project_script_component_count",
            asset.get("script_component_count", 0),
        )
        event_count = len(asset.get("event_bindings", []))
        metrics["event_bindings"] += event_count
        metrics["unity_events"] += event_count
        animator = asset.get("animator", {})
        metrics["animator_states"] += len(animator.get("states", []))
        metrics["animator_transitions"] += len(animator.get("transitions", []))
        metrics["blend_trees"] += len(animator.get("blend_trees", []))
        for reference in asset.get("references", []):
            if reference.get("confidence") == "exact":
                metrics["resolved_references"] += 1
            else:
                metrics["unresolved_references"] += 1
        for obj in asset.get("objects", []):
            for component in obj.get("components", []):
                if component.get("confidence") == "exact":
                    metrics["resolved_components"] += 1
                if component.get("provenance") == "unity-editor-monoscript":
                    metrics["editor_resolved_components"] += 1
                script_path = component.get("script", {}).get("path", "")
                if script_path:
                    script_usages[script_path].add(path)
        script = asset.get("script", {})
        if script.get("path"):
            script_usages[script["path"]].add(path)
        for event in asset.get("unity_events", []):
            flattened_events.append({"asset": path, **event})
            if event.get("confidence") == "exact":
                name = f"{event['target_type']}.{event['method']}"
                event_methods[name].add(path)
        compact_assets.append(
            {
                "path": path,
                "kind": kind,
                "status": status,
                "ownership": asset.get("ownership", ""),
                "object_count": asset.get("object_count", 0),
                "component_count": asset.get("component_count", 0),
                "script_types": asset.get("script_types", []),
                "root_objects": [item.get("name", "") for item in asset.get("root_objects", [])],
                "event_count": event_count,
                "animator_state_count": len(animator.get("states", [])),
                "signal_score": asset.get("high_signal", 0),
                "responsibility": asset.get("responsibility", ""),
                "model_node_count": asset.get("model", {}).get("node_count", 0),
                "model_mesh_count": asset.get("model", {}).get("mesh_count", 0),
                "model_bone_count": asset.get("model", {}).get("skeleton", {}).get(
                    "bone_count", 0
                ),
                "embedded_clip_count": len(asset.get("model_importer", {}).get("clips", [])),
                "subasset_count": len(editor_asset.get("subassets", [])),
                "non_default_importer": bool(asset.get("non_default_importer")),
                "editor_type": editor_asset.get("type_name", ""),
            }
        )
    metrics["assets"] = len(assets)
    for key in (
        "assets",
        "scenes",
        "prefabs",
        "scriptable_objects",
        "animator_controllers",
        "override_controllers",
        "animation_clips",
        "materials",
        "meshes",
        "models",
        "textures",
        "sprites",
        "sprite_atlases",
        "shaders",
        "cubemaps",
        "render_textures",
        "audio_clips",
        "video_clips",
        "fonts",
        "terrain_assets",
        "physics_assets",
        "audio_mixers",
        "timelines",
        "lighting_settings",
        "navmesh_assets",
        "editor_assets",
        "non_default_importers",
        "other_assets",
        "game_objects",
        "components",
        "script_components",
        "project_script_usages",
        "resolved_components",
        "editor_resolved_components",
        "event_bindings",
        "unity_events",
        "animator_states",
        "animator_transitions",
        "blend_trees",
        "resolved_references",
        "unresolved_references",
    ):
        metrics.setdefault(key, 0)
    for key in (
        "eligible",
        "candidates",
        "parsed",
        "partial",
        "unsupported",
        "failed",
        "errors",
        "skipped_non_owned",
    ):
        coverage.setdefault(key, 0)
    return {
        "engine": (
            "unity-yaml-fbx-editor"
            if any(asset.get("editor_asset") for asset in assets.values())
            else "unity-yaml-fbx-stdlib"
        ),
        "coverage": dict(coverage),
        "metrics": dict(metrics),
        "assets": sorted(compact_assets, key=lambda item: item["path"]),
        "event_bindings": sorted(
            flattened_events,
            key=lambda item: (item.get("asset", ""), item.get("line", 0)),
        ),
        "indexes": {
            "script_usages": {key: sorted(value) for key, value in sorted(script_usages.items())},
            "event_methods": {key: sorted(value) for key, value in sorted(event_methods.items())},
        },
    }


def _script_types(asset: dict[str, Any]) -> list[str]:
    names = set()
    for obj in asset.get("objects", []):
        for component in obj.get("components", []):
            script = component.get("script", {})
            if script.get("confidence") == "exact":
                name = script.get("qualified_name") or script.get("type")
                if name:
                    names.add(name)
    script = asset.get("script", {})
    if script.get("confidence") == "exact":
        name = script.get("qualified_name") or script.get("type")
        if name:
            names.add(name)
    return sorted(names)


def _asset_name(documents: list[_Document]) -> str:
    for document in documents:
        name = _scalar(document, "m_Name")
        if name:
            return name
    return ""


def _asset_confidence(asset: dict[str, Any]) -> str:
    confidences: list[str] = []
    for obj in asset.get("objects", []):
        confidences.extend(component.get("confidence", "exact") for component in obj["components"])
    confidences.extend(item.get("confidence", "exact") for item in asset.get("unity_events", []))
    confidences.extend(
        item.get("source_prefab", {}).get("confidence", "exact")
        for item in asset.get("prefab_instances", [])
    )
    confidences.extend(
        str(item.get("confidence", "exact")) for item in asset.get("references", [])
    )
    animator = asset.get("animator", {})
    for state in animator.get("states", []):
        if state.get("motion"):
            confidences.append(str(state["motion"].get("confidence", "exact")))
        confidences.extend(
            str(item.get("confidence", "exact")) for item in state.get("behaviours", [])
        )
    for blend_tree in animator.get("blend_trees", []):
        confidences.extend(
            str(item.get("motion", {}).get("confidence", "exact"))
            for item in blend_tree.get("children", [])
        )
    if "partial" in confidences or "unresolved" in confidences:
        return "partial"
    return "exact"


def _responsibility(asset: dict[str, Any]) -> str:
    kind = asset.get("kind", "asset").replace("_", " ").title()
    exact_events = [
        item for item in asset.get("unity_events", []) if item.get("confidence") == "exact"
    ]
    if exact_events:
        names = [f"{item['target_type']}.{item['method']}" for item in exact_events[:3]]
        return f"{kind} wiring " + ", ".join(f"`{name}`" for name in names) + "."
    if asset.get("kind") == "scriptable_object" and asset.get("script"):
        return f"ScriptableObject instance of `{asset['script'].get('qualified_name', '')}`."
    if asset.get("kind") == "animation_clip":
        clip = asset.get("animation_clip", {})
        sample_rate = clip.get("sample_rate")
        rate = f" sampled at {sample_rate:g} fps" if isinstance(sample_rate, (int, float)) else ""
        return (
            f"Animation clip `{clip.get('name', '')}`{rate} with "
            f"{clip.get('curve_count', 0)} curve(s) and "
            f"{len(clip.get('events', []))} animation event(s)."
        )
    if asset.get("kind") == "material":
        material = asset.get("material", {})
        texture_count = int(material.get("texture_reference_count", 0) or 0)
        texture_label = "texture reference" if texture_count == 1 else "texture references"
        shader = material.get("shader") or "an unresolved/built-in shader"
        return (
            f"Material `{material.get('name', '')}` using `{shader}` with "
            f"{texture_count} {texture_label}."
        )
    if asset.get("kind") == "mesh":
        mesh = asset.get("mesh", {})
        return (
            f"Mesh `{mesh.get('name', '')}` containing "
            f"{mesh.get('vertex_count', 0)} vertices across "
            f"{mesh.get('submesh_count', 0)} submesh(es)."
        )
    if asset.get("kind") == "model":
        model = asset.get("model", {})
        importer = asset.get("model_importer", {})
        rig = importer.get("rig", {})
        clips = importer.get("clips", [])
        rig_name = rig.get("animation_type", "unknown")
        return (
            f"FBX model `{PurePosixPath(asset['path']).stem}` with "
            f"{model.get('node_count', 0)} node(s), {model.get('mesh_count', 0)} mesh(es), "
            f"{model.get('skeleton', {}).get('bone_count', 0)} bone(s), and "
            f"{len(clips)} Unity clip split(s); rig `{rig_name}`."
        )
    if asset.get("kind") == "texture":
        editor = asset.get("editor_asset", {})
        facts = editor.get("facts", {})
        subassets = editor.get("subassets", [])
        source_dimensions = (
            f"{facts.get('source_width', '?')}×{facts.get('source_height', '?')}"
        )
        imported_dimensions = f"{facts.get('width', '?')}×{facts.get('height', '?')}"
        if subassets:
            names = [str(item.get("name", "")) for item in subassets[:4]]
            suffix = "…" if len(subassets) > 4 else ""
            return (
                f"Texture `{PurePosixPath(asset['path']).name}` source "
                f"{source_dimensions}, importing "
                f"{len(subassets)} Sprite subasset(s): {', '.join(names)}{suffix}."
            )
        if imported_dimensions != source_dimensions and "?" not in imported_dimensions:
            return (
                f"Texture `{PurePosixPath(asset['path']).name}` source {source_dimensions}; "
                f"current imported size {imported_dimensions}."
            )
        return f"Texture `{PurePosixPath(asset['path']).name}` source {source_dimensions}."
    if asset.get("kind") == "sprite_atlas":
        facts = asset.get("editor_asset", {}).get("facts", {})
        return (
            f"Sprite Atlas `{PurePosixPath(asset['path']).stem}` with "
            f"{facts.get('packable_count', '?')} packable(s)."
        )
    if asset.get("kind") == "audio_clip":
        facts = asset.get("editor_asset", {}).get("facts", {})
        return (
            f"Audio clip `{PurePosixPath(asset['path']).name}` using "
            f"`{facts.get('load_type', 'unknown')}` loading and "
            f"`{facts.get('compression_format', 'unknown')}` compression."
        )
    if asset.get("kind") == "video_clip":
        facts = asset.get("editor_asset", {}).get("facts", {})
        return (
            f"Video clip `{PurePosixPath(asset['path']).name}` at "
            f"{facts.get('width', '?')}×{facts.get('height', '?')}."
        )
    if asset.get("editor_asset"):
        label = asset.get("kind", "asset").replace("_", " ").title()
        return f"{label} `{PurePosixPath(asset['path']).name}` inspected by Unity Editor."
    animator = asset.get("animator", {})
    if animator:
        return (
            f"Animator controller defining {len(animator.get('layers', []))} layer(s), "
            f"{len(animator.get('states', []))} state(s), and "
            f"{len(animator.get('transitions', []))} transition(s)."
        )
    script_names = []
    for obj in asset.get("objects", []):
        for component in obj.get("components", []):
            script = component.get("script", {})
            if script.get("confidence") == "exact":
                script_names.append(script.get("qualified_name") or script.get("type"))
    if script_names:
        names = sorted(set(script_names))[:3]
        return (
            f"{kind} with {asset.get('object_count', 0)} GameObject(s) using project component(s) "
            + ", ".join(f"`{name}`" for name in names)
            + "."
        )
    return f"{kind} containing {asset.get('object_count', 0)} GameObject(s)."


def _high_signal(asset: dict[str, Any]) -> int:
    animator = asset.get("animator", {})
    semantic_art = any(
        asset.get(key)
        for key in ("animation_clip", "material", "mesh", "model")
    )
    editor_asset = asset.get("editor_asset", {})
    subasset_count = len(editor_asset.get("subassets", []))
    editor_signal = (
        (3 if subasset_count > 1 else 0)
        + (2 if asset.get("non_default_importer") else 0)
        + (2 if asset.get("kind") == "sprite_atlas" else 0)
    )
    return int(
        asset.get(
            "project_script_component_count",
            asset.get("script_component_count", 0),
        )
        * 3
        + len(asset.get("unity_events", [])) * 5
        + len(animator.get("states", []))
        + len(animator.get("transitions", []))
        + len(animator.get("blend_trees", [])) * 2
        + (4 if asset.get("kind") == "scriptable_object" else 0)
        + (1 if semantic_art else 0)
        + editor_signal
    )


def _kind_for_path(path: str) -> str:
    suffix = PurePosixPath(path).suffix.lower()
    return {
        ".unity": "scene",
        ".prefab": "prefab",
        ".controller": "animator_controller",
        ".overridecontroller": "override_controller",
        ".anim": "animation_clip",
        ".mat": "material",
        ".fbx": "model",
        ".png": "texture",
        ".jpg": "texture",
        ".jpeg": "texture",
        ".tga": "texture",
        ".tif": "texture",
        ".tiff": "texture",
        ".psd": "texture",
        ".exr": "texture",
        ".hdr": "texture",
        ".bmp": "texture",
        ".spriteatlas": "sprite_atlas",
        ".shader": "shader",
        ".shadergraph": "shader",
        ".shadersubgraph": "shader",
        ".wav": "audio_clip",
        ".mp3": "audio_clip",
        ".ogg": "audio_clip",
        ".aif": "audio_clip",
        ".aiff": "audio_clip",
        ".flac": "audio_clip",
        ".mp4": "video_clip",
        ".mov": "video_clip",
        ".webm": "video_clip",
        ".avi": "video_clip",
        ".ttf": "font",
        ".otf": "font",
    }.get(suffix, "asset")


def _ownership(path: str, entry: Any) -> str:
    metadata = getattr(entry, "metadata", {}) if entry is not None else {}
    return str(metadata.get("ownership") or classify_ownership(path))


def _normalize(path: str) -> str:
    return path.replace("\\", "/")


def _unquote(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        return value[1:-1]
    return value


def _as_int(value: str, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _as_number(value: str) -> int | float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return int(parsed) if parsed.is_integer() else parsed


def _as_bool(value: str, default: bool) -> bool:
    if str(value).strip() in {"0", "false", "False"}:
        return False
    if str(value).strip() in {"1", "true", "True"}:
        return True
    return default


__all__ = ["UnityRuntimeAnalysis", "analyze_unity_runtime"]
