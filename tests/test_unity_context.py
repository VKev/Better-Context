"""Unity and C# behavior added by the custom fork."""

import json
from pathlib import Path

import pytest

from better_context.agents_map import (
    BEGIN,
    END,
    SUMMARY_FILE,
    generate_agents_map,
    remove_managed_map,
)
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
    assert "`PlayerController` (MonoBehaviour)" in scripts_map
    assert "Named dependencies / dependents" in scripts_map
    assert "Ca/Ce/I/A/D" in scripts_map
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


def test_agents_cli_adds_and_persists_optional_summaries(unity_project: Path, capsys):
    args = [
        "--root",
        str(unity_project),
        "agents",
        "--summary",
        "Assets/Scripts=Runtime character and combat scripts.",
        "--summary",
        "Assets\\Scripts\\PlayerController.cs=Coordinates player control | damage handling.",
    ]
    assert main(args) == 0
    capsys.readouterr()

    stored = json.loads((unity_project / SUMMARY_FILE).read_text(encoding="utf-8"))
    assert stored == {
        "Assets/Scripts": "Runtime character and combat scripts.",
        "Assets/Scripts/PlayerController.cs": "Coordinates player control | damage handling.",
    }

    assets_map = (unity_project / "Assets" / "AGENTS.md").read_text(encoding="utf-8")
    scripts_map = (unity_project / "Assets" / "Scripts" / "AGENTS.md").read_text(encoding="utf-8")
    assert "| Folder | Purpose | Summary |" in assets_map
    assert "Runtime character and combat scripts." in assets_map
    assert "Verified responsibility" in scripts_map
    assert r"Coordinates player control \| damage handling." in scripts_map

    assert main(["--root", str(unity_project), "agents"]) == 0
    refreshed = (unity_project / "Assets" / "Scripts" / "AGENTS.md").read_text(encoding="utf-8")
    assert r"Coordinates player control \| damage handling." in refreshed


def test_agents_cli_can_remove_optional_summary(unity_project: Path, capsys):
    target = "Assets/Scripts/DamageSystem.cs"
    assert (
        main(["--root", str(unity_project), "agents", "--summary", f"{target}=Applies damage."])
        == 0
    )
    capsys.readouterr()

    assert main(
        [
            "--root",
            str(unity_project),
            "agents",
            "--dry-run",
            "--remove-summary",
            target,
        ]
    ) == 0
    assert (unity_project / SUMMARY_FILE).exists()

    assert main(["--root", str(unity_project), "agents", "--remove-summary", target]) == 0
    assert not (unity_project / SUMMARY_FILE).exists()
    scripts_map = (unity_project / "Assets" / "Scripts" / "AGENTS.md").read_text(encoding="utf-8")
    assert "Applies damage." not in scripts_map


def test_agents_cli_summary_dry_run_does_not_write(unity_project: Path):
    assert (
        main(
            [
                "--root",
                str(unity_project),
                "agents",
                "--dry-run",
                "--summary",
                "Assets/Scripts=Runtime scripts.",
            ]
        )
        == 0
    )
    assert not (unity_project / SUMMARY_FILE).exists()
    assert not (unity_project / "Assets" / "AGENTS.md").exists()


def test_agents_cli_rejects_unknown_summary_target(unity_project: Path, capsys):
    assert (
        main(
            [
                "--root",
                str(unity_project),
                "agents",
                "--summary",
                "Assets/Missing=Does not exist.",
            ]
        )
        == 1
    )
    assert "Summary target is not present" in capsys.readouterr().out
    assert not (unity_project / SUMMARY_FILE).exists()


def test_agents_cli_does_not_overwrite_invalid_summary_store(unity_project: Path, capsys):
    store = unity_project / SUMMARY_FILE
    store.write_text("{invalid", encoding="utf-8")

    assert main(["--root", str(unity_project), "agents"]) == 1
    assert f"Cannot read {SUMMARY_FILE}" in capsys.readouterr().out
    assert store.read_text(encoding="utf-8") == "{invalid"


@pytest.mark.parametrize(
    ("assignment", "message"),
    [
        ("Assets/Scripts", "PATH=TEXT"),
        ("Assets/Scripts=", "cannot be empty"),
        (f"Assets/Scripts={'x' * 241}", "cannot exceed 240"),
        (r"C:\Project\File.cs=Absolute path.", "relative to the project root"),
    ],
)
def test_agents_cli_rejects_invalid_summary_input(
    unity_project: Path,
    capsys,
    assignment: str,
    message: str,
):
    assert main(["--root", str(unity_project), "agents", "--summary", assignment]) == 1
    assert message in capsys.readouterr().out
    assert not (unity_project / SUMMARY_FILE).exists()
