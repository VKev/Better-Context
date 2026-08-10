"""Ground-truth fixtures for structured Unity runtime serialization."""

from __future__ import annotations

from pathlib import Path

from better_context.manifest import ChunkEntry, FileEntry
from better_context.scanner import FileInfo, FileInventory
from better_context.unity_runtime import analyze_unity_runtime

SCRIPT_GUID = "11111111111111111111111111111111"
CONFIG_GUID = "22222222222222222222222222222222"
PREFAB_GUID = "33333333333333333333333333333333"
CLIP_GUID = "44444444444444444444444444444444"
AMBIGUOUS_GUID = "55555555555555555555555555555555"


def _write(root: Path, relative: str, content: str | bytes) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, bytes):
        path.write_bytes(content)
    else:
        path.write_text(content, encoding="utf-8")


def _meta(root: Path, relative: str, guid: str) -> None:
    _write(root, f"{relative}.meta", f"fileFormatVersion: 2\nguid: {guid}\n")


def _inventory(root: Path) -> FileInventory:
    files = []
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        relative = path.relative_to(root).as_posix()
        files.append(
            FileInfo(
                path=relative,
                absolute_path=path,
                size_bytes=path.stat().st_size,
                extension=path.suffix.lower(),
                language="csharp" if path.suffix.lower() == ".cs" else None,
                content_hash="fixture",
                mtime=0,
                is_binary=b"\x00" in path.read_bytes()[:100],
            )
        )
    return FileInventory(root=root, files=files)


def _chunk(
    path: str,
    chunk_id: str,
    kind: str,
    name: str,
    parent: str | None = None,
    unity_type: str = "",
    qualified_name: str = "",
) -> ChunkEntry:
    return ChunkEntry(
        id=chunk_id,
        type=kind,
        name=name,
        signature=name,
        start_line=1,
        end_line=2,
        parent=parent,
        exported=True,
        metadata={
            "analysis_engine": "roslyn",
            "unity_type": unity_type or None,
            "qualified_name": qualified_name,
        },
    )


def _file_entry(path: str, chunks: list[ChunkEntry]) -> FileEntry:
    return FileEntry(
        path=path,
        language="csharp" if path.endswith(".cs") else "",
        size_bytes=1,
        hash="fixture",
        chunks=chunks,
        metadata={"ownership": "project-owned"},
    )


def _script_entries() -> list[FileEntry]:
    controller_type = _chunk(
        "Assets/Scripts/NotControllerFilename.cs",
        "controller-type",
        "class",
        "Controller",
        unity_type="MonoBehaviour",
        qualified_name="Game.UI.Controller",
    )
    pressed = _chunk(
        "Assets/Scripts/NotControllerFilename.cs",
        "pressed-method",
        "method",
        "OnPressed",
        parent="controller-type",
        qualified_name="Game.UI.Controller.OnPressed()",
    )
    config = _chunk(
        "Assets/Scripts/DataDefinition.cs",
        "config-type",
        "class",
        "GameConfig",
        unity_type="ScriptableObject",
        qualified_name="Game.Data.GameConfig",
    )
    abstract_config = _chunk(
        "Assets/Scripts/DataDefinition.cs",
        "abstract-config-type",
        "class",
        "RemoteConfigBase",
        unity_type="ScriptableObject",
        qualified_name="Game.Data.RemoteConfigBase",
    )
    abstract_config.metadata["is_abstract"] = True
    abstract_config.metadata["abstract"] = True
    return [
        _file_entry("Assets/Scripts/NotControllerFilename.cs", [controller_type, pressed]),
        _file_entry("Assets/Scripts/DataDefinition.cs", [config, abstract_config]),
    ]


