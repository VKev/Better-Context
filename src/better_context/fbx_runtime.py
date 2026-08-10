"""Zero-dependency FBX and Unity ModelImporter inspection.

The FBX reader extracts structural scene facts only.  It deliberately avoids
evaluating transforms or animation curves, which belong to Autodesk's runtime
SDK.  Unity's adjacent ``.fbx.meta`` file remains the authority for import
settings, clip splits, humanoid mapping, and avatar references.
"""

from __future__ import annotations

import re
import struct
import zlib
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_BINARY_MAGIC = b"Kaydara FBX Binary  \x00\x1a\x00"
_FBX_TICKS_PER_SECOND = 46_186_158_000
_OBJECT_LINE = re.compile(
    r"^\s*(?P<kind>[A-Za-z][A-Za-z0-9]*):\s*"
    r'(?P<id>-?\d+),\s*"(?P<name>[^"]*)",\s*"(?P<subtype>[^"]*)"\s*\{'
)
_CONNECTION_LINE = re.compile(
    r'^\s*C:\s*"(?P<kind>O[OP])",\s*(?P<child>-?\d+),\s*(?P<parent>-?\d+)'
)
_ASCII_VERSION = re.compile(r"^\s*FBXVersion:\s*(\d+)", re.MULTILINE)
_META_FIELD = re.compile(r"^(?P<indent>\s*)(?P<key>[A-Za-z_][A-Za-z0-9_]*):\s*(?P<value>.*)$")
_META_LIST_FIELD = re.compile(
    r"^(?P<indent>\s*)-\s+(?P<key>[A-Za-z_][A-Za-z0-9_]*):\s*(?P<value>.*)$"
)
_OBJECT_REFERENCE = re.compile(
    r"\{[^{}]*\bfileID:\s*(?P<file_id>-?\d+)[^{}]*"
    r"\bguid:\s*(?P<guid>[0-9a-fA-F]{32})[^{}]*\}"
)

_ANIMATION_TYPES = {0: "none", 1: "legacy", 2: "generic", 3: "humanoid"}
_AVATAR_SETUPS = {0: "no_avatar", 1: "create_from_this_model", 2: "copy_from_other"}
_TIME_MODE_RATES: dict[int, float] = {
    0: 30.0,
    1: 120.0,
    2: 100.0,
    3: 60.0,
    4: 50.0,
    5: 48.0,
    6: 30.0,
    7: 30.0,
    8: 29.9700262,
    9: 29.9700262,
    10: 25.0,
    11: 24.0,
    12: 1000.0,
    13: 23.976,
}


class FbxParseError(ValueError):
    """Raised when the FBX envelope is malformed or unsupported."""


@dataclass
class _ArraySummary:
    length: int
    negative_count: int = 0
    minimum: int | float | None = None
    maximum: int | float | None = None


@dataclass
class _Node:
    name: str
    properties: list[Any] = field(default_factory=list)
    children: list[_Node] = field(default_factory=list)


@dataclass
class _SceneObject:
    object_id: int
    kind: str
    name: str
    subtype: str
    node: _Node | None = None
    values: dict[str, Any] = field(default_factory=dict)


@dataclass
class _MetaLine:
    number: int
    indent: int
    text: str


