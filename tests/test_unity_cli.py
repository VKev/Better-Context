"""Tests for querying Unity runtime intelligence from a saved manifest."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from better_context.cli import _trim_unity_depth, create_parser, main
from better_context.config import Config
from better_context.manifest import (
    FileEntry,
    GraphData,
    Manifest,
    create_manifest_meta,
    save_manifest,
)
from better_context.staleness import collect_current_hashes, save_staleness_info


@pytest.fixture
def unity_runtime_project(tmp_path: Path) -> Path:
    asset_path = tmp_path / "Assets" / "UI" / "GunButton.prefab"
    asset_path.parent.mkdir(parents=True)
    asset_path.write_text("%YAML 1.1\n--- !u!1 &1\nGameObject:\n  m_Name: GunButton\n")

    full_runtime = {
        "path": "Assets/UI/GunButton.prefab",
        "kind": "prefab",
        "status": "parsed",
        "ownership": "project-owned",
        "objects": [
            {"path": "GunButton", "depth": 0},
            {"path": "GunButton/Label", "depth": 1},
            {"path": "GunButton/Label/Glyph", "depth": 2},
        ],
        "event_bindings": [
            {
                "asset": "Assets/UI/GunButton.prefab",
                "owner_object": "GunButton",
                "target_type": "GunButtonView",
                "target_script": "Assets/Scripts/GunButtonView.cs",
                "method": "SwitchGun",
                "mode": 1,
                "status": "resolved",
            }
        ],
    }
    compact = {
        "path": "Assets/UI/GunButton.prefab",
        "kind": "prefab",
        "status": "parsed",
        "ownership": "project-owned",
        "object_count": 3,
        "component_count": 4,
        "script_types": ["GunButtonView"],
        "root_objects": ["GunButton"],
        "event_count": 1,
        "animator_state_count": 0,
        "signal_score": 8,
    }
    binding = full_runtime["event_bindings"][0]
    config_hash = hashlib.sha256(str(vars(Config())).encode()).hexdigest()[:16]
    manifest = Manifest(
        meta=create_manifest_meta(tmp_path, config_hash),
        files=[
            FileEntry(
                path="Assets/UI/GunButton.prefab",
                language="unity-yaml",
                size_bytes=asset_path.stat().st_size,
                hash="fixture",
                metadata={"unity_runtime": full_runtime},
            )
        ],
        graph=GraphData(nodes=["Assets/UI/GunButton.prefab"]),
        project={
            "unity_runtime": {
                "engine": "unity",
                "scope": "project-owned",
                "coverage": {"eligible": 1, "parsed": 1},
                "metrics": {"assets": 1, "prefabs": 1},
                "assets": [compact],
                "event_bindings": [binding],
                "errors": [],
            }
        },
    )
    save_manifest(manifest, tmp_path / ".better-context" / "manifest.json")
    save_staleness_info(
        tmp_path,
        collect_current_hashes(tmp_path),
        manifest.meta.generated_at,
    )
    return tmp_path


def test_unity_nested_commands_parse() -> None:
    parser = create_parser()

    list_args = parser.parse_args(["unity", "list", "--kind", "prefab", "--limit", "10"])
    show_args = parser.parse_args(["unity", "show", "Assets/UI/GunButton.prefab", "--depth", "-1"])
    binding_args = parser.parse_args(["unity", "bindings", "--method", "SwitchGun"])

    assert (list_args.command, list_args.unity_command, list_args.format) == (
        "unity",
        "list",
        "json",
    )
    assert show_args.depth == -1
    assert binding_args.method == "SwitchGun"


def test_unity_show_depth_trims_fbx_hierarchy() -> None:
    runtime = {
        "path": "Assets/Hero.fbx",
        "model": {
            "root_nodes": [
                {
                    "name": "Root",
                    "children": [
                        {
                            "name": "Hips",
                            "children": [
                                {
                                    "name": "Spine",
                                    "children": [{"name": "Chest", "children": []}],
                                }
                            ],
                        }
                    ],
                }
            ]
        },
    }

    trimmed = _trim_unity_depth(runtime, 2)

    spine = trimmed["model"]["root_nodes"][0]["children"][0]["children"][0]
    assert spine["name"] == "Spine"
    assert spine["children"] == []


def test_unity_list_filters_assets(
    unity_runtime_project: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    exit_code = main(
        [
            "--root",
            str(unity_runtime_project),
            "unity",
            "list",
            "--kind",
            "prefab",
        ]
    )

    output = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert output["shown"] == 1
    assert output["total"] == 1
    assert output["assets"][0]["script_types"] == ["GunButtonView"]


def test_unity_show_normalizes_path_and_limits_hierarchy(
    unity_runtime_project: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    exit_code = main(
        [
            "--root",
            str(unity_runtime_project),
            "unity",
            "show",
            "Assets\\UI\\GunButton.prefab",
            "--depth",
            "1",
        ]
    )

    output = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert output["path"] == "Assets/UI/GunButton.prefab"
    assert [item["path"] for item in output["objects"]] == ["GunButton", "GunButton/Label"]


def test_unity_bindings_filters_exact_type_and_method(
    unity_runtime_project: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    exit_code = main(
        [
            "--root",
            str(unity_runtime_project),
            "unity",
            "bindings",
            "--type",
            "gunbuttonview",
            "--method",
            "switchgun",
        ]
    )

    output = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert output["count"] == 1
    assert output["bindings"][0]["status"] == "resolved"


def test_unity_queries_accept_full_per_file_fallback_schema(
    unity_runtime_project: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Queries stay useful when compact root indexes are absent."""
    manifest_path = unity_runtime_project / ".better-context" / "manifest.json"
    data = json.loads(manifest_path.read_text())
    data["project"]["unity_runtime"].pop("assets")
    data["project"]["unity_runtime"].pop("event_bindings")
    full = data["files"][0]["metadata"]["unity_runtime"]
    full["unity_events"] = full.pop("event_bindings")
    full["unity_events"][0]["owner_path"] = full["unity_events"][0].pop("owner_object")
    full["unity_events"][0]["confidence"] = full["unity_events"][0].pop("status")
    manifest_path.write_text(json.dumps(data))

    assert main(["--root", str(unity_runtime_project), "unity", "list"]) == 0
    listed = json.loads(capsys.readouterr().out)
    assert listed["assets"][0]["event_count"] == 1

    assert main(["--root", str(unity_runtime_project), "unity", "bindings"]) == 0
    bindings = json.loads(capsys.readouterr().out)
    assert bindings["bindings"][0]["owner_object"] == "GunButton"
    assert bindings["bindings"][0]["status"] == "resolved"


