"""Shader/UI/custom importer regression fixtures through the actual runtime pipeline."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from better_context.scanner import walk_repository
from better_context.unity_editor import compute_editor_source_hash, normalize_editor_snapshot
from better_context.unity_runtime import analyze_unity_runtime
from better_context.unity_sources import inspect_source_asset


def write(root: Path, path: str, content: str | bytes, guid: str | None = None) -> None:
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(content.encode() if isinstance(content, str) else content)
    if guid:
        target.with_name(target.name + ".meta").write_text(f"guid: {guid}\n")


def analyze(root: Path, snapshot: dict | None = None):
    return analyze_unity_runtime(root, walk_repository(root), [], editor_snapshot=snapshot)


def test_shader_ui_dependency_chain_not_false_yaml(tmp_path: Path) -> None:
    write(
        tmp_path,
        "Assets/UI/Main.uxml",
        '<ui:UXML xmlns:ui="UnityEngine.UIElements"><Style src="Main.uss"/>'
        '<ui:Button name="play" text="Play" class="primary"/></ui:UXML>',
        "1" * 32,
    )
    write(
        tmp_path,
        "Assets/UI/Main.uss",
        '/* url("fake.png") */\n.primary { background-image: url("../Textures/icon.png"); }',
        "2" * 32,
    )
    write(tmp_path, "Assets/Textures/icon.png", b"\x89PNG\0", "3" * 32)
    write(
        tmp_path,
        "Assets/Shaders/Lit.shader",
        'Shader "Game/Lit" {\nProperties {\n_Color ("Tint", Color) = (1,1,1,1)\n}\n'
        '#include "Shared.hlsl"\n// #include "Missing.hlsl"\n}',
        "4" * 32,
    )
    write(tmp_path, "Assets/Shaders/Shared.hlsl", "float4 Tint;", "5" * 32)
    result = analyze(tmp_path)
    assert not result.errors
    edges = {(edge["source"], edge["target"]) for edge in result.edge_details}
    assert edges == {
        ("Assets/UI/Main.uxml", "Assets/UI/Main.uss"),
        ("Assets/UI/Main.uss", "Assets/Textures/icon.png"),
        ("Assets/Shaders/Lit.shader", "Assets/Shaders/Shared.hlsl"),
    }
    assert result.assets["Assets/UI/Main.uxml"]["source_asset"]["elements"][-1]["name"] == "play"
    assert result.assets["Assets/Shaders/Lit.shader"]["source_asset"]["properties"] == ["_Color"]
    assert result.assets["Assets/Textures/icon.png"]["inspection"] == "inventory-only"


def test_shadergraph_multi_json_texture_and_subgraph_guids(tmp_path: Path) -> None:
    write(tmp_path, "Assets/Textures/icon.png", b"\x89PNG\0", "1" * 32)
    write(tmp_path, "Assets/Shared.shadersubgraph", '{"m_Type":"GraphData"}', "2" * 32)
    texture = json.dumps({"texture": {"fileID": 2800000, "guid": "1" * 32}})
    graph = [
        {"m_Type": "GraphData", "m_Guid": "1" * 32},  # random ID isn't an asset reference
        {"m_Type": "Texture2DShaderProperty", "m_Name": "Icon", "m_SerializedTexture": texture},
        {"m_Type": "SubGraphNode", "m_SubGraphGUID": "2" * 32},
    ]
    write(tmp_path, "Assets/Example.shadergraph", "\n\n".join(map(json.dumps, graph)), "3" * 32)
    result = analyze(tmp_path)
    assert not result.errors
    asset = result.assets["Assets/Example.shadergraph"]
    assert asset["source_asset"]["object_count"] == 3
    assert asset["source_asset"]["property_names"] == ["Icon"]
    assert {ref["target"] for ref in asset["references"]} == {
        "Assets/Textures/icon.png",
        "Assets/Shared.shadersubgraph",
    }
    assert len(asset["references"]) == 2


def test_custom_binary_and_extensionless_assets_retained(tmp_path: Path) -> None:
    write(tmp_path, "Assets/Custom/data.customformat", b"\0\xff" * 2000, "1" * 32)
    write(tmp_path, "Assets/Custom/noextension", b"\0\xff", "2" * 32)
    inventory = walk_repository(tmp_path, max_file_size_kb=1)
    assert {"Assets/Custom/data.customformat", "Assets/Custom/noextension"} <= {
        item.path for item in inventory.files
    }
    result = analyze_unity_runtime(tmp_path, inventory, [])
    assert len(result.assets) == 2
    assert all(item["confidence"] == "partial" for item in result.assets.values())
    assert not result.errors


def test_custom_editor_metadata_and_exact_subasset_reference(tmp_path: Path) -> None:
    write(tmp_path, "Assets/data.custom", b"\0\xff", "1" * 32)
    write(tmp_path, "Assets/icon.png", b"\0PNG", "2" * 32)
    snapshot = normalize_editor_snapshot(
        {
            "assets": [
                {
                    "path": "Assets/data.custom",
                    "guid": "1" * 32,
                    "kind": "asset",
                    "type_name": "Game.CustomData",
                    "facts": [{"name": "serialized.count", "value": "3"}],
                    "dependencies": ["Assets/icon.png"],
                    "references": [
                        {
                            "field": "icon",
                            "target": "Assets/icon.png",
                            "guid": "2" * 32,
                            "local_id": 21300000,
                        }
                    ],
                    "subassets": [
                        {"name": "Inner", "local_id": 42, "type_name": "Game.Inner", "facts": []}
                    ],
                }
            ]
        }
    )
    asset = analyze(tmp_path, snapshot).assets["Assets/data.custom"]
    assert asset["editor_asset"]["type_name"] == "Game.CustomData"
    assert asset["subasset_count"] == 1
    assert any(
        item["file_id"] == "21300000" and item["field"] == "icon" for item in asset["references"]
    )


def test_uxml_guid_url_and_duplicate_guid_are_not_guessed() -> None:
    source = (
        '<UXML><Style src="project://database/Assets/Style.uss?guid='
        + "1" * 32
        + '&amp;fileID=42"/></UXML>'
    )
    result = inspect_source_asset(
        "Assets/Main.uxml", source, set(), {"1" * 32: ["Assets/A.uss", "Assets/B.uss"]}
    )
    assert result["references"][0]["confidence"] == "unresolved"
    assert not result["references"][0]["target"]


@pytest.mark.parametrize(
    "extension,content",
    [
        (".uxml", "<UXML>"),
        (".uxml", '<!DOCTYPE x [<!ENTITY y "x">]><UXML/>'),
        (".shadergraph", '{"m_Type": invalid}'),
        (".inputactions", "{"),
    ],
)
def test_malformed_sources_have_explicit_coverage_errors(tmp_path, extension, content) -> None:
    path = "Assets/Broken" + extension
    write(tmp_path, path, content)
    result = analyze(tmp_path)
    assert result.assets[path]["status"] == "parse_error"
    assert result.errors[0]["error_type"] == "source_parse_error"


def test_compute_and_input_action_structure() -> None:
    compute = inspect_source_asset(
        "Assets/Sim.compute",
        '#pragma kernel Step\n#include "Common.hlsl"',
        {"Assets/Common.hlsl"},
        {},
    )
    assert compute["source_asset"]["kernels"] == ["Step"]
    assert compute["references"][0]["target"] == "Assets/Common.hlsl"
    actions = inspect_source_asset(
        "Assets/Controls.inputactions",
        '{"maps":[{"name":"Player","actions":[{"name":"Jump"}],"bindings":[{}]}]}',
        set(),
        {},
    )
    assert actions["source_asset"]["maps"] == [
        {"name": "Player", "actions": ["Jump"], "binding_count": 1},
    ]


def test_snapshot_invalidates_on_custom_assets_ui_and_hlsl(tmp_path: Path) -> None:
    for path in ["Assets/Main.uxml", "Assets/Shared.hlsl", "Assets/Data.custom"]:
        before = compute_editor_source_hash(tmp_path)
        write(tmp_path, path, "first")
        assert compute_editor_source_hash(tmp_path) != before
    before = compute_editor_source_hash(tmp_path)
    write(tmp_path, "Assets/AGENTS.md", "map generated after snapshot")
    assert compute_editor_source_hash(tmp_path) == before


def test_style_literals_and_comments_do_not_invent_edges() -> None:
    result = inspect_source_asset(
        "Assets/Main.uss",
        """/* url("fake.png") */ .label { content: 'url("fake.png")'; }
        @import "base.uss";
        .image { background-image: url("real.png"); }""",
        {"Assets/fake.png", "Assets/base.uss", "Assets/real.png"},
        {},
    )
    assert {item["target"] for item in result["references"]} == {
        "Assets/base.uss",
        "Assets/real.png",
    }


def test_tail_source_and_binary_edits_invalidate_inventory_hash(tmp_path: Path) -> None:
    import os

    source = "Assets/Large.hlsl"
    binary = "Assets/Large.custom"
    write(tmp_path, source, " " * 70000 + "float before;", "1" * 32)
    write(tmp_path, binary, b"\0" * 70000 + b"before", "2" * 32)
    before = {item.path: item.content_hash for item in walk_repository(tmp_path).files}
    write(tmp_path, source, " " * 70000 + "float after_;")
    write(tmp_path, binary, b"\0" * 70000 + b"after_")
    stat = (tmp_path / binary).stat()
    os.utime(tmp_path / binary, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1000000))
    after = {item.path: item.content_hash for item in walk_repository(tmp_path).files}
    assert before[source] != after[source]
    assert before[binary] != after[binary]


def test_material_properties_and_unknown_yaml_assets(tmp_path: Path) -> None:
    write(
        tmp_path,
        "Assets/Surface.mat",
        """%YAML 1.1