class _BinaryParser:
    def __init__(self, data: bytes) -> None:
        if not data.startswith(_BINARY_MAGIC) or len(data) < len(_BINARY_MAGIC) + 4:
            raise FbxParseError("Missing FBX binary header.")
        self.data = data
        self.version = struct.unpack_from("<I", data, len(_BINARY_MAGIC))[0]
        self.position = len(_BINARY_MAGIC) + 4
        self.wide = self.version >= 7500
        self.header_size = 25 if self.wide else 13
        self.node_count = 0

    def parse(self) -> list[_Node]:
        nodes: list[_Node] = []
        while self.position + self.header_size <= len(self.data):
            if self._is_null_record(self.position):
                self.position += self.header_size
                break
            nodes.append(self._node(0))
        return nodes

    def _is_null_record(self, offset: int) -> bool:
        return self.data[offset : offset + self.header_size] == b"\x00" * self.header_size

    def _node(self, depth: int) -> _Node:
        if depth > 256:
            raise FbxParseError("FBX node nesting exceeds 256 levels.")
        self.node_count += 1
        if self.node_count > 500_000:
            raise FbxParseError("FBX node count exceeds the safety limit.")

        start = self.position
        if self.wide:
            end_offset, property_count, property_length = struct.unpack_from(
                "<QQQ", self.data, start
            )
            name_length = self.data[start + 24]
        else:
            end_offset, property_count, property_length = struct.unpack_from(
                "<III", self.data, start
            )
            name_length = self.data[start + 12]
        if end_offset <= start or end_offset > len(self.data):
            raise FbxParseError(f"Invalid FBX node end offset {end_offset}.")
        if property_count > 10_000_000:
            raise FbxParseError("FBX property count exceeds the safety limit.")

        self.position += self.header_size
        name_end = self.position + name_length
        if name_end > end_offset:
            raise FbxParseError("FBX node name exceeds its record boundary.")
        name = self.data[self.position : name_end].decode("utf-8", errors="replace")
        self.position = name_end
        property_end = self.position + property_length
        if property_end > end_offset:
            raise FbxParseError("FBX property list exceeds its record boundary.")

        properties = [self._property(name) for _ in range(property_count)]
        if self.position > property_end:
            raise FbxParseError("FBX property payload exceeds its declared length.")
        self.position = property_end

        children: list[_Node] = []
        child_boundary = end_offset - self.header_size
        while self.position < child_boundary:
            if self._is_null_record(self.position):
                self.position += self.header_size
                break
            children.append(self._node(depth + 1))
        self.position = end_offset
        return _Node(name=name, properties=properties, children=children)

    def _property(self, node_name: str) -> Any:
        if self.position >= len(self.data):
            raise FbxParseError("Unexpected end of FBX property data.")
        code = chr(self.data[self.position])
        self.position += 1
        scalar_formats = {
            "Y": "<h",
            "C": "<?",
            "I": "<i",
            "F": "<f",
            "D": "<d",
            "L": "<q",
        }
        if code in scalar_formats:
            fmt = scalar_formats[code]
            size = struct.calcsize(fmt)
            if self.position + size > len(self.data):
                raise FbxParseError("Truncated FBX scalar property.")
            value = struct.unpack_from(fmt, self.data, self.position)[0]
            self.position += size
            return value
        if code in {"S", "R"}:
            length = self._uint32()
            end = self.position + length
            if end > len(self.data):
                raise FbxParseError("Truncated FBX byte/string property.")
            raw = self.data[self.position : end]
            self.position = end
            return raw.decode("utf-8", errors="replace") if code == "S" else raw
        if code in {"f", "d", "l", "i", "b", "c"}:
            return self._array_property(code, node_name)
        raise FbxParseError(f"Unsupported FBX property type {code!r}.")

    def _array_property(self, code: str, node_name: str) -> _ArraySummary:
        length = self._uint32()
        encoding = self._uint32()
        payload_length = self._uint32()
        end = self.position + payload_length
        if end > len(self.data):
            raise FbxParseError("Truncated FBX array property.")
        payload = self.data[self.position : end]
        self.position = end
        if node_name not in {"PolygonVertexIndex", "KeyTime"}:
            return _ArraySummary(length=length)
        if encoding == 1:
            try:
                payload = zlib.decompress(payload)
            except zlib.error as error:
                raise FbxParseError(f"Invalid compressed FBX array: {error}") from error
        elif encoding != 0:
            raise FbxParseError(f"Unsupported FBX array encoding {encoding}.")
        formats = {"i": "i", "l": "q", "f": "f", "d": "d", "b": "?", "c": "b"}
        item_format = formats[code]
        item_size = struct.calcsize("<" + item_format)
        expected = length * item_size
        if len(payload) < expected:
            raise FbxParseError("Decoded FBX array is shorter than declared.")
        values = (item[0] for item in struct.iter_unpack("<" + item_format, payload[:expected]))
        negative_count = 0
        minimum: int | float | None = None
        maximum: int | float | None = None
        for value in values:
            if isinstance(value, (int, float)):
                if value < 0:
                    negative_count += 1
                minimum = value if minimum is None else min(minimum, value)
                maximum = value if maximum is None else max(maximum, value)
        return _ArraySummary(
            length=length,
            negative_count=negative_count,
            minimum=minimum,
            maximum=maximum,
        )

    def _uint32(self) -> int:
        if self.position + 4 > len(self.data):
            raise FbxParseError("Truncated FBX integer property.")
        value = int(struct.unpack_from("<I", self.data, self.position)[0])
        self.position += 4
        return value


