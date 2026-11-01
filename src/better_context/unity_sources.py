"""Structured Unity source assets; binary/custom formats use Editor metadata.

Only explicit resource fields create edges, never names or arbitrary GUID strings.
"""

from __future__ import annotations

import json
import posixpath
import re
import xml.etree.ElementTree as ET
from contextlib import suppress
from pathlib import PurePosixPath
from typing import Any
from urllib.parse import parse_qs, unquote, urlsplit

SOURCE_KINDS = {
    ".shader": "shader",
    ".shadergraph": "shader",
    ".shadersubgraph": "shader",
    ".hlsl": "shader_include",
    ".cginc": "shader_include",
    ".hlslinc": "shader_include",
    ".glslinc": "shader_include",
    ".compute": "compute_shader",
    ".raytrace": "raytracing_shader",
    ".uxml": "ui_document",
    ".uss": "style_sheet",
    ".tss": "style_sheet",
    ".inputactions": "input_actions",
    ".asmdef": "assembly_definition",
    ".asmref": "assembly_reference",
}
EXTRA_ASSET_SUFFIXES = frozenset(SOURCE_KINDS) | {
    ".vfx",
    ".vfxoperator",
    ".vfxblock",
    ".spriteatlasv2",
    ".guiskin",
    ".flare",
    ".mask",
    ".preset",
    ".shadervariants",
    ".lightingdata",
    ".bytes",
    ".txt",
    ".json",
    ".xml",
    ".csv",
    ".yaml",
    ".yml",
    ".webp",
    ".ico",
    ".psb",
    ".dds",
    ".ktx",
    ".ktx2",
    ".raw",
    ".mpg",
    ".mpeg",
    ".m4v",
    ".m4a",
    ".aac",
    ".wmv",
    ".asf",
    ".woff",
    ".woff2",
    ".fnt",
    ".obj",
    ".blend",
    ".dae",
    ".3ds",
    ".gltf",
    ".glb",
    ".abc",
    ".usd",
    ".usda",
    ".usdc",
    ".usdz",
}
MAX_SOURCE_BYTES = 16 * 1024 * 1024


def strip_comments(source: str) -> str:
    """Remove C/USS comments while retaining literals and line numbers."""
    pattern = r""""(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|//[^\n]*|/\*[\s\S]*?\*/"""
    return re.sub(
        pattern,
        lambda m: re.sub(r"[^\n]", " ", m[0]) if m[0].startswith(("//", "/*")) else m[0],
        source,
    )


def reference(
    path: str,
    field: str,
    line: int,
    target: str,
    *,
    guid: str = "",
    reason: str = "structured_asset_path",
    file_id: str = "0",
) -> dict[str, Any]:
    return {
        "document_file_id": "0",
        "file_id": file_id,
        "guid": guid,
        "field": field,
        "line": line,
        "target": target,
        "confidence": "exact" if target and target != path else "unresolved",
        "reason": reason,
        "provenance": "unity-source",
        "edge_kind": "unity_source_reference",
    }


def resolve_resource(
    path: str, value: str, field: str, line: int, known_paths: set[str], guids: dict[str, list[str]]
) -> dict[str, Any]:
    """Resolve project/GUID URLs and relative paths, never by basename."""
    value = unquote(value.strip().strip("\"'"))
    parsed = urlsplit(value)
    query = parse_qs(parsed.query)
    guid = query.get("guid", [""])[0].lower()
    if parsed.scheme and parsed.scheme != "project":
        return reference(path, field, line, "", reason="external_or_builtin_resource")
    if guid:
        targets = sorted(set(guids.get(guid, [])))
        return reference(
            path,
            field,
            line,
            targets[0] if len(targets) == 1 else "",
            guid=guid,
            file_id=query.get("fileID", ["0"])[0],
            reason="structured_resource_guid",
        )
    if parsed.scheme == "project" and parsed.netloc not in {"database", ""}:
        return reference(path, field, line, "", reason="unsupported_resource_url")
    candidate = parsed.path.lstrip("/") if parsed.scheme == "project" else parsed.path
    if not candidate:
        return reference(path, field, line, "", reason="empty_resource")
    if not candidate.startswith(("Assets/", "Packages/")):
        candidate = posixpath.join(posixpath.dirname(path), candidate)
    candidate = posixpath.normpath(candidate.replace("\\", "/"))
    target = candidate if candidate in known_paths and candidate != path else ""
    return reference(path, field, line, target)


