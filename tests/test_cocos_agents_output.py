"""Rendered map output for a Cocos Creator project."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from better_context.agents_map import generate_agents_map, resolve_profile
from better_context.graph import build_graph_from_edges
from better_context.manifest import FileEntry, GraphData, Manifest, ManifestMeta
from better_context.project_profile import COCOS_PROFILE, UNITY_PROFILE


def _cocos_root(root: Path) -> None:
    (root / "assets" / "scene").mkdir(parents=True)
    (root / "assets" / "scripts").mkdir(parents=True)
    (root / "package.json").write_text(
        json.dumps({"name": "demo", "creator": {"version": "3.8.8"}}), encoding="utf-8"
    )
    (root / "assets" / "scripts" / "Player.ts").write_text(
        "@ccclass('Player')\nexport class Player extends Component { onLoad() {} attack() {} }\n",
        encoding="utf-8",
    )
    (root / "assets" / "scripts" / "Player.ts.meta").write_text("{}", encoding="utf-8")
    (root / "assets" / "scene" / "main.scene").write_text("[]", encoding="utf-8")
    (root / "assets" / "scene" / "main.scene.meta").write_text("{}", encoding="utf-8")


def _entry(path: str, language: str = "", **metadata: Any) -> FileEntry:
    return FileEntry(
        path=path,
        language=language,
        size_bytes=10,
        hash=path,
        metadata={"ownership": "project-owned", **metadata},
    )


def _manifest(root: Path) -> tuple[Manifest, Any]:
    scene_runtime = {
        "path": "assets/scene/main.scene",
        "kind": "scene",
        "status": "parsed",
        "ownership": "project-owned",
        "high_signal": 2,
        "responsibility": "Cocos scene `main` containing 2 node(s); wires `Player`.",
        "objects": [
            {
                "file_id": 1,
                "name": "Canvas",
                "path": "Canvas",
                "parent_file_id": None,
                "active": True,
                "components": [
                    {"type": "cc.Canvas", "source": "engine"},
                    {
                        "type": "Player",
                        "source": "class-id",
                        "script": {"type": "Player", "path": "assets/scripts/Player.ts"},
                    },
                ],
            }
        ],
        "root_objects": [1],
        "references": [{"target": "assets/scripts/Player.ts", "kind": "asset_uuid"}],
    }
    entries = [
        _entry("assets/scripts/Player.ts", "typescript"),
        _entry("assets/scripts/Player.ts.meta"),
        _entry("assets/scene/main.scene", engine_runtime=scene_runtime),
        _entry("assets/scene/main.scene.meta"),
    ]
    manifest = Manifest(
        meta=ManifestMeta("1.3.0", "now", "test", root.as_posix(), "hash"),
        files=entries,
        graph=GraphData(nodes=[entry.path for entry in entries]),
        project={
            "kind": "cocos",
            "creator_version": "3.8.8",
            "analysis_engine": "language-adapters",
            "bundles": [
                {"folder": "assets/resources", "bundle_name": "resources", "priority": 8}
            ],
            "start_scene": "626242e7-577e-505b-964c-570f4b31b5ac",
            "extensions": ["extensions/dev-tools"],
            "engine_runtime": {
                "kind": "cocos",
                "scope": "project-owned",
                "metrics": {
                    "scenes": 1,
                    "prefabs": 0,
                    "animation_clips": 0,
                    "resolved_scripts": 1,
                    "unresolved_components": 0,
                },
                "coverage": {"candidates": 1, "parsed": 1},
                "index": {
                    "assets_with_uuid": 2,
                    "script_class_ids": 1,
                    "ccclass_names": 1,
                },
            },
        },
    )
    return manifest, build_graph_from_edges([], nodes=[entry.path for entry in entries])


def test_profile_resolution_prefers_the_recorded_kind(tmp_path: Path) -> None:
    _cocos_root(tmp_path)
    manifest, _graph = _manifest(tmp_path)

    assert resolve_profile(tmp_path, manifest) is COCOS_PROFILE
    assert resolve_profile(tmp_path) is COCOS_PROFILE
    assert resolve_profile(tmp_path, None) is COCOS_PROFILE
    assert COCOS_PROFILE is not UNITY_PROFILE


def test_root_map_reports_verified_cocos_facts(tmp_path: Path) -> None:
    _cocos_root(tmp_path)
    manifest, graph = _manifest(tmp_path)

    generate_agents_map(manifest, graph, tmp_path)
    root_map = (tmp_path / "AGENTS.md").read_text(encoding="utf-8")

    assert "## Cocos Creator project map" in root_map
    assert "Cocos Creator `3.8.8`" in root_map
    assert "`resources` (assets/resources)" in root_map
    assert "Start scene uuid: `626242e7-577e-505b-964c-570f4b31b5ac`" in root_map
    assert "### Cocos Creator runtime intelligence" in root_map
    assert "1 script class-id(s)" in root_map
    assert "Exact Cocos Creator serialized uuid edges" in root_map
    assert "better-context-unity cocos list" in root_map


def test_root_map_carries_no_unity_prose(tmp_path: Path) -> None:
    _cocos_root(tmp_path)
    manifest, graph = _manifest(tmp_path)

    generate_agents_map(manifest, graph, tmp_path)
    root_map = (tmp_path / "AGENTS.md").read_text(encoding="utf-8")

    for leaked in (
        "Unity",
        "C# ",
        "EditMode/PlayMode",
        "Packages/manifest.json",
        ".csproj",
    ):
        assert leaked not in root_map.replace("better-context-unity", ""), leaked


def test_cocos_testing_rules_and_ownership_notes(tmp_path: Path) -> None:
    _cocos_root(tmp_path)
    manifest, graph = _manifest(tmp_path)

    generate_agents_map(manifest, graph, tmp_path)
    root_map = (tmp_path / "AGENTS.md").read_text(encoding="utf-8")

    assert "npx tsc --noEmit" in root_map
    assert "the real gate is a completed build" in root_map
    assert "sibling `.meta` holding its uuid" in root_map


def test_folder_map_renders_scene_hierarchy_and_meta_collapse(tmp_path: Path) -> None:
    _cocos_root(tmp_path)
    manifest, graph = _manifest(tmp_path)

    generate_agents_map(manifest, graph, tmp_path)
    scene_map = (tmp_path / "assets" / "scene" / "AGENTS.md").read_text(encoding="utf-8")

    assert "### Cocos Creator runtime assets" in scene_map
    assert "Cocos scene `main`" in scene_map
    assert "`Player`" in scene_map
    assert "Never treated as TypeScript dependencies." in scene_map


def test_maps_stay_inside_cocos_roots(tmp_path: Path) -> None:
    _cocos_root(tmp_path)
    (tmp_path / "library" / "imports").mkdir(parents=True)
    manifest, graph = _manifest(tmp_path)
    manifest.files.append(_entry("library/imports/cache.json", "json", ownership="generated"))

    generate_agents_map(manifest, graph, tmp_path)

    written = sorted(
        path.relative_to(tmp_path).as_posix() for path in tmp_path.rglob("AGENTS.md")
    )
    assert written == [
        "AGENTS.md",
        "assets/AGENTS.md",
        "assets/scene/AGENTS.md",
        "assets/scripts/AGENTS.md",
    ]
