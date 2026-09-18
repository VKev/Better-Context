"""Cocos Creator serialized-asset intelligence."""

from __future__ import annotations

import json
from pathlib import Path

from better_context.cocos_runtime import (
    CocosAssetIndex,
    analyze_cocos_asset,
    analyze_cocos_runtime,
    collect_cocos_project_facts,
    collect_cocos_reference_edges,
    compress_uuid,
)

SCRIPT_UUID = "456dd845-c248-43e4-8d17-d2d92a0b554b"
SCRIPT_CLASS_ID = "456ddhFwkhD5I0X0tkqC1VL"
TEXTURE_UUID = "b730527c-3233-41c2-aaf7-7cdab58f9749"


def _write(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(payload, str):
        path.write_text(payload, encoding="utf-8")
    else:
        path.write_text(json.dumps(payload), encoding="utf-8")


def _meta(path: Path, uuid: str, user_data: dict | None = None) -> None:
    _write(
        path,
        {
            "ver": "1.1.50",
            "importer": "typescript",
            "imported": True,
            "uuid": uuid,
            "files": [],
            "subMetas": {},
            "userData": user_data or {},
        },
    )


def _scene_records() -> list[dict]:
    return [
        {"__type__": "cc.SceneAsset", "_name": "main", "scene": {"__id__": 1}},
        {
            "__type__": "cc.Node",
            "_name": "Canvas",
            "_parent": None,
            "_children": [{"__id__": 2}],
            "_components": [{"__id__": 3}, {"__id__": 4}],
            "_active": True,
        },
        {
            "__type__": "cc.Node",
            "_name": "Icon",
            "_parent": {"__id__": 1},
            "_children": [],
            "_components": [{"__id__": 5}],
            "_active": True,
        },
        {"__type__": "cc.Canvas", "node": {"__id__": 1}},
        {"__type__": SCRIPT_CLASS_ID, "node": {"__id__": 1}},
        {
            "__type__": "cc.Sprite",
            "node": {"__id__": 2},
            "_spriteFrame": {"__uuid__": f"{TEXTURE_UUID}@f9941"},
        },
    ]


def _cocos_project(root: Path) -> Path:
    _write(root / "package.json", {"name": "demo", "creator": {"version": "3.8.8"}})
    _write(
        root / "settings" / "v2" / "packages" / "project.json",
        {"general": {"startScene": "626242e7-577e-505b-964c-570f4b31b5ac"}},
    )
    _write(root / "assets" / "scripts" / "VideoIcon.ts", "@ccclass('VideoIcon')\nclass X {}\n")
    _meta(root / "assets" / "scripts" / "VideoIcon.ts.meta", SCRIPT_UUID)
    _write(root / "assets" / "res" / "icon.png", "binary-ish")
    _meta(root / "assets" / "res" / "icon.png.meta", TEXTURE_UUID)
    _write(root / "assets" / "scene" / "main.scene", _scene_records())
    _meta(root / "assets" / "scene" / "main.scene.meta", "0f0f0f0f-1111-2222-3333-444444444444")
    _meta(
        root / "assets" / "resources.meta",
        "67dd238f-11c5-467b-a294-999f9164a7c7",
        {"isBundle": True, "bundleName": "resources", "priority": 8},
    )
    (root / "assets" / "resources").mkdir(parents=True, exist_ok=True)
    (root / "extensions" / "dev-tools").mkdir(parents=True, exist_ok=True)
    return root


def _paths(root: Path) -> list[str]:
    return [
        item.relative_to(root).as_posix()
        for item in root.rglob("*")
        if item.is_file()
    ]


def test_compress_uuid_matches_the_editor_class_id() -> None:
    # Verified against a real Cocos Creator 3.8.8 project: this uuid is the one the
    # editor compresses into the `__type__` value found in its scenes.
    assert compress_uuid(SCRIPT_UUID) == SCRIPT_CLASS_ID
    assert len(compress_uuid(SCRIPT_UUID)) == 23
    assert compress_uuid("not-a-uuid") == ""


def test_index_resolves_class_ids_ccclass_names_and_engine_types(tmp_path: Path) -> None:
    _cocos_project(tmp_path)
    index = CocosAssetIndex(tmp_path, _paths(tmp_path))

    by_class_id = index.resolve_component_type(SCRIPT_CLASS_ID)
    assert by_class_id["source"] == "class-id"
    assert by_class_id["script"]["path"] == "assets/scripts/VideoIcon.ts"

    by_name = index.resolve_component_type("VideoIcon")
    assert by_name["source"] == "ccclass"
    assert by_name["script"]["path"] == "assets/scripts/VideoIcon.ts"

    assert index.resolve_component_type("cc.Sprite")["source"] == "engine"
    # A namespaced extension type is engine-owned, not a missing project script.
    assert index.resolve_component_type("dragonBones.ArmatureDisplay")["source"] == "engine"
    assert index.resolve_component_type("GhostComponent")["source"] == "unresolved"

    assert index.asset_for_uuid(f"{TEXTURE_UUID}@f9941") == "assets/res/icon.png"


def test_scene_analysis_reports_hierarchy_scripts_and_references(tmp_path: Path) -> None:
    _cocos_project(tmp_path)
    index = CocosAssetIndex(tmp_path, _paths(tmp_path))

    detail = analyze_cocos_asset(tmp_path, "assets/scene/main.scene", index)

    assert detail["kind"] == "scene"
    assert detail["status"] == "parsed"
    assert detail["ownership"] == "project-owned"
    assert [item["path"] for item in detail["objects"]] == ["Canvas", "Canvas/Icon"]
    assert detail["root_objects"] == [1]
    scripts = [
        component["script"]["path"]
        for item in detail["objects"]
        for component in item["components"]
        if "script" in component
    ]
    assert scripts == ["assets/scripts/VideoIcon.ts"]
    assert {"target": "assets/res/icon.png", "kind": "asset_uuid"} in detail["references"]
    assert "Cocos scene `main`" in detail["responsibility"]
    assert "unresolved" not in detail["responsibility"]


def test_unresolved_component_is_reported_not_guessed(tmp_path: Path) -> None:
    _cocos_project(tmp_path)
    records = _scene_records()
    records[4] = {"__type__": "StaleClassId", "node": {"__id__": 1}}
    _write(tmp_path / "assets" / "scene" / "main.scene", records)
    index = CocosAssetIndex(tmp_path, _paths(tmp_path))

    detail = analyze_cocos_asset(tmp_path, "assets/scene/main.scene", index)

    assert detail["unresolved_components"] == ["StaleClassId"]
    assert "unresolved component type(s)" in detail["responsibility"]


def test_runtime_analysis_and_edges(tmp_path: Path) -> None:
    _cocos_project(tmp_path)

    runtime = analyze_cocos_runtime(tmp_path, _paths(tmp_path))

    assert runtime["kind"] == "cocos"
    assert runtime["metrics"]["scenes"] == 1
    assert runtime["metrics"]["resolved_scripts"] == 1
    assert runtime["coverage"] == {"candidates": 1, "parsed": 1}
    assert runtime["index"]["script_class_ids"] == 1

    edges = collect_cocos_reference_edges(runtime)
    targets = {(edge["target"], edge["kind"]) for edge in edges}
    assert ("assets/res/icon.png", "cocos_asset_uuid") in targets
    assert ("assets/scripts/VideoIcon.ts", "cocos_component") in targets
    assert all(edge["confidence"] == "exact" for edge in edges)


def test_project_facts_expose_the_bundle_contract(tmp_path: Path) -> None:
    _cocos_project(tmp_path)

    facts = collect_cocos_project_facts(tmp_path, _paths(tmp_path))

    assert facts["kind"] == "cocos"
    assert facts["creator_version"] == "3.8.8"
    assert facts["start_scene"] == "626242e7-577e-505b-964c-570f4b31b5ac"
    assert facts["bundles"] == [
        {
            "folder": "assets/resources",
            "bundle_name": "resources",
            "priority": 8,
            "config_id": None,
        }
    ]
    assert facts["extensions"] == ["extensions/dev-tools"]
    assert facts["ownership_counts"]["project-owned"] >= 4


def test_generated_roots_are_not_project_owned(tmp_path: Path) -> None:
    _cocos_project(tmp_path)
    _write(tmp_path / "library" / "imports" / "cache.json", {"x": 1})
    _write(tmp_path / "temp" / "programming" / "packer-driver.json", {"x": 1})

    facts = collect_cocos_project_facts(tmp_path, _paths(tmp_path))

    assert facts["ownership_counts"].get("generated") == 2
    assert "library" in " ".join(facts["generated_roots"])