def test_unity_command_rejects_missing_manifest(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["--root", str(tmp_path), "unity", "list"]) == 1

    output = capsys.readouterr().out
    assert "Manifest not found" in output
    assert "better-context-unity agents" in output


def test_unity_command_rejects_stale_manifest(
    unity_runtime_project: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    asset_path = unity_runtime_project / "Assets" / "UI" / "GunButton.prefab"
    asset_path.write_text(asset_path.read_text() + "  m_IsActive: 1\n")

    assert main(["--root", str(unity_runtime_project), "unity", "list"]) == 1

    output = capsys.readouterr().out
    assert "manifest is stale" in output
    assert "better-context-unity agents" in output


def test_unity_command_rejects_mismatched_freshness_generation(
    unity_runtime_project: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    staleness_path = unity_runtime_project / ".better-context" / "staleness.json"
    staleness = json.loads(staleness_path.read_text())
    staleness["generated_at"] = "2000-01-01T00:00:00+00:00"
    staleness_path.write_text(json.dumps(staleness))

    assert main(["--root", str(unity_runtime_project), "unity", "list"]) == 1

    output = capsys.readouterr().out
    assert "generated by different analyses" in output
    assert "better-context-unity agents" in output


def test_unity_command_rejects_mismatched_config_hash(
    unity_runtime_project: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    manifest_path = unity_runtime_project / ".better-context" / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["meta"]["config_hash"] = "old-config"
    manifest_path.write_text(json.dumps(manifest))

    assert main(["--root", str(unity_runtime_project), "unity", "list"]) == 1

    output = capsys.readouterr().out
    assert "generated with different configuration" in output
    assert "better-context-unity agents" in output


@pytest.mark.parametrize("command", ["scan", "agents"])
def test_generation_commands_honor_explicit_config(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    command: str,
) -> None:
    project = tmp_path / command
    project.mkdir()
    (project / "README.md").write_text("fixture\n")
    config_path = tmp_path / f"{command}.json"
    config_path.write_text(json.dumps({"output_dir": ".custom-context"}))

    assert (
        main(
            [
                "--root",
                str(project),
                "--config",
                str(config_path),
                command,
            ]
        )
        == 0
    )
    capsys.readouterr()

    assert (project / ".custom-context" / "manifest.json").exists()
    assert not (project / ".better-context" / "manifest.json").exists()


def test_unity_list_rejects_non_positive_limit(
    unity_runtime_project: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert (
        main(
            [
                "--root",
                str(unity_runtime_project),
                "unity",
                "list",
                "--limit",
                "0",
            ]
        )
        == 1
    )
    assert "--limit must be a positive integer" in capsys.readouterr().out
