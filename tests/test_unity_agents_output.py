"""Focused output coverage for Unity runtime intelligence maps."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from better_context.agents_map import (
    BEGIN,
    _architecture_summary,
    _cycle_summary,
    _local_violations,
    generate_agents_map,
)
from better_context.graph import build_graph_from_edges
from better_context.manifest import FileEntry, GraphData, Manifest, ManifestMeta


def _runtime_entry(
    root: Path,
    path: str,
    detail: dict[str, Any],
    ownership: str = "project-owned",
) -> FileEntry:
    target = root / Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("%YAML 1.1\n", encoding="utf-8")
    detail = {"path": path, "status": "parsed", "ownership": ownership, **detail}
    return FileEntry(
        path=path,
        language="",
        size_bytes=10,
        hash=path,
        metadata={"ownership": ownership, "unity_runtime": detail},
    )


def _script(name: str, path: str) -> dict[str, object]:
    return {
        "guid": "a" * 32,
        "path": path,
        "type": name.rsplit(".", 1)[-1],
        "qualified_name": name,
        "unity_type": "MonoBehaviour",
        "confidence": "exact",
    }


def test_editor_asset_metrics_and_low_signal_art_collapse(tmp_path: Path) -> None:
    target = _runtime_entry(
        tmp_path,
        "Assets/Art/target.png",
        {
            "kind": "texture",
            "high_signal": 2,
            "responsibility": "Texture `target.png` (512×512) importing 1 Sprite subasset(s).",
            "editor_asset": {
                "facts": {
                    "source_width": "512",
                    "source_height": "512",
                    "width": "512",
                    "height": "512",
                    "sprite_mode": "Single",
                    "pixels_per_unit": "100",
                    "mipmaps": "false",
                    "platform.Android.overridden": "true",
                    "platform.Android.max_texture_size": "1024",
                },
                "subassets": [{"name": "target", "local_id": 21300000}],
            },
        },
    )
    pure = _runtime_entry(
        tmp_path,
        "Assets/Art/Background.png",
        {
            "kind": "texture",
            "high_signal": 0,
            "responsibility": "Texture `Background.png` imported at 2048×1024.",
            "editor_asset": {
                "facts": {"source_width": "2048", "source_height": "1024"},
                "subassets": [],
            },
        },
    )
    meta_entries = [
        FileEntry(
            path=f"{entry.path}.meta",
            language="",
            size_bytes=1,
            hash=f"{entry.hash}.meta",
        )
        for entry in (target, pure)
    ]
    manifest = Manifest(
        meta=ManifestMeta("1.3.0", "now", "better-context-unity/1.6.0", str(tmp_path), "x"),
        files=[target, pure, *meta_entries],
        graph=GraphData(nodes=[target.path, pure.path]),
        project={
            "unity_runtime": {
                "scope": "project-owned",
                "metrics": {
                    "assets": 2,
                    "textures": 2,
                    "sprites": 1,
                    "resolved_components": 0,
                },
                "coverage": {"candidates": 2, "parsed": 2},
                "editor_snapshot": {
                    "status": "fresh",
                    "mode": "batch",
                    "coverage": {"assets_exported": 2},
                },
            }
        },
    )
    graph = build_graph_from_edges([], [target.path, pure.path])

    generate_agents_map(manifest, graph, tmp_path)

    root_map = (tmp_path / "AGENTS.md").read_text()
    art_map = (tmp_path / "Assets" / "Art" / "AGENTS.md").read_text()
    assert "2 textures" in root_map
    assert "1 Sprite subassets" in root_map
    assert "Unity Editor snapshot: fresh via `batch`" in root_map
    assert "Android override: `max 1024`" in art_map
    assert "2 `.meta` sidecar file(s) hidden" in art_map
    assert "Background.png" in art_map
    assert "Texture `Background.png` imported at 2048×1024" not in art_map


def _manifest(root: Path) -> tuple[Manifest, object]:
    gun_button = _script("Game.UI.GunButtonView", "Assets/Scripts/UI/GunButtonView.cs")
    player = _script("Game.PlayerController", "Assets/Scripts/PlayerController.cs")
    entries = [
        _runtime_entry(
            root,
            "Assets/Scenes/Main Scene.unity",
            {
                "kind": "scene",
                "high_signal": 120,
                "object_count": 2,
                "component_count": 3,
                "script_component_count": 1,
                "objects": [
                    {
                        "file_id": "1",
                        "name": "Game Root",
                        "path": "Game Root",
                        "active": True,
                        "parent_file_id": None,
                        "components": [{"file_id": "2", "type": "Transform"}],
                    },
                    {
                        "file_id": "3",
                        "name": "Player",
                        "path": "Game Root/Player",
                        "active": True,
                        "parent_file_id": "1",
                        "components": [{"file_id": "4", "type": "MonoBehaviour", "script": player}],
                    },
                ],
                "root_objects": ["1"],
                "unity_events": [],
                "references": [],
            },
        ),
        _runtime_entry(
            root,
            "Assets/Prefabs/Shop Button.prefab",
            {
                "kind": "prefab",
                "high_signal": 110,
                "object_count": 2,
                "component_count": 4,
                "script_component_count": 1,
                "objects": [
                    {
                        "file_id": "10",
                        "name": "Shop Button",
                        "path": "Shop Button",
                        "active": True,
                        "parent_file_id": None,
                        "components": [
                            {"file_id": "11", "type": "RectTransform"},
                            {"file_id": "12", "type": "MonoBehaviour", "script": gun_button},
                        ],
                    },
                    {
                        "file_id": "13",
                        "name": "Label",
                        "path": "Shop Button/Label",
                        "active": True,
                        "parent_file_id": "10",
                        "components": [{"file_id": "14", "type": "TextMeshProUGUI"}],
                    },
                ],
                "roots": ["10"],
                "event_bindings": [
                    {
                        "owner_file_id": "10",
                        "owner_path": "Shop Button",
                        "component_file_id": "12",
                        "target_file_id": "12",
                        "target_path": "Shop Button",
                        "target_script": "Assets/Scripts/UI/GunButtonView.cs",
                        "target_type": "Game.UI.GunButtonView",
                        "method": "SwitchGun",
                        "mode": 1,
                        "confidence": "exact",
                    }
                ],
                "references": [],
            },
        ),
        _runtime_entry(
            root,
            "Assets/Prefabs/Player.prefab",
            {
                "kind": "prefab",
                "high_signal": 90,
                "object_count": 1,
                "component_count": 1,
                "script_component_count": 1,
                "objects": [
                    {
                        "file_id": "20",
                        "name": "Player",
                        "path": "Player",
                        "parent_file_id": None,
                        "components": [
                            {"file_id": "21", "type": "MonoBehaviour", "script": player}
                        ],
                    }
                ],
                "roots": ["20"],
                "unity_events": [],
                "references": [],
            },
        ),
        _runtime_entry(
            root,
            "Assets/Prefabs/Low Signal.prefab",
            {
                "kind": "prefab",
                "high_signal": 10,
                "object_count": 1,
                "component_count": 0,
                "script_component_count": 0,
                "objects": [{"file_id": "30", "name": "Marker", "path": "Marker"}],
                "unity_events": [],
                "references": [],
            },
        ),
        _runtime_entry(
            root,
            "Assets/Data/GameConfig.asset",
            {
                "kind": "script",
                "high_signal": 100,
                "object_count": 0,
                "component_count": 1,
                "script_component_count": 1,
                "script": {
                    **_script("Game.Config.GameConfigSO", "Assets/Scripts/GameConfigSO.cs"),
                    "unity_type": "ScriptableObject",
                },
                "objects": [],
                "unity_events": [],
                "references": [],
            },
        ),
        _runtime_entry(
            root,
            "Assets/Animations/NormalZombieController.controller",
            {
                "kind": "animator_controller",
                "high_signal": 100,
                "object_count": 0,
                "component_count": 0,
                "script_component_count": 0,
                "objects": [],
                "unity_events": [],
                "references": [],
                "animator": {
                    "parameters": [{"name": "Speed", "type": "Float", "default": 0}],
                    "layers": [{"name": "Base Layer", "default_state_file_id": "101"}],
                    "states": [
                        {"file_id": "101", "name": "Idle"},
                        {"file_id": "102", "name": "Attack"},
                    ],
                    "transitions": [
                        {
                            "file_id": "103",
                            "source_state_file_id": "101",
                            "destination_state_file_id": "102",
                            "conditions": [{"parameter": "Speed", "mode": 3, "threshold": 0.1}],
                        }
                    ],
                    "blend_trees": [],
                },
            },
        ),
        _runtime_entry(
            root,
            "Assets/Art/Decoration.prefab",
            {
                "kind": "prefab",
                "high_signal": 0,
                "object_count": 1,
                "component_count": 1,
                "script_component_count": 0,
                "objects": [
                    {
                        "file_id": "40",
                        "name": "Decoration",
                        "path": "Decoration",
                        "components": [{"file_id": "41", "type": "MeshRenderer"}],
                    }
                ],
                "unity_events": [],
                "references": [
                    {
                        "field": "m_Material",
                        "target": "Assets/Art/Decoration.mat",
                        "confidence": "exact",
                    }
                ],
            },
        ),
        _runtime_entry(
            root,
            "Assets/Plugins/Vendor/Vendor.prefab",
            {
                "kind": "prefab",
                "high_signal": 999,
                "object_count": 1,
                "component_count": 1,
                "script_component_count": 1,
                "objects": [
                    {
                        "file_id": "50",
                        "name": "Vendor",
                        "path": "Vendor",
                        "components": [
                            {"file_id": "51", "type": "MonoBehaviour", "script": player}
                        ],
                    }
                ],
                "unity_events": [],
                "references": [],
            },
            ownership="vendor",
        ),
    ]

    for index in range(1, 7):
        entries.append(
            _runtime_entry(
                root,
                f"Assets/Runtime/Marker {index}.prefab",
                {
                    "kind": "prefab",
                    "high_signal": 30 - index,
                    "object_count": 1,
                    "component_count": 0,
                    "script_component_count": 0,
                    "objects": [
                        {
                            "file_id": str(1000 + index),
                            "name": f"Marker {index}",
                            "path": f"Marker {index}",
                        }
                    ],
                    "unity_events": [],
                    "references": [],
                },
            )
        )

    project = {
        "kind": "unity",
        "unity_version": "2022.3.62f2",
        "analysis_engine": "roslyn",
        "scenes": [
            {
                "path": "Assets/Scenes/Main Scene.unity",
                "ownership": "project-owned",
                "enabled": True,
            }
        ],
        "metrics": {},
        "unity_runtime": {
            "engine": "unity_yaml",
            "scope": "project-owned",
            "coverage": {"candidates": 14, "parsed": 13, "unsupported": 1, "errors": 0},
            "metrics": {
                "scenes": 1,
                "prefabs": 11,
                "scriptable_objects": 1,
                "animator_controllers": 1,
                "game_objects": 14,
                "components": 11,
                "script_components": 4,
                "unity_events": 1,
                "animator_states": 2,
            },
            "agents_limits": {"assets": 2, "objects": 8},
            "errors": [],
        },
    }
    manifest = Manifest(
        meta=ManifestMeta("1.2.0", "now", "test", root.as_posix(), "hash"),
        files=entries,
        graph=GraphData(nodes=[entry.path for entry in entries]),
        project=project,
    )
    graph = build_graph_from_edges([], nodes=[entry.path for entry in entries])
    return manifest, graph


def test_runtime_assets_render_semantic_maps_with_bounded_previews(tmp_path: Path) -> None:
    root = tmp_path / "UnityGame"
    (root / "Assets").mkdir(parents=True)
    (root / "ProjectSettings").mkdir()
    (root / "ProjectSettings" / "ProjectVersion.txt").write_text(
        "m_EditorVersion: 2022.3.62f2\n", encoding="utf-8"
    )
    (root / "AGENTS.md").write_text("# Handwritten\n\nKeep this.\n", encoding="utf-8")
    manifest, graph = _manifest(root)

    first = generate_agents_map(manifest, graph, root)
    assert not first.errors
    second = generate_agents_map(manifest, graph, root)
    assert not second.files_written

    root_map = (root / "AGENTS.md").read_text(encoding="utf-8")
    prefab_map = (root / "Assets" / "Prefabs" / "AGENTS.md").read_text(encoding="utf-8")
    data_map = (root / "Assets" / "Data" / "AGENTS.md").read_text(encoding="utf-8")
    animator_map = (root / "Assets" / "Animations" / "AGENTS.md").read_text(encoding="utf-8")

    assert "Keep this." in root_map and root_map.count(BEGIN) == 1
    assert "### Unity runtime intelligence" in root_map
    assert "1 scenes, 11 prefabs, 1 ScriptableObjects, 1 Animator controllers" in root_map
    assert "Parse coverage: 13/14 candidate assets parsed" in root_map
    assert "#### Key Unity runtime assets" in root_map
    assert "Assets/Prefabs/Shop%20Button.prefab" in root_map
    assert "additional semantic runtime assets" in root_map
    assert "better-context-unity unity bindings" in root_map

    assert "Unity runtime asset module" in prefab_map
    assert "### Unity runtime assets" in prefab_map
    assert "Shop%20Button.prefab" in prefab_map
    assert "Game.UI.GunButtonView.SwitchGun()" in prefab_map
    assert "objects: `Shop Button`, `Shop Button/Label`" in prefab_map
    assert "components: `RectTransform`, `MonoBehaviour`" in prefab_map
    assert "Player.prefab" in prefab_map
    assert "Low Signal.prefab" not in prefab_map
    assert "1 lower-signal runtime assets omitted" in prefab_map

    assert "Serialized `Game.Config.GameConfigSO` data instance `GameConfig`" in data_map
    assert (
        "Animator controller `NormalZombieController` defining 1 layer(s), 2 state(s)"
        in animator_map
    )
    assert "states: `Idle`, `Attack`" in animator_map
    assert "parameters: `Speed`" in animator_map

    art_map = (root / "Assets" / "Art" / "AGENTS.md").read_text(encoding="utf-8")
    vendor_map = (root / "Assets" / "Plugins" / "AGENTS.md").read_text(encoding="utf-8")
    assert "[`Decoration.prefab`](Decoration.prefab)" in art_map
    assert "[`Vendor/Vendor.prefab`](Vendor/Vendor.prefab)" in vendor_map


def test_runtime_asset_links_and_root_cap_are_deterministic(tmp_path: Path) -> None:
    root = tmp_path / "UnityGame"
    (root / "Assets").mkdir(parents=True)
    (root / "ProjectSettings").mkdir()
    (root / "ProjectSettings" / "ProjectVersion.txt").write_text(
        "m_EditorVersion: 2022.3.62f2\n", encoding="utf-8"
    )
    manifest, graph = _manifest(root)

    generated = generate_agents_map(manifest, graph, root)
    assert not generated.errors
    root_map = (root / "AGENTS.md").read_text(encoding="utf-8")

    key_section = root_map.split("#### Key Unity runtime assets", 1)[1].split(
        "- Browse assets:", 1
    )[0]
    assert key_section.count("| [`Assets/") == 8
    assert "[--kind KIND] [--limit 50] [--format json|human|markdown]" in root_map
    assert "unity show <project-relative-asset> [--depth 2|-1]" in root_map


def test_root_accepts_compact_runtime_asset_records(tmp_path: Path) -> None:
    root = tmp_path / "UnityGame"
    asset_path = "Assets/UI/Compact Button.prefab"
    target = root / Path(asset_path)
    target.parent.mkdir(parents=True)
    target.write_text("%YAML 1.1\n", encoding="utf-8")
    (root / "ProjectSettings").mkdir()
    (root / "ProjectSettings" / "ProjectVersion.txt").write_text(
        "m_EditorVersion: 2022.3.62f2\n", encoding="utf-8"
    )
    compact = {
        "path": asset_path,
        "kind": "prefab",
        "status": "parsed",
        "ownership": "project-owned",
        "high_signal": 10,
        "object_count": 1,
        "component_count": 1,
        "script_component_count": 0,
        "root_objects": [{"file_id": "1", "name": "Compact Button", "path": "Compact Button"}],
        "objects": [{"file_id": "1", "name": "Compact Button", "path": "Compact Button"}],
        "event_bindings": [
            {
                "owner_path": "Compact Button",
                "target_type": "Game.UI.CompactButton",
                "method": "Submit",
            }
        ],
    }
    entry = FileEntry(
        path=asset_path,
        language="",
        size_bytes=10,
        hash="compact",
        metadata={"ownership": "project-owned"},
    )
    manifest = Manifest(
        meta=ManifestMeta("1.2.0", "now", "test", root.as_posix(), "hash"),
        files=[entry],
        graph=GraphData(nodes=[asset_path]),
        project={
            "kind": "unity",
            "unity_runtime": {
                "scope": "project-owned",
                "coverage": {"candidates": 1, "parsed": 1},
                "metrics": {"prefabs": 1, "event_bindings": 1},
                "assets": [compact],
            },
        },
    )
    graph = build_graph_from_edges([], nodes=[asset_path])

    generated = generate_agents_map(manifest, graph, root)
    assert not generated.errors
    root_map = (root / "AGENTS.md").read_text(encoding="utf-8")
    assert "Assets/UI/Compact%20Button.prefab" in root_map
    assert "Compact Button → Game.UI.CompactButton.Submit()" in root_map
    assert "1 UnityEvent bindings" in root_map


def test_art_assets_get_bounded_path_maps_without_invented_responsibility(
    tmp_path: Path,
) -> None:
    root = tmp_path / "UnityGame"
    (root / "Assets").mkdir(parents=True)
    (root / "ProjectSettings").mkdir()
    (root / "ProjectSettings" / "ProjectVersion.txt").write_text(
        "m_EditorVersion: 2022.3.62f2\n", encoding="utf-8"
    )
    paths = [
        "Assets/Drone/DroneV21/Drone.fbx.meta",
        "Assets/Drone/DroneV21/Drone_D.png.meta",
        "Assets/Drone/DroneV20/Run.anim",
        "Assets/Imported/Pack/Models/Materials/Stone.mat",
        "Assets/GoogleMobileAds/Resources/GoogleMobileAdsSettings.asset",
    ]
    entries = []
    for path in paths:
        target = root / Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("fixture\n", encoding="utf-8")
        if path.endswith(".meta"):
            target.with_suffix("").write_bytes(b"fixture")
        ownership = "vendor" if path.startswith("Assets/GoogleMobileAds/") else "project-owned"
        metadata: dict[str, Any] = {"ownership": ownership}
        if path.endswith("Run.anim"):
            metadata["unity_runtime"] = {
                "path": path,
                "kind": "animation_clip",
                "status": "parsed",
                "ownership": ownership,
                "high_signal": 1,
                "responsibility": "Animation clip `Run` sampled at 60 fps with 1 curve(s).",
                "animation_clip": {"name": "Run", "sample_rate": 60, "curve_count": 1},
            }
        if path.endswith("Stone.mat"):
            metadata["unity_runtime"] = {
                "path": path,
                "kind": "material",
                "status": "parsed",
                "ownership": ownership,
                "high_signal": 1,
                "responsibility": "Material `Stone` using a built-in shader.",
                "material": {"name": "Stone", "texture_reference_count": 0},
            }
        entries.append(
            FileEntry(
                path=path,
                language="",
                size_bytes=8,
                hash=path,
                metadata=metadata,
            )
        )
    orphan = root / "Assets" / "Orphan" / "Ghost.png.meta"
    orphan.parent.mkdir(parents=True, exist_ok=True)
    orphan.write_text("fixture\n", encoding="utf-8")
    entries.append(
        FileEntry(
            path="Assets/Orphan/Ghost.png.meta",
            language="",
            size_bytes=8,
            hash="orphan",
            metadata={"ownership": "project-owned"},
        )
    )
    manifest = Manifest(
        meta=ManifestMeta("1.2.0", "now", "test", root.as_posix(), "hash"),
        files=entries,
        graph=GraphData(nodes=[entry.path for entry in entries]),
        project={"kind": "unity", "unity_runtime": {"scope": "project-owned"}},
    )
    graph = build_graph_from_edges([], nodes=[entry.path for entry in entries])

    generated = generate_agents_map(manifest, graph, root)
    assert not generated.errors

    drone_map = (root / "Assets" / "Drone" / "AGENTS.md").read_text(encoding="utf-8")
    model_map = (root / "Assets" / "Drone" / "DroneV21" / "AGENTS.md").read_text(encoding="utf-8")
    animation_map = (root / "Assets" / "Drone" / "DroneV20" / "AGENTS.md").read_text(
        encoding="utf-8"
    )
    vendor_map = (root / "Assets" / "GoogleMobileAds" / "AGENTS.md").read_text(encoding="utf-8")
    imported_map = (root / "Assets" / "Imported" / "Pack" / "AGENTS.md").read_text(encoding="utf-8")

    assert "[`DroneV21/`](DroneV21/AGENTS.md)" in drone_map
    assert "### Unity asset paths" in model_map
    assert "[`Drone.fbx`](Drone.fbx)" in model_map
    assert "[`Drone_D.png`](Drone_D.png)" in model_map
    assert "Verified responsibility" not in model_map
    assert "### Unity runtime assets" in animation_map
    assert "Animation clip `Run` sampled at 60 fps" in animation_map
    assert (
        "[`Resources/GoogleMobileAdsSettings.asset`](Resources/GoogleMobileAdsSettings.asset)"
    ) in vendor_map
    assert "[`Models/Materials/Stone.mat`](Models/Materials/Stone.mat)" in imported_map
    assert not (root / "Assets" / "Imported" / "Pack" / "Models" / "AGENTS.md").exists()
    assert not (root / "Assets" / "GoogleMobileAds" / "Resources" / "AGENTS.md").exists()
    assert not (root / "Assets" / "Orphan" / "AGENTS.md").exists()


def test_parsed_fbx_gets_bounded_model_intelligence(tmp_path: Path) -> None:
    root = tmp_path / "UnityGame"
    model_path = "Assets/Characters/Hero/Model/Hero.fbx"
    target = root / Path(model_path)
    target.parent.mkdir(parents=True)
    target.write_bytes(b"binary fixture")
    (root / "ProjectSettings").mkdir()
    (root / "ProjectSettings" / "ProjectVersion.txt").write_text(
        "m_EditorVersion: 2022.3.62f2\n", encoding="utf-8"
    )
    detail = {
        "path": model_path,
        "kind": "model",
        "status": "parsed",
        "ownership": "project-owned",
        "confidence": "exact",
        "high_signal": 1,
        "responsibility": (
            "FBX model `Hero` with 8 node(s), 1 mesh(es), 5 bone(s), "
            "and 1 Unity clip split(s); rig `humanoid`."
        ),
        "model": {
            "format": "binary",
            "fbx_version": 7400,
            "node_count": 8,
            "mesh_count": 1,
            "skeleton": {"bone_count": 5},
            "animation_stacks": [{"name": "Take 001"}],
        },
        "model_importer": {
            "rig": {"animation_type": "humanoid"},
            "clips": [{"name": "Take 001", "first_frame": 0, "last_frame": 60}],
        },
    }
    entry = FileEntry(
        path=model_path,
        language="",
        size_bytes=target.stat().st_size,
        hash="model",
        metadata={"ownership": "project-owned", "unity_runtime": detail},
    )
    manifest = Manifest(
        meta=ManifestMeta("1.2.0", "now", "test", root.as_posix(), "hash"),
        files=[entry],
        graph=GraphData(nodes=[model_path]),
        project={
            "kind": "unity",
            "unity_runtime": {
                "scope": "project-owned",
                "coverage": {"candidates": 1, "parsed": 1},
                "metrics": {"assets": 1, "models": 1},
            },
        },
    )

    generated = generate_agents_map(manifest, build_graph_from_edges([], nodes=[model_path]), root)

    assert not generated.errors
    model_map = (root / "Assets" / "Characters" / "Hero" / "AGENTS.md").read_text(encoding="utf-8")
    root_map = (root / "AGENTS.md").read_text(encoding="utf-8")
    assert "### Unity runtime assets" in model_map
    assert "FBX Model" in model_map
    assert "8 node(s), 1 mesh(es), 5 bone(s)" in model_map
    assert "takes: `Take 001`" in model_map
    assert "rig: `humanoid`" in model_map
    assert "1 FBX models" in root_map
    assert not (root / "Assets" / "Characters" / "Hero" / "Model" / "AGENTS.md").exists()


def test_architecture_and_cycle_rendering_is_order_independent() -> None:
    violations = [
        {
            "source_path": "Assets/Z/B.cs",
            "source_layer": "application",
            "target_path": "Assets/Z/D.cs",
            "target_layer": "presentation",
            "message": "B to D",
        },
        {
            "source_path": "Assets/Z/A.cs",
            "source_layer": "application",
            "target_path": "Assets/Z/C.cs",
            "target_layer": "presentation",
            "message": "A to C",
        },
    ]

    def make_manifest(reverse: bool) -> Manifest:
        ordered = list(reversed(violations)) if reverse else list(violations)
        cycles = [["z.cs", "a.cs"], ["d.cs", "c.cs"]]
        if reverse:
            cycles = [list(reversed(cycle)) for cycle in reversed(cycles)]
        return Manifest(
            meta=ManifestMeta("1.2.0", "now", "test", ".", "hash"),
            files=[],
            graph=GraphData(
                cycles=cycles,
                architecture={
                    "layers": {"presentation": ["c"], "application": ["a"]},
                    "violations": ordered,
                },
            ),
            project={"project_cycles": cycles},
        )

    first = make_manifest(False)
    second = make_manifest(True)
    assert _architecture_summary(first) == _architecture_summary(second)
    assert _cycle_summary(first) == _cycle_summary(second)
    assert _local_violations("Assets/Z", first) == _local_violations("Assets/Z", second)
