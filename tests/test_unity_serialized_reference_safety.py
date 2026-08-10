"""Compatibility checks for the legacy Unity serialized-reference helper."""

from __future__ import annotations

from types import SimpleNamespace

from better_context.unity_intelligence import collect_serialized_reference_edges


def test_serialized_reference_helper_ignores_free_text_guid(tmp_path):
    guid = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    script = tmp_path / "Target.cs"
    script.write_text("public sealed class Target {}\n", encoding="utf-8")
    meta = tmp_path / "Target.cs.meta"
    meta.write_text(f"fileFormatVersion: 2\nguid: {guid}\n", encoding="utf-8")
    prefab = tmp_path / "Actor.prefab"
    prefab.write_text(
        "\n".join(
            [
                "%YAML 1.1",
                "--- !u!114 &1",
                "MonoBehaviour:",
                f'  note: "{{fileID: 11500000, guid: {guid}, type: 3}}"',
                f"  m_Script: {{fileID: 11500000, guid: {guid}, type: 3}}",
            ]
        ),
        encoding="utf-8",
    )
    inventory = SimpleNamespace(
        files=[
            SimpleNamespace(path="Target.cs", absolute_path=script),
            SimpleNamespace(path="Target.cs.meta", absolute_path=meta),
            SimpleNamespace(path="Actor.prefab", absolute_path=prefab),
        ]
    )

    edges = collect_serialized_reference_edges(inventory)

    assert len(edges) == 1
    assert edges[0]["source"] == "Actor.prefab"
    assert edges[0]["target"] == "Target.cs"
    assert edges[0]["lines"] == [5]
