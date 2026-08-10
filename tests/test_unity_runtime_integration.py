"""End-to-end coverage for Unity runtime assets in the main analysis pipeline."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from better_context.orchestrator import Orchestrator, _merge_edge_details
from better_context.scanner import walk_repository

pytestmark = pytest.mark.skipif(shutil.which("dotnet") is None, reason=".NET SDK required")


@pytest.fixture
def runtime_unity_project(tmp_path: Path) -> Path:
    root = tmp_path / "RuntimeUnity"
    scripts = root / "Assets" / "Scripts"
    prefabs = root / "Assets" / "Prefabs"
    data = root / "Assets" / "Data"
    animators = root / "Assets" / "Animators"
    for directory in (
        scripts,
        prefabs,
        data,
        animators,
        root / "Packages",
        root / "ProjectSettings",
    ):
        directory.mkdir(parents=True, exist_ok=True)

    (root / "ProjectSettings" / "ProjectVersion.txt").write_text(
        "m_EditorVersion: 2022.3.62f2\n", encoding="utf-8"
    )
    (root / "Packages" / "manifest.json").write_text(
        '{"dependencies":{}}\n', encoding="utf-8"
    )

    view_guid = "11111111111111111111111111111111"
    config_guid = "22222222222222222222222222222222"
    (scripts / "Presentation.cs").write_text(
        """using UnityEngine;
namespace Game.UI;
public sealed class ShopView : MonoBehaviour
{
    public void SwitchGun() { }
}
""",
        encoding="utf-8",
    )
    (scripts / "Presentation.cs.meta").write_text(
        f"fileFormatVersion: 2\nguid: {view_guid}\n", encoding="utf-8"
    )
    (scripts / "ConfigTypes.cs").write_text(
        """using UnityEngine;
namespace Game.Data;
public sealed class GameConfigSO : ScriptableObject { }
""",
        encoding="utf-8",
    )
    (scripts / "ConfigTypes.cs.meta").write_text(
        f"fileFormatVersion: 2\nguid: {config_guid}\n", encoding="utf-8"
    )

    (prefabs / "Shop.prefab").write_text(
        f"""%YAML 1.1
--- !u!1 &1
GameObject:
  m_Component:
  - component: {{fileID: 4}}
  - component: {{fileID: 114}}
  m_Layer: 5
  m_Name: Shop
  m_TagString: Untagged
  m_IsActive: 1
--- !u!4 &4
Transform:
  m_GameObject: {{fileID: 1}}
  m_Father: {{fileID: 0}}
--- !u!114 &114
MonoBehaviour:
  m_GameObject: {{fileID: 1}}
  m_Script: {{fileID: 11500000, guid: {view_guid}, type: 3}}
  onClick:
    m_PersistentCalls:
      m_Calls:
      - m_Target: {{fileID: 114}}
        m_TargetAssemblyTypeName: Game.UI.ShopView, Assembly-CSharp
        m_MethodName: SwitchGun
        m_Mode: 1
        m_CallState: 2
  fakeText: "guid: ffffffffffffffffffffffffffffffff"
""",
        encoding="utf-8",
    )

    (data / "GameConfig.asset").write_text(
        f"""%YAML 1.1
--- !u!114 &11400000
MonoBehaviour:
  m_Script: {{fileID: 11500000, guid: {config_guid}, type: 3}}
  m_Name: GameConfig
""",
        encoding="utf-8",
    )

    (animators / "Shop.controller").write_text(
        """%YAML 1.1
--- !u!1102 &10
AnimatorState:
  m_Name: Idle
  m_Speed: 1
  m_Transitions: []
  m_Motion: {fileID: 0}
--- !u!1107 &20
AnimatorStateMachine:
  m_ChildStates:
  - m_State: {fileID: 10}
  m_DefaultState: {fileID: 10}
--- !u!91 &9100000
AnimatorController:
  m_Name: Shop
  m_AnimatorParameters:
  - m_Name: Open
    m_Type: 4
  m_AnimatorLayers:
  - m_Name: Base Layer
    m_StateMachine: {fileID: 20}
""",
        encoding="utf-8",
    )
    return root


def test_orchestrator_enriches_manifest_and_graph(runtime_unity_project: Path):
    result = Orchestrator(runtime_unity_project).analyze()
    manifest = result.manifest

    runtime = manifest.project["unity_runtime"]
    assert runtime["metrics"]["prefabs"] == 1
    assert runtime["metrics"]["scriptable_objects"] == 1
    assert runtime["metrics"]["animator_controllers"] == 1
    assert runtime["metrics"]["event_bindings"] == 1

    by_path = {entry.path: entry for entry in manifest.files}
    prefab = by_path["Assets/Prefabs/Shop.prefab"].metadata["unity_runtime"]
    assert prefab["kind"] == "prefab"
    assert prefab["root_objects"][0]["name"] == "Shop"
    assert "Game.UI.ShopView" in prefab["script_types"]

    data = by_path["Assets/Data/GameConfig.asset"].metadata["unity_runtime"]
    assert data["scriptable_object"]["type"] == "Game.Data.GameConfigSO"

    edges = set(manifest.graph.edges)
    assert ("Assets/Prefabs/Shop.prefab", "Assets/Scripts/Presentation.cs") in edges
    assert ("Assets/Data/GameConfig.asset", "Assets/Scripts/ConfigTypes.cs") in edges
    assert not any(target.endswith(".meta") for _, target in edges)
    assert len(manifest.graph.edge_details) == len(edges)
    assert any(item.get("kind") == "unity_event" for item in manifest.graph.call_graph)
    graph_nodes = set(manifest.graph.nodes)
    assert all(
        call["source"] in graph_nodes and call["target"] in graph_nodes
        for call in manifest.graph.call_graph
    )


def test_scanner_keeps_oversized_streamed_unity_assets(tmp_path: Path) -> None:
    scene = tmp_path / "Assets" / "Large.unity"
    scene.parent.mkdir(parents=True)
    scene.write_text(
        "%YAML 1.1\n--- !u!1 &1\nGameObject:\n  m_Name: Large\n" + ("# padding\n" * 300),
        encoding="utf-8",
    )
    (tmp_path / "Large.txt").write_text("plain\n" * 500, encoding="utf-8")

    inventory = walk_repository(tmp_path, max_file_size_kb=1)
    paths = {item.path for item in inventory.files}

    assert "Assets/Large.unity" in paths
    assert "Assets/Large.unity" not in inventory.skipped_too_large
    assert "Large.txt" in inventory.skipped_too_large


def test_edge_detail_merge_preserves_runtime_evidence_and_provenance() -> None:
    details = _merge_edge_details(
        [
            {
                "source": "Assets/A.prefab",
                "target": "Assets/B.cs",
                "kinds": ["import"],
                "symbols": [],
                "lines": [],
                "confidence": "resolved",
                "engine": "language-adapter",
            },
            {
                "source": "Assets/A.prefab",
                "target": "Assets/B.cs",
                "kinds": ["unity_component"],
                "symbols": ["m_Script"],
                "lines": [12],
                "confidence": "exact",
                "engine": "unity-runtime",
                "evidence": [{"field": "m_Script", "guid": "a" * 32}],
            },
        ]
    )

    assert details[0]["engine"] == "mixed"
    assert details[0]["engines"] == ["language-adapter", "unity-runtime"]
    assert details[0]["evidence"] == [{"field": "m_Script", "guid": "a" * 32}]