def _json_documents(source: str) -> list[dict[str, Any]]:
    """Shader Graph may be a stream of JSON objects."""
    decoder = json.JSONDecoder()
    cursor = 0
    result = []
    while cursor < len(source):
        while cursor < len(source) and source[cursor].isspace():
            cursor += 1
        if cursor == len(source):
            break
        value, cursor = decoder.raw_decode(source, cursor)
        if isinstance(value, dict):
            result.append(value)
    return result


def inspect_source_asset(
    path: str, source: str, known_paths: set[str], guids: dict[str, list[str]]
) -> dict[str, Any]:
    """Return source facts and exact/unresolved references; no compile claims."""
    suffix = PurePosixPath(path).suffix.lower()
    references: list[dict[str, Any]] = []
    facts: dict[str, Any] = {}
    if suffix == ".uxml":
        if re.search(r"<!DOCTYPE|<!ENTITY", source, re.IGNORECASE):
            raise ValueError("DTD/entity declarations are not supported in UXML.")
        try:
            tree = ET.fromstring(source)
        except ET.ParseError as error:
            raise ValueError(f"Malformed UXML: {error}") from error
        elements = []
        for element in tree.iter():
            tag = element.tag.rsplit("}", 1)[-1]
            elements.append(
                {
                    "type": tag,
                    "name": element.get("name", ""),
                    "classes": element.get("class", "").split(),
                }
            )
            for field in ("src", "texture", "sprite", "icon-image"):
                value = element.get(field)
                if value:
                    # ElementTree does not retain attribute line numbers.
                    references.append(
                        resolve_resource(path, value, f"{tag}.{field}", 0, known_paths, guids)
                    )
            for match in re.finditer(r"""url\(\s*["']?([^\)"']+)""", element.get("style", "")):
                references.append(
                    resolve_resource(path, match[1], "style.url", 0, known_paths, guids)
                )
        facts = {
            "element_count": len(elements),
            "elements": elements[:256],
            "truncated": len(elements) > 256,
        }
    elif suffix in {".shadergraph", ".shadersubgraph", ".inputactions", ".asmdef", ".asmref"}:
        documents = _json_documents(source)
        if not documents:
            raise ValueError("No JSON objects found.")
        if suffix in {".shadergraph", ".shadersubgraph"}:
            names: list[str] = []
            node_types: list[str] = []

            def visit(value: Any, field: str = "", depth: int = 0) -> None:
                if depth > 64:
                    return
                if isinstance(value, dict):
                    type_name = str(value.get("m_Type", ""))
                    if type_name:
                        node_types.append(type_name)
                        if "Property" in type_name:
                            names.append(
                                str(
                                    value.get("m_OverrideReferenceName")
                                    or value.get("m_DefaultReferenceName")
                                    or value.get("m_Name", "")
                                )
                            )
                    guid = value.get("guid")
                    if isinstance(guid, str) and "fileID" in value:
                        targets = sorted(set(guids.get(guid.lower(), [])))
                        references.append(
                            reference(
                                path,
                                field,
                                0,
                                targets[0] if len(targets) == 1 else "",
                                guid=guid.lower(),
                                file_id=str(value["fileID"]),
                                reason="shadergraph_object_reference",
                            )
                        )
                    for key, item in value.items():
                        if key == "m_SubGraphGUID" and isinstance(item, str):
                            targets = sorted(set(guids.get(item.lower(), [])))
                            references.append(
                                reference(
                                    path,
                                    key,
                                    0,
                                    targets[0] if len(targets) == 1 else "",
                                    guid=item.lower(),
                                    reason="shadergraph_subgraph_guid",
                                )
                            )
                        elif key.startswith("m_Serialized") and isinstance(item, str):
                            with suppress(ValueError, RecursionError):
                                visit(json.loads(item), key, depth + 1)
                        else:
                            visit(item, key, depth + 1)
                elif isinstance(value, list):
                    for item in value:
                        visit(item, field, depth + 1)

            for document in documents:
                visit(document)
            facts = {
                "object_count": len(documents),
                "node_types": sorted(set(node_types)),
                "property_names": sorted(set(filter(None, names))),
            }
        elif suffix == ".inputactions":
            maps = documents[0].get("maps", [])
            if not isinstance(maps, list):
                raise ValueError("Input Actions 'maps' must be an array.")
            facts = {
                "name": documents[0].get("name", ""),
                "maps": [
                    {
                        "name": item.get("name", ""),
                        "actions": [
                            action.get("name", "")
                            for action in item.get("actions", [])
                            if isinstance(action, dict)
                        ],
                        "binding_count": len(item.get("bindings", [])),
                    }
                    for item in maps
                    if isinstance(item, dict)
                ],
            }
        else:
            facts = {
                key: documents[0][key]
                for key in (
                    "name",
                    "references",
                    "includePlatforms",
                    "excludePlatforms",
                    "reference",
                )
                if key in documents[0]
            }
            refs = documents[0].get("references", [])
            refs = refs if isinstance(refs, list) else []
            for value in refs + [documents[0].get("reference", "")]:
                if isinstance(value, str) and value.startswith("GUID:"):
                    guid = value[5:].lower()
                    targets = sorted(set(guids.get(guid, [])))
                    references.append(
                        reference(
                            path,
                            "assembly_reference",
                            0,
                            targets[0] if len(targets) == 1 else "",
                            guid=guid,
                            reason="assembly_guid_reference",
                        )
                    )
    else:
        clean = strip_comments(source)
        if suffix in {".uss", ".tss"}:
            # Skip ordinary quoted literals so content strings cannot invent URLs.
            pattern = (
                r"""(?P<url>url\(\s*["']?(?P<resource>[^\)"']+)[^)]*\))"""
                r"""|(?P<import>@import\s+["'](?P<import_path>[^"']+)["'])"""
                r"""|"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'"""
            )
            for match in re.finditer(pattern, clean):
                resource = match.group("resource") or match.group("import_path")
                if not resource:
                    continue
                references.append(
                    resolve_resource(
                        path,
                        resource,
                        "style.resource",
                        clean.count("\n", 0, match.start()) + 1,
                        known_paths,
                        guids,
                    )
                )
            facts = {"selectors": [item.strip() for item in re.findall(r"([^{}]+)\{", clean)[:128]]}
        else:
            for match in re.finditer(
                r'^\s*#\s*include(?:_with_pragmas)?\s+"([^"\n]+)"', clean, re.MULTILINE
            ):
                references.append(
                    resolve_resource(
                        path,
                        match[1],
                        "include",
                        clean.count("\n", 0, match.start()) + 1,
                        known_paths,
                        guids,
                    )
                )
            name = re.search(r'\bShader\s+"([^"\n]+)"', clean)
            facts = {
                "name": name[1] if name else "",
                "kernels": re.findall(r"^\s*#\s*pragma\s+kernel\s+(\w+)", clean, re.MULTILINE),
                "properties": re.findall(
                    r'^\s*(?:\[[^\]\n]+\]\s*)*(\w+)\s*\(\s*"[^"\n]*"\s*,', clean, re.MULTILINE
                )[:128],
                "use_passes": re.findall(r'\bUsePass\s+"([^"\n]+)"', clean),
            }
    kind = SOURCE_KINDS[suffix]
    return {
        "kind": kind,
        "references": references,
        "source_asset": facts,
        "inspection": "source-structure",
        "confidence": "partial",
        "responsibility": (
            f"{kind.replace('_', ' ').title()} with "
            f"{len(references)} structured resource reference(s)."
        ),
        "high_signal": len(references) + bool(facts),
    }