def test_hierarchy_roslyn_scriptable_object_and_event_binding(tmp_path: Path) -> None:
    root = tmp_path / "Unity"
    _write(root, "Assets/Scripts/NotControllerFilename.cs", "// parsed by Roslyn\n")
    _meta(root, "Assets/Scripts/NotControllerFilename.cs", SCRIPT_GUID)
    _write(root, "Assets/Scripts/DataDefinition.cs", "// parsed by Roslyn\n")
    _meta(root, "Assets/Scripts/DataDefinition.cs", CONFIG_GUID)
    _write(
        root,
        "Assets/Prefabs/Button.prefab",
        f"""%YAML 1.1
--- !u!1 &1
GameObject:
  m_Component:
  - component: {{fileID: 4}}
  - component: {{fileID: 10}}
  - component: {{fileID: 11}}
  m_Layer: 5
  m_Name: Root
  m_TagString: UI
  m_IsActive: 1
--- !u!4 &4
Transform:
  m_GameObject: {{fileID: 1}}
  m_Children:
  - {{fileID: 5}}
  - {{fileID: 6}}
  m_Father: {{fileID: 0}}
--- !u!1 &2
GameObject:
  m_Component:
  - component: {{fileID: 5}}
  m_Name: Child
  m_IsActive: 0
--- !u!4 &5
Transform:
  m_GameObject: {{fileID: 2}}
  m_Children: []
  m_Father: {{fileID: 4}}
--- !u!1 &3
GameObject:
  m_Component:
  - component: {{fileID: 6}}
  m_Name: Child
  m_IsActive: 1
--- !u!4 &6
Transform:
  m_GameObject: {{fileID: 3}}
  m_Children: []
  m_Father: {{fileID: 4}}
--- !u!114 &10
MonoBehaviour:
  m_GameObject: {{fileID: 1}}
  m_Script: {{fileID: 11500000, guid: {SCRIPT_GUID}, type: 3}}
--- !u!114 &11
MonoBehaviour:
  m_GameObject: {{fileID: 1}}
  m_Script: {{fileID: 11500000, guid: {SCRIPT_GUID}, type: 3}}
  unrelated:
  - m_Target: {{fileID: 10}}
    m_MethodName: MustNotBecomeAnEvent
  m_OnClick:
    m_PersistentCalls:
      m_Calls:
      - m_Target: {{fileID: 10}}
        m_TargetAssemblyTypeName: Game.UI.Controller, Assembly-CSharp
        m_MethodName: OnPressed
        m_Mode: 1
        m_CallState: 2
      - m_Target: {{fileID: 0}}
        m_MethodName: 0
  note: "guid: {PREFAB_GUID}"
  # guid: {PREFAB_GUID}
""",
    )
    _meta(root, "Assets/Prefabs/Button.prefab", PREFAB_GUID)
    _write(
        root,
        "Assets/Data/GameConfig.asset",
        f"""%YAML 1.1
--- !u!114 &11400000
MonoBehaviour:
  m_GameObject: {{fileID: 0}}
  m_Script: {{fileID: 11500000, guid: {CONFIG_GUID}, type: 3}}
  m_Name: ProductionConfig
""",
    )
    _write(
        root,
        "Assets/Data/NotScriptable.asset",
        f"""--- !u!114 &11400000
MonoBehaviour:
  m_Script: {{fileID: 11500000, guid: {SCRIPT_GUID}, type: 3}}
  m_Name: NotScriptable
""",
    )
    _write(
        root,
        "Assets/Scenes/Main.unity",
        """--- !u!1 &100
GameObject:
  m_Component:
  - component: {fileID: 101}
  m_Name: SceneRoot
--- !u!114 &101
MonoBehaviour:
  m_GameObject: {fileID: 100}
  m_Script: {fileID: 11500000, guid: 99999999999999999999999999999999, type: 3}
""",
    )

    result = analyze_unity_runtime(root, _inventory(root), _script_entries())
    prefab = result.assets["Assets/Prefabs/Button.prefab"]
    children = [item for item in prefab["objects"] if item["name"] == "Child"]

    assert len(children) == 2
    assert [item["path"] for item in children] == ["Root/Child", "Root/Child"]
    assert any(item["active"] is False for item in children)
    assert prefab["root_objects"][0]["name"] == "Root"
    assert prefab["script_types"] == ["Game.UI.Controller"]
    assert len(prefab["event_bindings"]) == 1
    assert prefab["event_bindings"][0]["method"] == "OnPressed"
    assert prefab["event_bindings"][0]["owner_object"] == "Root"
    assert prefab["event_bindings"][0]["status"] == "exact"
    assert len(result.call_graph) == 1
    assert result.call_graph[0]["calleeId"] == "pressed-method"

    config = result.assets["Assets/Data/GameConfig.asset"]
    assert config["kind"] == "scriptable_object"
    assert config["scriptable_object"] == {
        "name": "ProductionConfig",
        "type": "Game.Data.GameConfig",
        "script_path": "Assets/Scripts/DataDefinition.cs",
        "confidence": "exact",
    }
    edge = next(
        item
        for item in result.edge_details
        if item["source"] == "Assets/Data/GameConfig.asset"
    )
    assert "scriptable_object_type" in edge["kinds"]
    assert result.assets["Assets/Data/NotScriptable.asset"]["kind"] == "asset"
    assert "scriptable_object" not in result.assets["Assets/Data/NotScriptable.asset"]
    missing = result.assets["Assets/Scenes/Main.unity"]["objects"][0]["components"][0]["script"]
    assert missing["confidence"] == "unresolved"
    assert missing["reason"] == "guid_not_in_inventory"
    assert result.summary["metrics"]["scenes"] == 1
    assert all(not item["target"].endswith(".meta") for item in result.edge_details)
    assert not any(item["target"] == "Assets/Prefabs/Button.prefab" for item in result.edge_details)
    assert result.summary["engine"] == "unity-yaml-stdlib"
    assert result.summary["metrics"]["event_bindings"] == 1
    assert result.summary["event_bindings"][0]["method"] == "OnPressed"


