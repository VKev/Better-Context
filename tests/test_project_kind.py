"""Project-kind detection: Unity, Cocos Creator, or a plain repository."""

from __future__ import annotations

import json
from pathlib import Path

from better_context.project_kind import (
    COCOS_KIND,
    REPOSITORY_KIND,
    UNITY_KIND,
    cocos_creator_version,
    detect_project_kind,
    is_cocos_project,
    is_unity_project,
    resolve_project_kind,
)


def _unity(root: Path) -> Path:
    (root / "Assets").mkdir(parents=True)
    (root / "ProjectSettings").mkdir()
    (root / "ProjectSettings" / "ProjectVersion.txt").write_text(
        "m_EditorVersion: 6000.3.21f1\n", encoding="utf-8"
    )
    return root


def _cocos(root: Path, version: str = "3.8.8") -> Path:
    (root / "assets").mkdir(parents=True)
    (root / "package.json").write_text(
        json.dumps({"name": "game", "creator": {"version": version}}), encoding="utf-8"
    )
    return root


def test_unity_project_is_detected(tmp_path: Path) -> None:
    _unity(tmp_path)
    assert is_unity_project(tmp_path)
    assert detect_project_kind(tmp_path) == UNITY_KIND


def test_cocos_project_is_detected(tmp_path: Path) -> None:
    _cocos(tmp_path)
    assert is_cocos_project(tmp_path)
    assert cocos_creator_version(tmp_path) == "3.8.8"
    assert detect_project_kind(tmp_path) == COCOS_KIND


def test_node_project_without_creator_field_is_a_plain_repository(tmp_path: Path) -> None:
    (tmp_path / "assets").mkdir()
    (tmp_path / "package.json").write_text(json.dumps({"name": "site"}), encoding="utf-8")

    assert not is_cocos_project(tmp_path)
    assert detect_project_kind(tmp_path) == REPOSITORY_KIND


def test_unity_wins_over_incidental_node_tooling(tmp_path: Path) -> None:
    # A case-insensitive filesystem makes `Assets/` answer to `assets/`, so the Unity
    # check must run first for a Unity project that also carries Node tooling.
    _unity(tmp_path)
    (tmp_path / "package.json").write_text(
        json.dumps({"name": "tools", "creator": {"version": "3.8.8"}}), encoding="utf-8"
    )

    assert detect_project_kind(tmp_path) == UNITY_KIND


def test_broken_package_json_does_not_raise(tmp_path: Path) -> None:
    (tmp_path / "assets").mkdir()
    (tmp_path / "package.json").write_text("{not json", encoding="utf-8")

    assert cocos_creator_version(tmp_path) == ""
    assert detect_project_kind(tmp_path) == REPOSITORY_KIND


def test_explicit_override_wins_and_unknown_values_fall_back(tmp_path: Path) -> None:
    _cocos(tmp_path)

    assert resolve_project_kind(tmp_path, "repository") == REPOSITORY_KIND
    assert resolve_project_kind(tmp_path, "auto") == COCOS_KIND
    assert resolve_project_kind(tmp_path, "") == COCOS_KIND
    assert resolve_project_kind(tmp_path, "godot") == COCOS_KIND
