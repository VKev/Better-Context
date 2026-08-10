"""Integration coverage for Roslyn-backed Unity intelligence."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from better_context.agents_map import generate_agents_map
from better_context.cli import export_graph
from better_context.orchestrator import Orchestrator

pytestmark = pytest.mark.skipif(shutil.which("dotnet") is None, reason=".NET SDK required")


@pytest.fixture
def semantic_unity_project(tmp_path: Path) -> Path:
    root = tmp_path / "SemanticUnity"
    scripts = root / "Assets" / "Scripts"
    vendor = root / "Assets" / "Plugins" / "UniRx"
    scenes = root / "Assets" / "Scenes"
    prefabs = root / "Assets" / "Prefabs"
    media = root / "Assets" / "Art" / "Icons"
    for directory in (
        scripts,
        vendor,
        scenes,
        prefabs,
        media,
        root / "Packages",
        root / "ProjectSettings",
    ):
        directory.mkdir(parents=True, exist_ok=True)
    (media / "icon.png").write_bytes(b"not-a-real-png")
    (root / "ProjectSettings" / "ProjectVersion.txt").write_text(
        "m_EditorVersion: 2022.3.62f2\n", encoding="utf-8"
    )
    (root / "ProjectSettings" / "ProjectSettings.asset").write_text(
        "  companyName: Example\n  productName: Semantic Game\n  bundleVersion: 2.0.0\n",
        encoding="utf-8",
    )
    (root / "ProjectSettings" / "EditorBuildSettings.asset").write_text(
        "- enabled: 1\n  path: Assets/Scenes/Main.unity\n", encoding="utf-8"
    )
    (root / "Packages" / "manifest.json").write_text(
        '{"dependencies":{"com.unity.test-framework":"1.1.33"}}\n', encoding="utf-8"
    )
    (scripts / "Dependency.cs").write_text(
        """namespace Fixture;
public sealed class Dependency
{
    public void Run() { }
    public static void Ping() { }
    public static int Value() => 1;
}
""",
        encoding="utf-8",
    )
    (scripts / "MarkedAttribute.cs").write_text(
        """using System;
namespace Fixture;
public sealed class MarkedAttribute : Attribute { }
""",
        encoding="utf-8",
    )
    (scripts / "BaseConsumer.cs").write_text(
        "namespace Fixture; public abstract class BaseConsumer { }\n", encoding="utf-8"
    )
    (scripts / "Box.cs").write_text(
        "namespace Fixture; public sealed class Box { public Box(int value) { } }\n",
        encoding="utf-8",
    )
    (scripts / "Amount.cs").write_text(
        """namespace Fixture;
public readonly struct Amount
{
    public int Value { get; }
    public Amount(int value) { Value = value; }
    public static Amount operator +(Amount left, Amount right) => new(left.Value + right.Value);
    public static implicit operator int(Amount value) => value.Value;
}
""",
        encoding="utf-8",
    )
    (scripts / "Consumer.cs").write_text(
        """using System;
