from __future__ import annotations

import struct
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from better_context.fbx_runtime import inspect_fbx
from better_context.scanner import walk_repository
from better_context.unity_runtime import analyze_unity_runtime

_MAGIC = b"Kaydara FBX Binary  \x00\x1a\x00"


@dataclass
class _Array:
    code: str
    values: list[int | float]


@dataclass
class _NodeSpec:
    name: str
    properties: list[Any]
    children: list[_NodeSpec]


def _property(value: Any) -> bytes:
    if isinstance(value, str):
        payload = value.encode("utf-8")
        return b"S" + struct.pack("<I", len(payload)) + payload
    if isinstance(value, int):
        return b"L" + struct.pack("<q", value)
    if isinstance(value, _Array):
        item_format = {"i": "i", "d": "d"}[value.code]
        payload = struct.pack(f"<{len(value.values)}{item_format}", *value.values)
        return (
            value.code.encode("ascii")
            + struct.pack("<III", len(value.values), 0, len(payload))
            + payload
        )
    raise TypeError(value)


def _node(spec: _NodeSpec, start: int) -> bytes:
    name = spec.name.encode("utf-8")
    properties = b"".join(_property(value) for value in spec.properties)
    child_start = start + 13 + len(name) + len(properties)
    children: list[bytes] = []
    for child in spec.children:
        encoded = _node(child, child_start + sum(len(value) for value in children))
        children.append(encoded)
    child_payload = b"".join(children) + (b"\x00" * 13 if children else b"")
    end_offset = start + 13 + len(name) + len(properties) + len(child_payload)
    header = struct.pack(
        "<IIIB",
        end_offset,
        len(spec.properties),
        len(properties),
        len(name),
    )
    return header + name + properties + child_payload


def _p(name: str, value: int) -> _NodeSpec:
    return _NodeSpec("P", [name, "KTime", "Time", "", value], [])


def _binary_fbx() -> bytes:
    objects = _NodeSpec(
        "Objects",
        [],
        [
            _NodeSpec("Model", [1, "Model::Root", "Null"], []),
            _NodeSpec("Model", [2, "Model::Hips", "LimbNode"], []),
            _NodeSpec(
                "Geometry",
                [3, "Geometry::Body", "Mesh"],
                [
                    _NodeSpec("Vertices", [_Array("d", [0.0] * 9)], []),
                    _NodeSpec("PolygonVertexIndex", [_Array("i", [0, 1, -3])], []),
                ],
            ),
            _NodeSpec("Material", [4, "Material::BodyMat", ""], []),
            _NodeSpec(
                "AnimationStack",
                [5, "AnimStack::Take 001", ""],
                [
                    _NodeSpec(
                        "Properties70",
                        [],
                        [_p("LocalStart", 0), _p("LocalStop", 2 * 46_186_158_000)],
                    )
                ],
            ),
            _NodeSpec("AnimationLayer", [6, "AnimLayer::BaseLayer", ""], []),
            _NodeSpec("AnimationCurve", [7, "AnimCurve::Rotation", ""], []),
        ],
    )
    connections = _NodeSpec(
        "Connections",
        [],
        [
            _NodeSpec("C", ["OO", 2, 1], []),
            _NodeSpec("C", ["OO", 3, 2], []),
            _NodeSpec("C", ["OO", 4, 2], []),
            _NodeSpec("C", ["OO", 6, 5], []),
            _NodeSpec("C", ["OO", 7, 6], []),
        ],
    )
    settings = _NodeSpec(
        "GlobalSettings",
        [],
        [_NodeSpec("Properties70", [], [_p("TimeMode", 6)])],
    )
    start = len(_MAGIC) + 4
    payload = b""
    for spec in (objects, connections, settings):
        payload += _node(spec, start + len(payload))
    return _MAGIC + struct.pack("<I", 7400) + payload + b"\x00" * 13


def _meta(guid: str, avatar_guid: str) -> str:
    return f"""fileFormatVersion: 2
guid: {guid}
ModelImporter:
  serializedVersion: 22200
  materials:
    materialImportMode: 2
    materialName: 0
    materialSearch: 1
    materialLocation: 1
  animations:
    resampleCurves: 1
    optimizeGameObjects: 0
    animationCompression: 3
    clipAnimations:
    - serializedVersion: 16
      name: Take 001
      takeName: Take 001
      internalID: 1827226128182048838
      firstFrame: 0
      lastFrame: 60
      loop: 1
      loopTime: 1
      mirror: 0
      events:
      - time: 0.5
        functionName: Fire
  meshes:
    globalScale: 1
    importBlendShapes: 1
    preserveHierarchy: 1
    maxBonesPerVertex: 4
  importAnimation: 1
  humanDescription:
    human:
    - boneName: Hips
      humanName: Hips
    skeleton:
    - name: Root
      parentName:
    - name: Hips
      parentName: Root
  lastHumanDescriptionAvatarSource: {{fileID: 9000000, guid: {avatar_guid}, type: 3}}
  animationType: 3
  avatarSetup: 2
  autoGenerateAvatarMappingIfUnspecified: 1
"""


