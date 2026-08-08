"""Unity and C# behavior added by the custom fork."""

from pathlib import Path

import pytest

from better_context.agents_map import BEGIN, END, generate_agents_map, remove_managed_map
from better_context.cli import main
from better_context.languages.csharp import CSharpAdapter
from better_context.orchestrator import Orchestrator
from better_context.primitives.overview import analyze_overview


@pytest.fixture
def unity_project(tmp_path: Path) -> Path:
    root = tmp_path / "UnityGame"
    scripts = root / "Assets" / "Scripts"
    scripts.mkdir(parents=True)
    (root / "ProjectSettings").mkdir()
    (root / "Packages").mkdir()
    (root / "Library").mkdir()
    (root / "ProjectSettings" / "ProjectVersion.txt").write_text(
        "m_EditorVersion: 6000.0.0f1\n", encoding="utf-8"
    )
    (root / "Packages" / "manifest.json").write_text("{}\n", encoding="utf-8")
    (scripts / "PlayerController.cs").write_text(
        """using UnityEngine;
namespace Game.Gameplay;

/// <summary>Controls the player.</summary>
public sealed class PlayerController : MonoBehaviour
{
    private void Awake() { }
    public void TakeDamage(int amount) { }
}
""",
        encoding="utf-8",
    )
    (scripts / "DamageSystem.cs").write_text(
        """namespace Game.Gameplay;
public sealed class DamageSystem
{
    public void Apply(PlayerController player) { }
}
""",
        encoding="utf-8",
    )
    (root / "Library" / "Generated.cs").write_text("public class Generated {}\n", encoding="utf-8")
    (root / "AGENTS.md").write_text("# Handwritten rules\n\nDo not replace me.\n", encoding="utf-8")
    return root


def test_csharp_adapter_extracts_unity_types_and_methods():
    source = """using UnityEngine;
using Alias = Game.Shared.Service;
namespace Game;
public class Player : MonoBehaviour
{
    private void Awake() { }
    public void Move(float speed) { }
}
"""
    result = CSharpAdapter().parse_file("Assets/Scripts/Player.cs", source)

    player = next(chunk for chunk in result.chunks if chunk.name == "Player")
    move = next(chunk for chunk in result.chunks if chunk.name == "Move")
    assert player.metadata["unity_type"] == "MonoBehaviour"
    assert move.parent == player.id
    assert {item.module for item in result.imports} == {"UnityEngine", "Game.Shared.Service"}


def test_unity_overview(unity_project: Path):
    overview = analyze_overview(unity_project)
    assert overview.primary_language == "csharp"
    assert overview.package_manager == "unity-package-manager"
    assert overview.frameworks == ["unity"]
    assert "Assets" in overview.source_dirs


def test_unity_scan_builds_csharp_edges_and_ignores_library(unity_project: Path):
    analysis = Orchestrator(unity_project).analyze()
    paths = {entry.path for entry in analysis.manifest.files}
    assert "Library/Generated.cs" not in paths
    assert analysis.graph.has_edge(
        "Assets/Scripts/DamageSystem.cs",
        "Assets/Scripts/PlayerController.cs",
    )


def test_agents_map_preserves_handwritten_content_and_is_idempotent(unity_project: Path):
    orchestrator = Orchestrator(unity_project)
    analysis = orchestrator.analyze()
    first = generate_agents_map(analysis.manifest, analysis.graph, unity_project)
    assert not first.errors

    root_map = (unity_project / "AGENTS.md").read_text(encoding="utf-8")
    scripts_map = (unity_project / "Assets" / "Scripts" / "AGENTS.md").read_text(encoding="utf-8")
    assert "Do not replace me." in root_map
    assert root_map.count(BEGIN) == 1
    assert "PlayerController (MonoBehaviour)" in scripts_map
    assert not (unity_project / "Library" / "AGENTS.md").exists()

    refreshed = Orchestrator(unity_project).analyze()
    second = generate_agents_map(refreshed.manifest, refreshed.graph, unity_project)
    assert not second.files_written

    assert remove_managed_map(unity_project / "AGENTS.md")
    remaining = (unity_project / "AGENTS.md").read_text(encoding="utf-8")
    assert "Do not replace me." in remaining
    assert BEGIN not in remaining and END not in remaining


def test_agents_cli_writes_context_that_verifies_fresh(unity_project: Path, capsys):
    assert main(["--root", str(unity_project), "agents"]) == 0
    capsys.readouterr()

    assert (unity_project / ".better-context" / "manifest.json").is_file()
    assert (unity_project / ".better-context" / "staleness.json").is_file()
    assert main(["--root", str(unity_project), "verify"]) == 0