namespace Fixture;
[Marked]
public sealed class Consumer : BaseConsumer
{
    private const string Text = "Range Dependency Marked";
    // Range and GhostType are comments, not dependencies.
    public event Action? Completed;
    public Dependency Current { get; }
    public Consumer(Dependency current) { Current = current; }
    public void Execute()
    {
        Current.Run();
        Dependency.Ping();
        _ = new Box(Dependency.Value());
        var total = new Amount(1) + new Amount(2);
        _ = (int)total;
        Completed?.Invoke();
    }
}
""",
        encoding="utf-8",
    )
    (vendor / "Range.cs").write_text(
        "namespace UniRx; public static class Range { public static void Create() { } }\n",
        encoding="utf-8",
    )
    (vendor / "SystemFragment.cs").write_text(
        "namespace System; public static class SourceMarker { }\n",
        encoding="utf-8",
    )
    (vendor / "PerformanceTest.cs").write_text(
        "namespace UniRx; public sealed class PerformanceTest { }\n",
        encoding="utf-8",
    )
    (root / "Assets" / "System.meta").write_text(
        "fileFormatVersion: 2\nguid: aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\n", encoding="utf-8"
    )
    prefab_guid = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
    (prefabs / "Actor.prefab").write_text("%YAML 1.1\n--- !u!1 &1\nGameObject:\n", encoding="utf-8")
    (prefabs / "Actor.prefab.meta").write_text(
        f"fileFormatVersion: 2\nguid: {prefab_guid}\n", encoding="utf-8"
    )
    (scenes / "Main.unity").write_text(
        f"%YAML 1.1\n--- !u!1 &1\n  m_SourcePrefab: {{fileID: 1, guid: {prefab_guid}, type: 3}}\n",
        encoding="utf-8",
    )
    return root


def test_roslyn_filters_false_positives_and_extracts_public_surface(
    semantic_unity_project: Path,
):
    result = Orchestrator(semantic_unity_project).analyze()
    edges = set(result.graph.get_all_edges())
    consumer = "Assets/Scripts/Consumer.cs"

    assert (consumer, "Assets/Scripts/Dependency.cs") in edges
    assert (consumer, "Assets/Scripts/MarkedAttribute.cs") in edges
    assert (consumer, "Assets/Scripts/BaseConsumer.cs") in edges
    assert not any(source.endswith(".cs") and target.endswith(".meta") for source, target in edges)
    assert (consumer, "Assets/Plugins/UniRx/Range.cs") not in edges
    assert (consumer, "Assets/Plugins/UniRx/SystemFragment.cs") not in edges
    dependency_detail = next(
        item
        for item in result.manifest.graph.edge_details
        if item["source"] == consumer and item["target"] == "Assets/Scripts/Dependency.cs"
    )
    assert "call" in dependency_detail["kinds"]
    assert "construct" not in dependency_detail["kinds"]

    amount = next(entry for entry in result.manifest.files if entry.path.endswith("Amount.cs"))
    assert sum(chunk.type == "operator" for chunk in amount.chunks) == 2
    consumer_entry = next(entry for entry in result.manifest.files if entry.path == consumer)
    assert any(
        chunk.type == "event" and chunk.name == "Completed" for chunk in consumer_entry.chunks
    )
    assert all(chunk.semantic_anchor for chunk in consumer_entry.chunks)

    call_names = {item["calleeName"] for item in result.manifest.graph.call_graph}
    assert any("Dependency.Run" in name for name in call_names)
    assert any("Dependency.Ping" in name for name in call_names)
    assert any("operator +" in name for name in call_names)


def test_unity_guid_edges_and_rich_agents_map(semantic_unity_project: Path):
    orchestrator = Orchestrator(semantic_unity_project)
    result = orchestrator.analyze()
    assert result.graph.has_edge(
        "Assets/Scenes/Main.unity",
        "Assets/Prefabs/Actor.prefab",
    )
    generated = generate_agents_map(result.manifest, result.graph, semantic_unity_project)
    assert not generated.errors

    root_map = (semantic_unity_project / "AGENTS.md").read_text(encoding="utf-8")
    scripts_map = (semantic_unity_project / "Assets" / "Scripts" / "AGENTS.md").read_text(
        encoding="utf-8"
    )
    assets_map = (semantic_unity_project / "Assets" / "AGENTS.md").read_text(encoding="utf-8")
    for heading in (
        "Project overview",
        "Key files (PageRank)",
        "Architecture layers",
        "Metrics",
        "Circular dependencies",
        "Observed feature flow",
        "Ownership boundaries",
        "Testing and change rules",
        "Focus and token controls",
    ):
        assert heading in root_map
    assert "Dependency.cs" in scripts_map
    assert "MarkedAttribute.cs" in scripts_map
    assert "Ca/Ce/I/A/D" in scripts_map
    assert "@" in scripts_map
    assert "Never treated as C# dependencies" in assets_map
    assert "Semantic Game" in root_map
    assert "Scene assets: 1 total, 1 project-owned, 1 enabled" in root_map
    assert "implements `Execute`" in scripts_map
    assert "No project test file was detected" in root_map
    assert (semantic_unity_project / "Assets" / "Plugins" / "AGENTS.md").is_file()
    assert not (semantic_unity_project / "Assets" / "Plugins" / "UniRx" / "AGENTS.md").exists()
    art_map = (
        semantic_unity_project / "Assets" / "Art" / "Icons" / "AGENTS.md"
    ).read_text(encoding="utf-8")
    assert "Path-only navigation" in art_map
    assert "Unity runtime assets" not in art_map
    prefab_map = (
        semantic_unity_project / "Assets" / "Prefabs" / "AGENTS.md"
    ).read_text(encoding="utf-8")
    assert "[`Actor.prefab`](Actor.prefab)" in prefab_map


def test_manifest_records_exact_edge_evidence(semantic_unity_project: Path):
    manifest = Orchestrator(semantic_unity_project).analyze().manifest
    detail = next(
        item
        for item in manifest.graph.edge_details
        if item["source"] == "Assets/Scripts/Consumer.cs"
        and item["target"] == "Assets/Scripts/Dependency.cs"
    )
    assert detail["engine"] == "roslyn"
    assert detail["confidence"] == "exact"
    assert {"call", "type"} & set(detail["kinds"])
    assert any("Dependency" in symbol for symbol in detail["symbols"])
    call_graph = json.loads(export_graph(manifest, "json", "call"))
    assert call_graph["calls"]
    assert any("Dependency.Run" in name for name in call_graph["nodes"].values())
