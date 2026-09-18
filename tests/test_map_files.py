"""Coverage for multi-client instruction maps (AGENTS.md and CLAUDE.md)."""

from __future__ import annotations

from pathlib import Path

import pytest

from better_context.agents_map import (
    BEGIN,
    DEFAULT_MAP_FILENAMES,
    MAP_FILENAMES,
    generate_agents_map,
    is_map_filename,
    is_map_meta_filename,
    is_map_path,
    remove_managed_map,
    resolve_map_filenames,
)
from better_context.config import Config, validate_config
from better_context.graph import build_graph_from_edges
from better_context.manifest import FileEntry, GraphData, Manifest, ManifestMeta


def _unity_project(root: Path) -> tuple[Manifest, object]:
    (root / "Assets" / "Scripts").mkdir(parents=True)
    (root / "ProjectSettings").mkdir()
    (root / "ProjectSettings" / "ProjectVersion.txt").write_text(
        "m_EditorVersion: 6000.3.21f1\n", encoding="utf-8"
    )
    script = root / "Assets" / "Scripts" / "Player.cs"
    script.write_text("public class Player {}\n", encoding="utf-8")
    entry = FileEntry(
        path="Assets/Scripts/Player.cs",
        language="csharp",
        size_bytes=script.stat().st_size,
        hash="player",
        metadata={"ownership": "project-owned"},
    )
    manifest = Manifest(
        meta=ManifestMeta("1.3.0", "now", "test", root.as_posix(), "hash"),
        files=[entry],
        graph=GraphData(nodes=[entry.path]),
        project={"kind": "unity"},
    )
    return manifest, build_graph_from_edges([], nodes=[entry.path])


def test_default_selection_writes_only_agents_md(tmp_path: Path) -> None:
    manifest, graph = _unity_project(tmp_path)

    result = generate_agents_map(manifest, graph, tmp_path)

    assert (tmp_path / "AGENTS.md").exists()
    assert not (tmp_path / "CLAUDE.md").exists()
    assert all(path.endswith("AGENTS.md") for path in result.files_written)


def test_both_clients_share_one_scan(tmp_path: Path) -> None:
    manifest, graph = _unity_project(tmp_path)
    (tmp_path / "CLAUDE.md").write_text("# Handwritten\n\nKeep this.\n", encoding="utf-8")

    generate_agents_map(manifest, graph, tmp_path, map_filenames=["AGENTS.md", "CLAUDE.md"])

    agents_root = (tmp_path / "AGENTS.md").read_text(encoding="utf-8")
    claude_root = (tmp_path / "CLAUDE.md").read_text(encoding="utf-8")
    assert BEGIN in agents_root and BEGIN in claude_root
    assert "Keep this." in claude_root
    # Same scan, same managed content, only the navigation links differ.
    assert agents_root.count(BEGIN) == 1
    assert "Assets/AGENTS.md" in sorted(
        path.relative_to(tmp_path).as_posix() for path in tmp_path.rglob("AGENTS.md")
    )
    assets_agents = (tmp_path / "Assets" / "AGENTS.md").read_text(encoding="utf-8")
    assets_claude = (tmp_path / "Assets" / "CLAUDE.md").read_text(encoding="utf-8")
    assert "Scripts/AGENTS.md" in assets_agents
    assert "Scripts/CLAUDE.md" in assets_claude
    assert "Scripts/AGENTS.md" not in assets_claude

    nested_claude = (tmp_path / "Assets" / "Scripts" / "CLAUDE.md").read_text(encoding="utf-8")
    assert "Parent map: [`../CLAUDE.md`](../CLAUDE.md)" in nested_claude
    nested_agents = (tmp_path / "Assets" / "Scripts" / "AGENTS.md").read_text(encoding="utf-8")
    assert "Parent map: [`../AGENTS.md`](../AGENTS.md)" in nested_agents


def test_existing_client_maps_are_not_analysed_as_source(tmp_path: Path) -> None:
    manifest, graph = _unity_project(tmp_path)
    manifest.files.append(
        FileEntry(
            path="Assets/Scripts/CLAUDE.md",
            language="",
            size_bytes=1,
            hash="claude-map",
            metadata={"ownership": "project-owned"},
        )
    )

    generate_agents_map(manifest, graph, tmp_path, map_filenames=["CLAUDE.md"])

    nested = (tmp_path / "Assets" / "Scripts" / "CLAUDE.md").read_text(encoding="utf-8")
    assert "| [`CLAUDE.md`]" not in nested
    assert "| [`Player.cs`]" in nested


def test_stale_managed_block_is_removed_for_every_selected_client(tmp_path: Path) -> None:
    manifest, graph = _unity_project(tmp_path)
    stale_dir = tmp_path / "Assets" / "Removed"
    stale_dir.mkdir(parents=True)
    for filename in ("AGENTS.md", "CLAUDE.md"):
        (stale_dir / filename).write_text(
            f"{BEGIN}\nstale\n<!-- better-context-unity:end -->\n", encoding="utf-8"
        )

    result = generate_agents_map(
        manifest, graph, tmp_path, map_filenames=["AGENTS.md", "CLAUDE.md"]
    )

    assert "Assets/Removed/AGENTS.md" in result.files_removed
    assert "Assets/Removed/CLAUDE.md" in result.files_removed
    assert not (stale_dir / "AGENTS.md").exists()
    assert not (stale_dir / "CLAUDE.md").exists()


def test_remove_managed_map_keeps_handwritten_claude_instructions(tmp_path: Path) -> None:
    target = tmp_path / "CLAUDE.md"
    target.write_text(
        f"# Project rules\n\nNever run Unity in play mode.\n\n{BEGIN}\nmanaged\n"
        "<!-- better-context-unity:end -->\n",
        encoding="utf-8",
    )

    assert remove_managed_map(target) is True
    remaining = target.read_text(encoding="utf-8")
    assert "Never run Unity in play mode." in remaining
    assert BEGIN not in remaining


@pytest.mark.parametrize(
    ("values", "expected"),
    [
        (None, DEFAULT_MAP_FILENAMES),
        ([], DEFAULT_MAP_FILENAMES),
        (["CLAUDE.md"], ("CLAUDE.md",)),
        (["claude.md", "AGENTS.md", "CLAUDE.md"], ("CLAUDE.md", "AGENTS.md")),
    ],
)
def test_resolve_map_filenames(values: list[str] | None, expected: tuple[str, ...]) -> None:
    assert resolve_map_filenames(values) == expected


def test_resolve_map_filenames_rejects_unknown_target() -> None:
    with pytest.raises(ValueError, match="Unsupported map file"):
        resolve_map_filenames(["README.md"])


def test_map_filename_recognition_covers_both_clients() -> None:
    assert set(MAP_FILENAMES) == {"AGENTS.md", "CLAUDE.md"}
    assert is_map_filename("CLAUDE.md") and is_map_filename("agents.md")
    assert is_map_path("Assets/Scripts/CLAUDE.md")
    assert not is_map_path("Assets/Scripts/Player.cs")
    assert is_map_meta_filename("CLAUDE.md.meta") and is_map_meta_filename("AGENTS.md.meta")


def test_config_validates_map_files() -> None:
    assert Config().map_files == list(DEFAULT_MAP_FILENAMES)
    assert validate_config(Config(map_files=["AGENTS.md", "CLAUDE.md"])) == []
    assert validate_config(Config(map_files=[])) != []
    assert validate_config(Config(map_files=["README.md"])) != []