def test_script_guid_collision_and_multiple_roslyn_types_are_not_guessed(tmp_path: Path) -> None:
    root = tmp_path / "Unity"
    for name in ("One.cs", "Two.cs"):
        _write(root, f"Assets/Scripts/{name}", "// fixture\n")
        _meta(root, f"Assets/Scripts/{name}", AMBIGUOUS_GUID)
    _write(
        root,
        "Assets/Prefabs/Ambiguous.prefab",
        f"""--- !u!1 &1
GameObject:
  m_Component:
  - component: {{fileID: 10}}
  m_Name: Ambiguous
--- !u!114 &10
MonoBehaviour:
  m_GameObject: {{fileID: 1}}
  m_Script: {{fileID: 11500000, guid: {AMBIGUOUS_GUID}, type: 3}}
""",
    )
    entries = []
    for index, name in enumerate(("One.cs", "Two.cs"), start=1):
        chunk = _chunk(
            f"Assets/Scripts/{name}",
            f"type-{index}",
            "class",
            "SameName",
            unity_type="MonoBehaviour",
            qualified_name=f"Namespace{index}.SameName",
        )
        entries.append(_file_entry(f"Assets/Scripts/{name}", [chunk]))

    result = analyze_unity_runtime(root, _inventory(root), entries)
    script = result.assets["Assets/Prefabs/Ambiguous.prefab"]["objects"][0]["components"][0][
        "script"
    ]

    assert script["confidence"] == "partial"
    assert script["reason"] == "duplicate_guid"
    assert set(script["candidates"]) == {
        "Assets/Scripts/One.cs",
        "Assets/Scripts/Two.cs",
    }
    assert result.edge_details == []

    # A unique GUID still cannot select between two Roslyn-confirmed Unity
    # types declared in the same source file.
    _meta(root, "Assets/Scripts/One.cs", SCRIPT_GUID)
    source = (root / "Assets/Prefabs/Ambiguous.prefab").read_text(encoding="utf-8")
    (root / "Assets/Prefabs/Ambiguous.prefab").write_text(
        source.replace(AMBIGUOUS_GUID, SCRIPT_GUID), encoding="utf-8"
    )
    two_types = [
        _chunk(
            "Assets/Scripts/One.cs",
            f"multi-{index}",
            "class",
            name,
            unity_type="MonoBehaviour",
            qualified_name=f"Fixture.{name}",
        )
        for index, name in enumerate(("First", "Second"))
    ]
    result = analyze_unity_runtime(
        root,
        _inventory(root),
        [_file_entry("Assets/Scripts/One.cs", two_types)],
    )
    script = result.assets["Assets/Prefabs/Ambiguous.prefab"]["objects"][0]["components"][0][
        "script"
    ]
    assert script["confidence"] == "partial"
    assert script["reason"] == "ambiguous_roslyn_unity_types"