def test_binary_fbx_and_model_importer_are_inspected(tmp_path: Path) -> None:
    fbx = tmp_path / "Hero.fbx"
    fbx.write_bytes(_binary_fbx())
    meta = tmp_path / "Hero.fbx.meta"
    meta.write_text(_meta("a" * 32, "b" * 32), encoding="utf-8")

    result = inspect_fbx(
        fbx,
        meta,
        {"b" * 32: ["Assets/Avatar.fbx"]},
    )

    assert result["status"] == "parsed"
    assert result["confidence"] == "exact"
    assert result["model"]["format"] == "binary"
    assert result["model"]["fbx_version"] == 7400
    assert result["model"]["node_count"] == 2
    assert result["model"]["root_nodes"][0]["children"][0]["name"] == "Hips"
    assert result["model"]["meshes"] == [
        {
            "name": "Body",
            "control_point_count": 3,
            "polygon_vertex_count": 3,
            "polygon_count": 1,
            "models": ["Hips"],
        }
    ]
    assert result["model"]["materials"] == [{"name": "BodyMat", "models": ["Hips"]}]
    assert result["model"]["skeleton"]["bone_count"] == 1
    assert result["model"]["animation_stacks"][0]["last_frame"] == 60.0
    importer = result["model_importer"]
    assert importer["rig"]["animation_type"] == "humanoid"
    assert importer["rig"]["avatar_setup"] == "copy_from_other"
    assert importer["rig"]["humanoid_bones"] == [{"bone": "Hips", "human": "Hips"}]
    assert importer["skeleton"]["node_count"] == 2
    assert importer["clips"][0]["events"] == ["Fire"]
    assert importer["clips"][0]["event_count"] == 1
    assert result["references"][0]["target"] == "Assets/Avatar.fbx"


def test_ascii_fbx_is_inspected_without_an_external_dependency(tmp_path: Path) -> None:
    fbx = tmp_path / "Simple.fbx"
    fbx.write_text(
        """FBXHeaderExtension: {
  FBXVersion: 7400
}
Objects: {
  Model: 1, "Model::Root", "Null" {
  }
  Geometry: 2, "Geometry::Body", "Mesh" {
  }
}
Connections: {
  C: "OO", 2, 1
}
""",
        encoding="utf-8",
    )

    result = inspect_fbx(fbx, tmp_path / "missing.meta", {})

    assert result["status"] == "parsed"
    assert result["confidence"] == "partial"
    assert result["model"]["format"] == "ascii"
    assert result["model"]["fbx_version"] == 7400
    assert result["model"]["root_nodes"][0]["geometry"] == ["Body"]


def test_scanner_indexes_oversized_fbx_for_staleness(tmp_path: Path) -> None:
    path = tmp_path / "Model.fbx"
    prefix = _binary_fbx() + b"padding" * 10_000
    path.write_bytes(prefix + b"first tail")

    inventory = walk_repository(tmp_path, max_file_size_kb=1)

    entry = next(item for item in inventory.files if item.path == "Model.fbx")
    assert entry.is_binary is True
    assert entry.content_hash
    assert "Model.fbx" not in inventory.skipped_binary
    assert "Model.fbx" not in inventory.skipped_too_large

    path.write_bytes(prefix + b"other tail")
    changed = walk_repository(tmp_path, max_file_size_kb=1)
    changed_entry = next(item for item in changed.files if item.path == "Model.fbx")
    assert changed_entry.content_hash != entry.content_hash


def test_unity_runtime_exposes_fbx_and_avatar_dependency(tmp_path: Path) -> None:
    assets = tmp_path / "Assets"
    assets.mkdir()
    hero = assets / "Hero.fbx"
    avatar = assets / "Avatar.fbx"
    hero.write_bytes(_binary_fbx())
    avatar.write_bytes(_binary_fbx())
    (assets / "Hero.fbx.meta").write_text(_meta("a" * 32, "b" * 32), encoding="utf-8")
    (assets / "Avatar.fbx.meta").write_text(
        f"fileFormatVersion: 2\nguid: {'b' * 32}\n", encoding="utf-8"
    )
    inventory = walk_repository(tmp_path)
    entries = [
        SimpleNamespace(path=item.path, chunks=[], metadata={"ownership": "project-owned"})
        for item in inventory.files
    ]

    result = analyze_unity_runtime(tmp_path, inventory, entries)

    runtime = result.assets["Assets/Hero.fbx"]
    assert runtime["kind"] == "model"
    assert runtime["model_importer"]["clips"][0]["name"] == "Take 001"
    assert any(
        edge["source"] == "Assets/Hero.fbx"
        and edge["target"] == "Assets/Avatar.fbx"
        and edge["kinds"] == ["serialized_guid"]
        for edge in result.edge_details
    )
    assert result.summary["metrics"]["models"] == 2