def inspect_fbx(
    fbx_path: Path,
    meta_path: Path,
    guid_to_assets: dict[str, list[str]],
) -> dict[str, Any]:
    """Inspect one FBX plus Unity's adjacent ModelImporter metadata."""
    result: dict[str, Any] = {
        "kind": "model",
        "status": "parsed",
        "confidence": "exact",
        "model": {},
        "model_importer": {},
        "references": [],
        "warnings": [],
    }
    raw = fbx_path.read_bytes()
    model_error = ""
    try:
        if raw.startswith(_BINARY_MAGIC):
            parser = _BinaryParser(raw)
            model = _model_from_nodes(parser.parse(), "binary", parser.version)
        else:
            source = raw.decode("utf-8-sig")
            model = _model_from_ascii(source)
        result["model"] = model
    except (FbxParseError, UnicodeDecodeError) as error:
        model_error = str(error)
        result["warnings"].append({"source": "fbx", "message": model_error})

    if meta_path.is_file():
        try:
            source = meta_path.read_text(encoding="utf-8-sig", errors="strict")
            importer, references = _model_importer(source, guid_to_assets)
            result["model_importer"] = importer
            result["references"] = references
        except (OSError, UnicodeDecodeError) as error:
            result["warnings"].append({"source": "meta", "message": str(error)})

    if not result["model"] and not result["model_importer"]:
        result["status"] = "unsupported_serialization"
        result["confidence"] = "unresolved"
    elif model_error or not result["model"] or not result["model_importer"]:
        result["confidence"] = "partial"
    return result


def _model_from_nodes(nodes: list[_Node], fmt: str, version: int) -> dict[str, Any]:
    objects_node = next((node for node in nodes if node.name == "Objects"), None)
    if objects_node is None:
        raise FbxParseError("FBX Objects section is missing.")
    objects: dict[int, _SceneObject] = {}
    for node in objects_node.children:
        if len(node.properties) < 3 or not isinstance(node.properties[0], int):
            continue
        object_id = int(node.properties[0])
        objects[object_id] = _SceneObject(
            object_id=object_id,
            kind=node.name,
            name=_object_name(node.properties[1]),
            subtype=_text(node.properties[2]),
            node=node,
            values=_properties70(node),
        )
    connections: list[tuple[str, int, int]] = []
    connections_node = next((node for node in nodes if node.name == "Connections"), None)
    if connections_node is not None:
        for node in connections_node.children:
            if node.name != "C" or len(node.properties) < 3:
                continue
            if not isinstance(node.properties[1], int) or not isinstance(node.properties[2], int):
                continue
            connections.append(
                (_text(node.properties[0]), int(node.properties[1]), int(node.properties[2]))
            )
    global_settings = next((node for node in nodes if node.name == "GlobalSettings"), None)
    settings = _properties70(global_settings) if global_settings is not None else {}
    return _build_model_summary(objects, connections, fmt, version, settings)


def _model_from_ascii(source: str) -> dict[str, Any]:
    version_match = _ASCII_VERSION.search(source)
    objects: dict[int, _SceneObject] = {}
    for line in source.splitlines():
        match = _OBJECT_LINE.match(line)
        if match:
            object_id = int(match.group("id"))
            objects[object_id] = _SceneObject(
                object_id=object_id,
                kind=match.group("kind"),
                name=_object_name(match.group("name")),
                subtype=match.group("subtype"),
            )
    connections = [
        (match.group("kind"), int(match.group("child")), int(match.group("parent")))
        for line in source.splitlines()
        if (match := _CONNECTION_LINE.match(line))
    ]
    if not objects:
        raise FbxParseError("ASCII FBX Objects section contains no supported objects.")
    return _build_model_summary(
        objects,
        connections,
        "ascii",
        int(version_match.group(1)) if version_match else 0,
        {},
    )