def test_unity_event_overload_is_partial_and_not_a_call_edge(tmp_path: Path) -> None:
    root = tmp_path / "Unity"
    overload_guid = "66666666666666666666666666666666"
    _write(root, "Assets/Scripts/Receiver.cs", "// Roslyn fixture\n")
    _meta(root, "Assets/Scripts/Receiver.cs", overload_guid)
    _write(
        root,
        "Assets/Prefabs/Overloaded.prefab",
        f"""--- !u!1 &1
GameObject:
  m_Component:
  - component: {{fileID: 10}}
  - component: {{fileID: 11}}
  m_Name: Overloaded
--- !u!114 &10
MonoBehaviour:
  m_GameObject: {{fileID: 1}}
  m_Script: {{fileID: 11500000, guid: {overload_guid}, type: 3}}
--- !u!114 &11
MonoBehaviour:
  m_GameObject: {{fileID: 1}}
  m_OnClick:
    m_PersistentCalls:
      m_Calls:
      - m_Target: {{fileID: 10}}
        m_TargetAssemblyTypeName: Receiver, Assembly-CSharp
        m_MethodName: Receive
        m_Mode: 1
""",
    )
    receiver = _chunk(
        "Assets/Scripts/Receiver.cs",
        "receiver-type",
        "class",
        "Receiver",
        unity_type="MonoBehaviour",
        qualified_name="Receiver",
    )
    methods = [
        _chunk(
            "Assets/Scripts/Receiver.cs",
            f"receive-{index}",
            "method",
            "Receive",
            parent="receiver-type",
            qualified_name=f"Receiver.Receive({argument})",
        )
        for index, argument in enumerate(("int", "string"))
    ]

    result = analyze_unity_runtime(
        root,
        _inventory(root),
        [_file_entry("Assets/Scripts/Receiver.cs", [receiver, *methods])],
    )
    binding = result.assets["Assets/Prefabs/Overloaded.prefab"]["event_bindings"][0]

    assert binding["confidence"] == "partial"
    assert binding["reason"] == "ambiguous_method_overload"
    assert result.call_graph == []
    assert not any("unity_event" in edge["kinds"] for edge in result.edge_details)


def test_external_unity_event_target_and_disabled_call_state(tmp_path: Path) -> None:
    root = tmp_path / "Unity"
    external_script_guid = "88888888888888888888888888888888"
    target_asset_guid = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    _write(root, "Assets/Scripts/ExternalReceiver.cs", "// Roslyn fixture\n")
    _meta(root, "Assets/Scripts/ExternalReceiver.cs", external_script_guid)
    _write(
        root,
        "Assets/Data/Receiver.asset",
        f"""--- !u!114 &11400000
MonoBehaviour:
  m_Script: {{fileID: 11500000, guid: {external_script_guid}, type: 3}}
  m_Name: Receiver
""",
    )
    _meta(root, "Assets/Data/Receiver.asset", target_asset_guid)
    _write(
        root,
        "Assets/Prefabs/ExternalEvent.prefab",
        f"""--- !u!1 &1
GameObject:
  m_Component:
  - component: {{fileID: 11}}
  m_Name: EventOwner
--- !u!114 &11
MonoBehaviour:
  m_GameObject: {{fileID: 1}}
  m_EnabledEvent:
    m_PersistentCalls:
      m_Calls:
      - m_Target: {{fileID: 11400000, guid: {target_asset_guid},
          type: 2}}
        m_TargetAssemblyTypeName: Game.ExternalReceiver, Assembly-CSharp
        m_MethodName: Receive
        m_Mode: 1
        m_CallState: 2
  m_DisabledEvent:
    m_PersistentCalls:
      m_Calls:
      - m_Target: {{fileID: 11400000, guid: {target_asset_guid}, type: 2}}
        m_TargetAssemblyTypeName: Game.ExternalReceiver, Assembly-CSharp
        m_MethodName: Receive
        m_Mode: 1
        m_CallState: 0
""",
    )
    receiver = _chunk(
        "Assets/Scripts/ExternalReceiver.cs",
        "external-type",
        "class",
        "ExternalReceiver",
        unity_type="ScriptableObject",
        qualified_name="Game.ExternalReceiver",
    )
    method = _chunk(
        "Assets/Scripts/ExternalReceiver.cs",
        "external-method",
        "method",
        "Receive",
        parent="external-type",
        qualified_name="Game.ExternalReceiver.Receive()",
    )

    result = analyze_unity_runtime(
        root,
        _inventory(root),
        [_file_entry("Assets/Scripts/ExternalReceiver.cs", [receiver, method])],
    )
    bindings = result.assets["Assets/Prefabs/ExternalEvent.prefab"]["event_bindings"]

    assert len(bindings) == 2
    assert {item["target_asset"] for item in bindings} == {"Assets/Data/Receiver.asset"}
    assert {item["confidence"] for item in bindings} == {"exact"}
    assert {item["status"] for item in bindings} == {"exact", "disabled"}
    assert len(result.call_graph) == 1
    assert result.call_graph[0]["calleeId"] == "external-method"
    event_edges = [item for item in result.edge_details if "unity_event" in item["kinds"]]
    assert len(event_edges) == 1
    assert event_edges[0]["target"] == "Assets/Scripts/ExternalReceiver.cs"