--- !u!21 &2100000
Material:
  m_Name: Surface
  m_CustomRenderQueue: 2450
  m_EnableInstancingVariants: 1
  m_SavedProperties:
    m_Floats:
    - _Smoothness: 0.75
    m_Colors:
    - _Tint: {r: 1, g: 0, b: 0, a: 1}
""",
    )
    write(
        tmp_path,
        "Assets/Effect.vfx",
        """%YAML 1.1
--- !u!114 &1
MonoBehaviour:
  m_Name: Effect
""",
    )
    result = analyze(tmp_path)
    material = result.assets["Assets/Surface.mat"]["material"]
    assert material["render_queue"] == 2450
    assert material["enable_instancing"] is True
    assert material["floats"]["_Smoothness"] == 0.75
    assert "_Tint" in material["colors"]
    assert result.assets["Assets/Effect.vfx"]["status"] == "parsed"
    assert not result.errors


def test_custom_asset_navigation_survives_map_generation(tmp_path: Path) -> None:
    from better_context.agents_map import generate_agents_map
    from better_context.graph import build_graph_from_edges
    from better_context.manifest import FileEntry, GraphData, Manifest, create_manifest_meta

    path = "Assets/Custom/blob.custom"
    write(tmp_path, path, b"\0binary", "1" * 32)
    detail = analyze(tmp_path).assets[path]
    manifest = Manifest(
        meta=create_manifest_meta(tmp_path, "test"),
        files=[
            FileEntry(
                path=path,
                language="",
                size_bytes=7,
                hash="test",
                metadata={"unity_runtime": detail, "ownership": "project-owned"},
            )
        ],
        graph=GraphData(nodes=[path]),
        project={"kind": "unity", "unity_version": "6000.6.4f1"},
    )
    (tmp_path / "ProjectSettings").mkdir()
    (tmp_path / "ProjectSettings/ProjectVersion.txt").write_text("m_EditorVersion: 6000.6.4f1")
    generate_agents_map(manifest, build_graph_from_edges([], [path]), tmp_path)
    assert "blob.custom" in (tmp_path / "Assets/Custom/AGENTS.md").read_text(encoding="utf-8")


def test_snapshot_invalidates_on_embedded_package_asset(tmp_path: Path) -> None:
    before = compute_editor_source_hash(tmp_path)
    write(tmp_path, "Packages/com.game.custom/Resources/data.custom", "first")
    assert compute_editor_source_hash(tmp_path) != before


def test_generated_maps_do_not_become_runtime_assets(tmp_path: Path) -> None:
    write(tmp_path, "Assets/AGENTS.md", "generated map", "1" * 32)
    write(tmp_path, "Assets/CLAUDE.md", "generated map", "2" * 32)
    assert not analyze(tmp_path).assets