def _build_model_summary(
    objects: dict[int, _SceneObject],
    connections: list[tuple[str, int, int]],
    fmt: str,
    version: int,
    settings: dict[str, Any],
) -> dict[str, Any]:
    children_by_parent: dict[int, list[int]] = defaultdict(list)
    model_parent: dict[int, int] = {}
    for kind, child, parent in connections:
        if kind not in {"OO", "OP"}:
            continue
        children_by_parent[parent].append(child)
        child_obj = objects.get(child)
        parent_obj = objects.get(parent)
        if child_obj and parent_obj and child_obj.kind == parent_obj.kind == "Model":
            model_parent[child] = parent

    model_ids = sorted(object_id for object_id, item in objects.items() if item.kind == "Model")
    root_ids = [object_id for object_id in model_ids if object_id not in model_parent]

    def hierarchy(object_id: int, depth: int, seen: set[int]) -> dict[str, Any]:
        item = objects[object_id]
        if object_id in seen:
            return {"id": str(object_id), "name": item.name, "type": item.subtype, "cycle": True}
        next_seen = {*seen, object_id}
        geometry = [
            objects[child].name
            for child in children_by_parent.get(object_id, [])
            if child in objects and objects[child].kind == "Geometry"
        ]
        materials = [
            objects[child].name
            for child in children_by_parent.get(object_id, [])
            if child in objects and objects[child].kind == "Material"
        ]
        result: dict[str, Any] = {
            "id": str(object_id),
            "name": item.name,
            "type": item.subtype or "Null",
            "depth": depth,
            "children": [
                hierarchy(child, depth + 1, next_seen)
                for child in sorted(children_by_parent.get(object_id, []))
                if child in objects and objects[child].kind == "Model"
            ],
        }
        if geometry:
            result["geometry"] = sorted(geometry)
        if materials:
            result["materials"] = sorted(materials)
        return result

    geometries = [item for item in objects.values() if item.kind == "Geometry"]
    meshes: list[dict[str, Any]] = []
    for item in sorted(geometries, key=lambda current: (current.name, current.object_id)):
        if item.subtype != "Mesh":
            continue
        vertices = _array_child(item.node, "Vertices")
        polygons = _array_child(item.node, "PolygonVertexIndex")
        owners = [
            objects[parent].name
            for _, child, parent in connections
            if child == item.object_id and parent in objects and objects[parent].kind == "Model"
        ]
        meshes.append(
            {
                "name": item.name,
                "control_point_count": vertices.length // 3 if vertices else 0,
                "polygon_vertex_count": polygons.length if polygons else 0,
                "polygon_count": polygons.negative_count if polygons else 0,
                "models": sorted(set(owners)),
            }
        )

    materials = [
        {
            "name": item.name,
            "models": sorted(
                {
                    objects[parent].name
                    for _, child, parent in connections
                    if child == item.object_id
                    and parent in objects
                    and objects[parent].kind == "Model"
                }
            ),
        }
        for item in sorted(objects.values(), key=lambda current: (current.name, current.object_id))
        if item.kind == "Material"
    ]
    textures = sorted(
        {item.name for item in objects.values() if item.kind in {"Texture", "Video"} and item.name}
    )

    bone_ids = {
        object_id
        for object_id, item in objects.items()
        if item.kind == "Model" and item.subtype in {"LimbNode", "Root"}
    }
    bone_roots = sorted(
        object_id for object_id in bone_ids if model_parent.get(object_id) not in bone_ids
    )
    skeleton = {
        "bone_count": len(bone_ids),
        "root_bones": [objects[object_id].name for object_id in bone_roots],
        "bones": [
            {
                "name": objects[object_id].name,
                "parent": objects[model_parent[object_id]].name
                if model_parent.get(object_id) in objects
                else "",
            }
            for object_id in sorted(bone_ids, key=lambda value: objects[value].name)
        ],
    }

    time_mode = _integer(settings.get("TimeMode"), 0)
    custom_rate = _number(settings.get("CustomFrameRate"))
    frame_rate = custom_rate if time_mode == 14 and custom_rate else _TIME_MODE_RATES.get(time_mode)
    animation_stacks: list[dict[str, Any]] = []
    for item in sorted(objects.values(), key=lambda current: (current.name, current.object_id)):
        if item.kind != "AnimationStack":
            continue
        descendants = _descendants(item.object_id, children_by_parent)
        start_ticks = _integer(item.values.get("LocalStart"), 0)
        stop_ticks = _integer(item.values.get("LocalStop"), 0)
        stack: dict[str, Any] = {
            "name": item.name,
            "layer_count": sum(
                1
                for value in descendants
                if objects.get(value) and objects[value].kind == "AnimationLayer"
            ),
            "curve_count": sum(
                1
                for value in descendants
                if objects.get(value) and objects[value].kind == "AnimationCurve"
            ),
        }
        if frame_rate:
            stack["frame_rate"] = frame_rate
        if stop_ticks >= start_ticks and (start_ticks or stop_ticks):
            stack["start_seconds"] = start_ticks / _FBX_TICKS_PER_SECOND
            stack["end_seconds"] = stop_ticks / _FBX_TICKS_PER_SECOND
            if frame_rate:
                stack["first_frame"] = round(stack["start_seconds"] * frame_rate, 3)
                stack["last_frame"] = round(stack["end_seconds"] * frame_rate, 3)
        animation_stacks.append(stack)

    return {
        "format": fmt,
        "fbx_version": version,
        "node_count": len(model_ids),
        "root_nodes": [hierarchy(object_id, 0, set()) for object_id in root_ids],
        "mesh_count": len(meshes),
        "meshes": meshes,
        "material_count": len(materials),
        "materials": materials,
        "texture_count": len(textures),
        "textures": textures,
        "skeleton": skeleton,
        "animation_stack_count": len(animation_stacks),
        "animation_stacks": animation_stacks,
    }