def test_animator_and_nested_prefab_instance(tmp_path: Path) -> None:
    root = tmp_path / "Unity"
    behaviour_guid = "77777777777777777777777777777777"
    _write(root, "Assets/Scripts/AttackBehaviour.cs", "// Roslyn fixture\n")
    _meta(root, "Assets/Scripts/AttackBehaviour.cs", behaviour_guid)
    _write(root, "Assets/Prefabs/Base.prefab", "--- !u!1 &1\nGameObject:\n  m_Name: Base\n")
    _meta(root, "Assets/Prefabs/Base.prefab", PREFAB_GUID)
    _write(root, "Assets/Animations/Run.anim", "--- !u!74 &7400000\nAnimationClip:\n")
    _meta(root, "Assets/Animations/Run.anim", CLIP_GUID)
    _write(
        root,
        "Assets/Prefabs/Variant.prefab",
        f"""--- !u!1001 &1001
PrefabInstance:
  m_Modification:
    m_TransformParent: {{fileID: 0}}
    m_Modifications:
    - target: {{fileID: 1, guid: {PREFAB_GUID}, type: 3}}
      propertyPath: m_Name
      value: Variant
  m_SourcePrefab: {{fileID: 100100000, guid: {PREFAB_GUID}, type: 3}}
--- !u!1 &20 stripped
GameObject:
  m_CorrespondingSourceObject: {{fileID: 1, guid: {PREFAB_GUID}, type: 3}}
  m_PrefabInstance: {{fileID: 1001}}
""",
    )
    _write(
        root,
        "Assets/Anim/Controller.controller",
        f"""--- !u!206 &206
BlendTree:
  m_Name: Locomotion
  m_Childs:
  - serializedVersion: 2
    m_Motion: {{fileID: 7400000, guid: {CLIP_GUID},
      type: 2}}
    m_Threshold: 0
    m_DirectBlendParameter: Speed
  m_BlendParameter: Speed
--- !u!1101 &1101
AnimatorStateTransition:
  m_Conditions:
  - m_ConditionMode: 1
    m_ConditionEvent: Moving
    m_EventTreshold: 0
  m_DstState: {{fileID: 1102}}
  m_TransitionDuration: 0.25
  m_ExitTime: 0.75
  m_HasExitTime: 1
--- !u!1107 &1107
AnimatorStateMachine:
  m_AnyStateTransitions:
  - {{fileID: 1103}}
  m_EntryTransitions:
  - {{fileID: 1104}}
  m_DefaultState: {{fileID: 1102}}
--- !u!1102 &1102
AnimatorState:
  m_Name: Run
  m_Transitions:
  - {{fileID: 1101}}
  - {{fileID: 1105}}
  m_StateMachineBehaviours:
  - {{fileID: 11401}}
  m_Motion: {{fileID: 206}}
--- !u!114 &11401
MonoBehaviour:
  m_Script: {{fileID: 11500000, guid: {behaviour_guid}, type: 3}}
--- !u!1101 &1103
AnimatorStateTransition:
  m_Conditions: []
  m_DstState: {{fileID: 1102}}
  m_IsExit: 0
--- !u!1101 &1104
AnimatorStateTransition:
  m_Conditions: []
  m_DstState: {{fileID: 1102}}
  m_IsExit: 0
--- !u!1101 &1105
AnimatorStateTransition:
  m_Conditions: []
  m_DstState: {{fileID: 0}}
  m_IsExit: 1
--- !u!91 &9100000
AnimatorController:
  m_Name: Controller
  m_AnimatorParameters:
  - m_Name: Speed
    m_Type: 1
    m_DefaultFloat: 0
  - m_Name: Moving
    m_Type: 4
    m_DefaultBool: 0
  m_AnimatorLayers:
  - m_Name: Base Layer
    m_StateMachine: {{fileID: 1107}}
  - m_Name: Upper Body
    m_StateMachine: {{fileID: 1107}}
""",
    )

    behaviour = _chunk(
        "Assets/Scripts/AttackBehaviour.cs",
        "behaviour-type",
        "class",
        "AttackBehaviour",
        unity_type="StateMachineBehaviour",
        qualified_name="Game.Animation.AttackBehaviour",
    )
    result = analyze_unity_runtime(
        root,
        _inventory(root),
        [_file_entry("Assets/Scripts/AttackBehaviour.cs", [behaviour])],
    )
    variant = result.assets["Assets/Prefabs/Variant.prefab"]
    instance = variant["prefab_instances"][0]
    assert instance["source_prefab"]["path"] == "Assets/Prefabs/Base.prefab"
    assert instance["source_prefab"]["confidence"] == "exact"
    assert instance["modification_count"] == 1
    assert instance["stripped_refs"][0]["file_id"] == "20"

    animator = result.assets["Assets/Anim/Controller.controller"]["animator"]
    assert animator["parameters"] == [
        {"name": "Speed", "type": "float", "default": "0"},
        {"name": "Moving", "type": "bool", "default": False},
    ]
    assert len(animator["layers"]) == 2
    assert {item["default_state_file_id"] for item in animator["layers"]} == {"1102"}
    assert animator["states"][0]["motion"]["local_type"] == "BlendTree"
    assert animator["states"][0]["behaviours"][0]["type"] == "AttackBehaviour"
    transitions = {item["file_id"]: item for item in animator["transitions"]}
    assert transitions["1101"]["source_state_file_id"] == "1102"
    assert transitions["1101"]["conditions"][0]["parameter"] == "Moving"
    assert transitions["1103"]["source_state_file_id"] == "AnyState:1107"
    assert transitions["1104"]["source_state_file_id"] == "Entry:1107"
    assert transitions["1105"]["is_exit"] is True
    assert animator["blend_trees"][0]["children"][0]["motion"]["path"] == (
        "Assets/Animations/Run.anim"
    )
    edge = next(
        item
        for item in result.edge_details
        if item["source"] == "Assets/Anim/Controller.controller"
        and item["target"] == "Assets/Animations/Run.anim"
    )
    assert "animator_motion" in edge["kinds"]


