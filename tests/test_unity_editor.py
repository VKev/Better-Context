"""Tests for Unity Editor snapshot and component enrichment."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from better_context.cli import create_parser
from better_context.scanner import walk_repository
from better_context.unity_editor import (
    EDITOR_BRIDGE_VERSION,
    EDITOR_PACKAGE_NAME,
    EDITOR_SNAPSHOT_SCHEMA,
    compute_editor_source_hash,
    compute_package_lock_hash,
    editor_snapshot_path,
    get_editor_snapshot_status,
    install_editor_package,
    normalize_editor_snapshot,
)
from better_context.unity_runtime import analyze_unity_runtime


def _unity_project(root: Path) -> None:
    (root / "Assets").mkdir()
    (root / "Packages").mkdir()
    (root / "ProjectSettings").mkdir()
    (root / "ProjectSettings" / "ProjectVersion.txt").write_text(
        "m_EditorVersion: 2022.3.62f2\n"
    )
    (root / "Packages" / "manifest.json").write_text('{"dependencies": {}}')
    (root / "Packages" / "packages-lock.json").write_text("{}")


def _snapshot(root: Path, *, source_hash: str | None = None) -> dict[str, object]:
    return {
        "schema_version": EDITOR_SNAPSHOT_SCHEMA,
        "bridge_version": EDITOR_BRIDGE_VERSION,
        "unity_version": "2022.3.62f2",
        "mode": "batch",
        "nonce": "fixture",
        "source_hash": source_hash or compute_editor_source_hash(root),
        "package_lock_hash": compute_package_lock_hash(root),
        "status": "ok",
        "coverage": {"assets_scanned": 1, "assets_exported": 1, "mono_scripts": 0},
        "assets": [],
        "scripts": [],
        "errors": [],
    }


def test_snapshot_status_rejects_stale_and_normalizes_facts(tmp_path: Path) -> None:
    _unity_project(tmp_path)
    snapshot = _snapshot(tmp_path)
    snapshot["assets"] = [
        {
            "path": "Assets/Icon.png",
            "guid": "1" * 32,
            "kind": "texture",
            "facts": [{"name": "source_width", "value": "128"}],
            "subassets": [
                {
                    "name": "Icon",
                    "local_id": 21300000,
                    "type_name": "UnityEngine.Sprite",
                    "facts": [],
                }
            ],
        }
    ]
    path = editor_snapshot_path(tmp_path)
    path.parent.mkdir()
    path.write_text(json.dumps(snapshot))

    status = get_editor_snapshot_status(tmp_path)

    assert status.state == "fresh"
    assert status.snapshot is not None
    asset = status.snapshot["assets_by_path"]["Assets/Icon.png"]
    assert asset["facts"]["source_width"] == "128"
    assert status.snapshot["subassets_by_identity"][f"{'1' * 32}:21300000"]["name"] == "Icon"

    (tmp_path / "Assets" / "Changed.cs").write_text("class Changed {}")
    assert get_editor_snapshot_status(tmp_path).state == "stale"


def test_editor_install_pins_git_subfolder(tmp_path: Path) -> None:
    _unity_project(tmp_path)
    manifest_path = tmp_path / "Packages" / "manifest.json"
    manifest_path.write_text(
        '{\n  "dependencies": {\n    "z.last": "1.0.0",\n'
        '    "a.first": "1.0.0"\n  }\n}\n'
    )

    success, _message = install_editor_package(tmp_path, "abc123")

    assert success
    installed_text = manifest_path.read_text()
    manifest = json.loads(installed_text)
    assert manifest["dependencies"][EDITOR_PACKAGE_NAME].endswith(
        "?path=/unity-package/com.vkev.better-context.editor#abc123"
    )
    assert installed_text.endswith("\n")
    assert installed_text.index('"z.last"') < installed_text.index('"a.first"')
    assert installed_text.index('"a.first"') < installed_text.index(
        f'"{EDITOR_PACKAGE_NAME}"'
    )


def test_editor_commands_and_component_query_parse() -> None:
    parser = create_parser()

    install = parser.parse_args(["editor", "install", "--revision", "abc"])
    default_install = parser.parse_args(["editor", "install"])
    sync = parser.parse_args(["editor", "sync", "--mode", "batch"])
    components = parser.parse_args(
        ["unity", "components", "--asset", "Assets/UI.prefab", "--type", "Image"]
    )

    assert (install.command, install.editor_command, install.revision) == (
        "editor",
        "install",
        "abc",
    )
    assert sync.mode == "batch"
    assert default_install.revision == "v1.6.0"
    assert components.unity_command == "components"
    assert components.type == "Image"


def test_texture_snapshot_creates_direct_dependency_without_meta(tmp_path: Path) -> None:
    _unity_project(tmp_path)
    icon = tmp_path / "Assets" / "Icon.png"
    icon.write_bytes(b"\x89PNG\r\n\x1a\nfixture")
    (tmp_path / "Assets" / "Icon.png.meta").write_text(f"guid: {'1' * 32}\n")
    (tmp_path / "Assets" / "Shared.mat").write_text(
        "%YAML 1.1\n--- !u!21 &1\nMaterial:\n  m_Name: Shared\n"
    )
    (tmp_path / "Assets" / "Shared.mat.meta").write_text(f"guid: {'2' * 32}\n")
    snapshot = normalize_editor_snapshot(_snapshot(tmp_path))
    snapshot["assets_by_path"] = {
        "Assets/Icon.png": {
            "path": "Assets/Icon.png",
            "guid": "1" * 32,
            "kind": "texture",
            "facts": {"source_width": "128", "source_height": "64", "mipmaps": "false"},
            "subassets": [],
            "dependencies": ["Assets/Shared.mat", "Assets/Icon.png.meta"],
        }
    }
    inventory = walk_repository(tmp_path)

    analysis = analyze_unity_runtime(
        tmp_path,
        inventory,
        [SimpleNamespace(path=item.path, chunks=[], metadata={}) for item in inventory.files],
        editor_snapshot=snapshot,
    )

    texture = analysis.assets["Assets/Icon.png"]
    assert texture["kind"] == "texture"
    assert texture["editor_asset"]["facts"]["source_width"] == "128"
    assert any(
        detail["source"] == "Assets/Icon.png"
        and detail["target"] == "Assets/Shared.mat"
        and detail["kinds"] == ["asset_database_direct"]
        for detail in analysis.edge_details
    )
    assert all(not detail["target"].endswith(".meta") for detail in analysis.edge_details)


def test_monoscript_get_class_resolves_ui_component_and_sprite(tmp_path: Path) -> None:
    _unity_project(tmp_path)
    script_guid = "a" * 32
    sprite_guid = "b" * 32
    prefab = tmp_path / "Assets" / "Button.prefab"
    prefab.write_text(
        "%YAML 1.1\n"
        "--- !u!1 &1\n"
        "GameObject:\n"
        "  m_Component:\n"
        "  - component: {fileID: 2}\n"
        "  m_Name: Button\n"
        "  m_IsActive: 1\n"
        "--- !u!114 &2\n"
        "MonoBehaviour:\n"
        "  m_GameObject: {fileID: 1}\n"
        "  m_Enabled: 1\n"
        f"  m_Script: {{fileID: 11500000, guid: {script_guid}, type: 3}}\n"
        f"  m_Sprite: {{fileID: 21300000, guid: {sprite_guid}, type: 3}}\n"
        "  m_Type: 0\n"
        "  m_PreserveAspect: 1\n"
    )
    (tmp_path / "Assets" / "Button.prefab.meta").write_text(f"guid: {'c' * 32}\n")
    (tmp_path / "Assets" / "Icon.png").write_bytes(b"\x89PNG\r\n\x1a\nfixture")
    (tmp_path / "Assets" / "Icon.png.meta").write_text(f"guid: {sprite_guid}\n")
    snapshot = normalize_editor_snapshot(
        {
            **_snapshot(tmp_path),
            "assets": [
                {
                    "path": "Assets/Icon.png",
                    "guid": sprite_guid,
                    "kind": "texture",
                    "facts": [],
                    "subassets": [
                        {
                            "name": "Icon",
                            "local_id": 21300000,
                            "sprite_id": "sprite-id",
                            "type_name": "UnityEngine.Sprite",
                            "facts": [],
                        }
                    ],
                    "dependencies": [],
                }
            ],
            "scripts": [
                {
                    "guid": script_guid,
                    "path": "Packages/com.unity.ugui/Runtime/UI/Core/Image.cs",
                    "qualified_type": "UnityEngine.UI.Image",
                    "assembly": "UnityEngine.UI",
                    "base_type": "UnityEngine.EventSystems.UIBehaviour",
                    "boundary": "package",
                    "resolved": True,
                }
            ],
        }
    )
    inventory = walk_repository(tmp_path)

    analysis = analyze_unity_runtime(
        tmp_path,
        inventory,
        [SimpleNamespace(path=item.path, chunks=[], metadata={}) for item in inventory.files],
        editor_snapshot=snapshot,
    )

    component = analysis.assets["Assets/Button.prefab"]["objects"][0]["components"][0]
    assert component["qualified_type"] == "UnityEngine.UI.Image"
    assert component["boundary"] == "package"
    assert component["provenance"] == "unity-editor-monoscript"
    sprite = next(item for item in component["references"] if item["field"] == "m_Sprite")
    assert sprite["target"] == "Assets/Icon.png"
    assert sprite["subasset"] == {
        "name": "Icon",
        "type": "UnityEngine.Sprite",
        "local_id": 21300000,
        "sprite_id": "sprite-id",
    }