def _model_importer(
    source: str,
    guid_to_assets: dict[str, list[str]],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    lines = [
        _MetaLine(number, len(line) - len(line.lstrip()), line.strip())
        for number, line in enumerate(source.splitlines(), start=1)
        if line.strip() and not line.lstrip().startswith("#")
    ]
    model = _section(lines, ["ModelImporter"])
    if not model:
        return {}, []
    root_values = _direct_values(model)
    animations = _section(model, ["animations"])
    meshes = _section(model, ["meshes"])
    materials = _section(model, ["materials"])
    human = _list_maps(_section(model, ["humanDescription", "human"]))
    skeleton_items = _list_maps(_section(model, ["humanDescription", "skeleton"]))
    clips = _clip_maps(_section(model, ["animations", "clipAnimations"]))

    animation_type = _integer(root_values.get("animationType"), 0)
    avatar_setup = _integer(root_values.get("avatarSetup"), 0)
    importer: dict[str, Any] = {
        "serialized_version": _integer(root_values.get("serializedVersion"), 0),
        "import_animation": _boolean(root_values.get("importAnimation"), False),
        "rig": {
            "animation_type": _ANIMATION_TYPES.get(animation_type, f"unknown:{animation_type}"),
            "animation_type_value": animation_type,
            "avatar_setup": _AVATAR_SETUPS.get(avatar_setup, f"unknown:{avatar_setup}"),
            "avatar_setup_value": avatar_setup,
            "auto_map": _boolean(root_values.get("autoGenerateAvatarMappingIfUnspecified"), False),
            "humanoid_bones": [
                {
                    "bone": item.get("boneName", ""),
                    "human": item.get("humanName", ""),
                }
                for item in human
                if item.get("boneName") or item.get("humanName")
            ],
        },
        "animation": _selected_values(
            _direct_values(animations),
            {
                "resampleCurves": "resample_curves",
                "optimizeGameObjects": "optimize_game_objects",
                "animationCompression": "compression",
                "animationRotationError": "rotation_error",
                "animationPositionError": "position_error",
                "animationScaleError": "scale_error",
                "animationWrapMode": "wrap_mode",
                "isReadable": "is_readable",
            },
        ),
        "clips": clips,
        "mesh": _selected_values(
            _direct_values(meshes),
            {
                "globalScale": "global_scale",
                "meshCompression": "compression",
                "addColliders": "add_colliders",
                "importBlendShapes": "import_blend_shapes",
                "importCameras": "import_cameras",
                "importLights": "import_lights",
                "preserveHierarchy": "preserve_hierarchy",
                "maxBonesPerVertex": "max_bones_per_vertex",
                "optimizeBones": "optimize_bones",
                "useFileScale": "use_file_scale",
                "useFileUnits": "use_file_units",
                "generateSecondaryUV": "generate_secondary_uv",
            },
        ),
        "materials": _selected_values(
            _direct_values(materials),
            {
                "materialImportMode": "import_mode",
                "materialName": "name_mode",
                "materialSearch": "search_mode",
                "materialLocation": "location",
            },
        ),
        "skeleton": {
            "node_count": len(skeleton_items),
            "roots": [
                item.get("name", "") for item in skeleton_items if not item.get("parentName")
            ],
            "nodes": [
                {"name": item.get("name", ""), "parent": item.get("parentName", "")}
                for item in skeleton_items
                if item.get("name")
            ],
        },
    }

    references: list[dict[str, Any]] = []
    for line in model:
        match = _META_FIELD.match(" " * line.indent + line.text)
        if not match or match.group("key") != "lastHumanDescriptionAvatarSource":
            continue
        reference = _OBJECT_REFERENCE.search(match.group("value"))
        if not reference:
            continue
        guid = reference.group("guid").lower()
        targets = guid_to_assets.get(guid, [])
        item = {
            "document_file_id": "ModelImporter",
            "field": "lastHumanDescriptionAvatarSource",
            "file_id": reference.group("file_id"),
            "guid": guid,
            "target": targets[0] if len(targets) == 1 else "",
            "candidates": targets,
            "confidence": "exact"
            if len(targets) == 1
            else ("partial" if targets else "unresolved"),
            "reason": "meta_guid",
            "line": line.number,
        }
        references.append(item)
        importer["rig"]["avatar_source"] = item.get("target") or ""
    return importer, references


def _section(lines: list[_MetaLine], path: list[str]) -> list[_MetaLine]:
    current = lines
    parent_indent = -1
    for key in path:
        index = -1
        field_indent = -1
        for candidate_index, line in enumerate(current):
            match = _META_FIELD.match(" " * line.indent + line.text)
            if not match or match.group("key") != key:
                continue
            if line.indent <= parent_indent:
                continue
            index = candidate_index
            field_indent = line.indent
            break
        if index < 0:
            return []
        end = len(current)
        for candidate_index in range(index + 1, len(current)):
            line = current[candidate_index]
            if line.indent < field_indent or (
                line.indent == field_indent and not line.text.startswith("- ")
            ):
                end = candidate_index
                break
        current = current[index + 1 : end]
        parent_indent = field_indent
    return current


def _direct_values(lines: list[_MetaLine]) -> dict[str, str]:
    if not lines:
        return {}
    direct_indent = min(line.indent for line in lines)
    values: dict[str, str] = {}
    for line in lines:
        if line.indent != direct_indent:
            continue
        match = _META_FIELD.match(" " * line.indent + line.text)
        if match and match.group("value"):
            values[match.group("key")] = _unquote(match.group("value"))
    return values


def _list_maps(lines: list[_MetaLine]) -> list[dict[str, str]]:
    return [_group_values(group) for group in _list_groups(lines)]


def _list_groups(lines: list[_MetaLine]) -> list[list[_MetaLine]]:
    if not lines:
        return []
    candidates = [line.indent for line in lines if line.text.startswith("- ")]
    if not candidates:
        return []
    list_indent = min(candidates)
    groups: list[list[_MetaLine]] = []
    current: list[_MetaLine] = []
    for line in lines:
        if line.indent == list_indent and line.text.startswith("- "):
            if current:
                groups.append(current)
            current = [line]
        elif current:
            current.append(line)
    if current:
        groups.append(current)
    return groups


def _group_values(group: list[_MetaLine]) -> dict[str, str]:
    values: dict[str, str] = {}
    if not group:
        return values
    list_indent = group[0].indent
    first = _META_LIST_FIELD.match(" " * group[0].indent + group[0].text)
    if first:
        values[first.group("key")] = _unquote(first.group("value"))
    direct_indent = list_indent + 2
    for line in group[1:]:
        if line.indent != direct_indent:
            continue
        match = _META_FIELD.match(" " * line.indent + line.text)
        if match and match.group("value"):
            values[match.group("key")] = _unquote(match.group("value"))
    return values


def _clip_maps(lines: list[_MetaLine]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for group in _list_groups(lines):
        values = _group_values(group)
        if not values.get("name") and not values.get("takeName"):
            continue
        event_names: list[str] = []
        event_count = 0
        for index, line in enumerate(group):
            if line.text != "events:":
                continue
            event_indent = line.indent
            for following in group[index + 1 :]:
                if following.indent < event_indent or (
                    following.indent == event_indent and not following.text.startswith("- ")
                ):
                    break
                if following.text.startswith("- "):
                    event_count += 1
                match = _META_FIELD.match(" " * following.indent + following.text)
                if match and match.group("key") == "functionName" and match.group("value"):
                    event_names.append(_unquote(match.group("value")))
            break
        result.append(
            {
                "name": values.get("name", ""),
                "take_name": values.get("takeName", ""),
                "internal_id": values.get("internalID", ""),
                "first_frame": _number(values.get("firstFrame")),
                "last_frame": _number(values.get("lastFrame")),
                "loop": _boolean(values.get("loop"), False),
                "loop_time": _boolean(values.get("loopTime"), False),
                "mirror": _boolean(values.get("mirror"), False),
                "event_count": event_count,
                "events": event_names,
            }
        )
    return result


def _selected_values(values: dict[str, str], names: dict[str, str]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    boolean_names = {
        "resampleCurves",
        "optimizeGameObjects",
        "isReadable",
        "addColliders",
        "importBlendShapes",
        "importCameras",
        "importLights",
        "preserveHierarchy",
        "optimizeBones",
        "useFileScale",
        "useFileUnits",
        "generateSecondaryUV",
    }
    for source, destination in names.items():
        if source not in values:
            continue
        result[destination] = (
            _boolean(values[source], False)
            if source in boolean_names
            else (
                _number(values[source]) if _number(values[source]) is not None else values[source]
            )
        )
    return result


def _properties70(node: _Node | None) -> dict[str, Any]:
    if node is None:
        return {}
    properties = next((child for child in node.children if child.name == "Properties70"), None)
    if properties is None:
        return {}
    values: dict[str, Any] = {}
    for child in properties.children:
        if child.name == "P" and len(child.properties) >= 5:
            values[_text(child.properties[0])] = child.properties[-1]
    return values


def _array_child(node: _Node | None, name: str) -> _ArraySummary | None:
    if node is None:
        return None
    child = next((item for item in node.children if item.name == name), None)
    if child and child.properties and isinstance(child.properties[0], _ArraySummary):
        return child.properties[0]
    return None


def _descendants(root: int, children_by_parent: dict[int, list[int]]) -> set[int]:
    result: set[int] = set()
    pending = list(children_by_parent.get(root, []))
    while pending:
        current = pending.pop()
        if current in result:
            continue
        result.add(current)
        pending.extend(children_by_parent.get(current, []))
    return result


def _object_name(value: Any) -> str:
    text = _text(value).split("\x00", 1)[0]
    return text.split("::", 1)[-1]


def _text(value: Any) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def _integer(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _number(value: Any) -> int | float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return int(parsed) if parsed.is_integer() else parsed


def _boolean(value: Any, default: bool) -> bool:
    if str(value).strip().casefold() in {"0", "false"}:
        return False
    if str(value).strip().casefold() in {"1", "true"}:
        return True
    return default


def _unquote(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        return value[1:-1]
    return value


__all__ = ["FbxParseError", "inspect_fbx"]