def test_wrapped_structured_references_remain_exact(tmp_path: Path) -> None:
    root = tmp_path / "Unity"
    _write(root, "Assets/Prefabs/Target.prefab", "--- !u!1 &1\nGameObject:\n  m_Name: T\n")
    _meta(root, "Assets/Prefabs/Target.prefab", PREFAB_GUID)
    _write(
        root,
        "Assets/Prefabs/Wrapped.prefab",
        f"""--- !u!114 &114
MonoBehaviour:
  wrapped: {{fileID: 1, guid: {PREFAB_GUID},
    type: 3}}
  values:
  - {{fileID: 2, guid: {PREFAB_GUID},
    type: 3}}
  quoted: "{{fileID: 3, guid: {PREFAB_GUID}, type: 3}}"
  # comment: {{fileID: 4, guid: {PREFAB_GUID}, type: 3}}
""",
    )

    result = analyze_unity_runtime(root, _inventory(root), [])
    edge = next(
        item
        for item in result.edge_details
        if item["source"] == "Assets/Prefabs/Wrapped.prefab"
    )

    assert edge["target"] == "Assets/Prefabs/Target.prefab"
    assert edge["lines"] == [3, 6]
    assert len(edge["evidence"]) == 2


def test_binary_malformed_and_ownership_coverage(tmp_path: Path) -> None:
    root = tmp_path / "Unity"
    _write(root, "Assets/Data/Binary.asset", b"\x00\x01\x02")
    _write(root, "Assets/Data/Malformed.asset", "m_Name: no document header\n")
    _write(root, "Assets/Plugins/Vendor.prefab", "--- !u!1 &1\nGameObject:\n  m_Name: V\n")

    inventory = _inventory(root)
    inventory.files = [item for item in inventory.files if item.path != "Assets/Data/Binary.asset"]
    inventory.skipped_binary.append("Assets/Data/Binary.asset")
    result = analyze_unity_runtime(root, inventory, [])

    assert result.assets["Assets/Data/Binary.asset"]["status"] == "unsupported_serialization"
    assert result.assets["Assets/Data/Malformed.asset"]["status"] == "parse_error"
    assert [item["path"] for item in result.errors] == ["Assets/Data/Malformed.asset"]
    assert "Assets/Plugins/Vendor.prefab" not in result.assets
    coverage = result.summary["coverage"]
    assert coverage["eligible"] == 2
    assert coverage["candidates"] == 2
    assert coverage["skipped_non_owned"] == 1
    assert coverage["unsupported"] == 1
    assert coverage["failed"] == 1
    assert coverage["errors"] == 1
    assert coverage["parsed"] == 0
    assert coverage["partial"] == 0
    assert result.summary["metrics"]["event_bindings"] == 0
    assert result.summary["errors"] == result.errors
