"""Verified Unity project facts and GUID-based serialized dependencies."""

from __future__ import annotations

import json
import re
from collections import Counter
from collections.abc import Iterable
from contextlib import suppress
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

GUID_PATTERN = re.compile(r"\bguid:\s*([0-9a-fA-F]{32})\b")
META_GUID_PATTERN = re.compile(r"^guid:\s*([0-9a-fA-F]{32})\s*$", re.MULTILINE)
VENDOR_SEGMENTS = {
    "plugin",
    "plugins",
    "thirdparty",
    "third-party",
    "external",
    "vendor",
    "textmesh pro",
    "googlemobileads",
    "unirx",
    "dotween",
    "demigiant",
    "tools",
}
GENERATED_SEGMENTS = {
    "generated",
    "generatedlocalrepo",
    "library",
    "temp",
    "obj",
}


def is_unity_project(root: Path) -> bool:
    return (root / "Assets").is_dir() and (
        root / "ProjectSettings" / "ProjectVersion.txt"
    ).is_file()


def classify_ownership(path: str) -> str:
    """Classify edit ownership from path and Unity file conventions."""
    normalized = path.replace("\\", "/")
    pure = PurePosixPath(normalized)
    parts = [part.lower() for part in pure.parts]
    suffix = pure.suffix.lower()
    if suffix in {".csproj", ".sln", ".slnx"}:
        return "unity-generated"
    if any(part in GENERATED_SEGMENTS or part.startswith("generated") for part in parts):
        return "generated"
    if parts and parts[0] == "packages":
        return "package"
    if parts and parts[0] == "projectsettings":
        return "project-configuration"
    if any(part in VENDOR_SEGMENTS for part in parts):
        return "vendor"
    if parts and parts[0] == "assets":
        return "project-owned"
    return "repository"


def collect_project_facts(root: Path, paths: Iterable[str]) -> dict[str, Any]:
    normalized_paths = sorted({path.replace("\\", "/") for path in paths})
    unity = is_unity_project(root)
    ownership = Counter(classify_ownership(path) for path in normalized_paths)
    facts: dict[str, Any] = {
        "kind": "unity" if unity else "repository",
        "analysis_engine": "",
        "ownership_counts": dict(sorted(ownership.items())),
        "generated_files": [
            path
            for path in normalized_paths
            if classify_ownership(path) in {"generated", "unity-generated"}
        ][:100],
        "vendor_roots": _ownership_roots(normalized_paths, "vendor"),
        "generated_roots": _ownership_roots(normalized_paths, "generated"),
    }
    if not unity:
        facts["test_files"] = _project_test_files(normalized_paths)
        return facts

    facts.update(
        {
            "unity_version": _unity_version(root),
            **_player_settings(root),
            "packages": _packages(root),
            "scenes": _scenes(root, normalized_paths),
            "asmdefs": _asmdefs(root, normalized_paths),
            "test_files": _project_test_files(normalized_paths),
            "vendor_test_files": _vendor_test_files(normalized_paths),
        }
    )
    return facts


def collect_serialized_reference_edges(inventory: Any) -> list[dict[str, Any]]:
    """Resolve Unity YAML GUID references to asset paths, never to .meta files."""
    by_path = {entry.path.replace("\\", "/"): entry for entry in inventory.files}
    guid_to_asset: dict[str, str] = {}
    for path, entry in by_path.items():
        if not path.endswith(".meta"):
            continue
        try:
            source = entry.absolute_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        match = META_GUID_PATTERN.search(source)
        asset_path = path[:-5]
        if match and asset_path in by_path:
            guid_to_asset[match.group(1).lower()] = asset_path

    details: list[dict[str, Any]] = []
    serialized_suffixes = {".unity", ".prefab", ".asset", ".controller", ".overridecontroller"}
    for path, entry in by_path.items():
        if PurePosixPath(path).suffix.lower() not in serialized_suffixes:
            continue
        try:
            source = entry.absolute_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        targets: dict[str, set[str]] = {}
        for match in GUID_PATTERN.finditer(source):
            guid = match.group(1).lower()
            target = guid_to_asset.get(guid)
            if not target or target == path:
                continue
            targets.setdefault(target, set()).add(guid)
        for target, guids in sorted(targets.items()):
            details.append(
                {
                    "source": path,
                    "target": target,
                    "kinds": ["serialized_guid"],
                    "symbols": sorted(guids)[:5],
                    "lines": [],
                    "confidence": "exact",
                }
            )
    return details


def _unity_version(root: Path) -> str:
    path = root / "ProjectSettings" / "ProjectVersion.txt"
    try:
        source = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return "unknown"
    match = re.search(r"^m_EditorVersion:\s*(\S+)", source, re.MULTILINE)
    return match.group(1) if match else "unknown"


def _player_settings(root: Path) -> dict[str, str]:
    path = root / "ProjectSettings" / "ProjectSettings.asset"
    try:
        source = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return {}
    facts: dict[str, str] = {}
    for key, output_key in (
        ("productName", "product_name"),
        ("bundleVersion", "bundle_version"),
        ("companyName", "company_name"),
    ):
        match = re.search(rf"^\s*{key}:\s*(.*?)\s*$", source, re.MULTILINE)
        if match and match.group(1):
            facts[output_key] = match.group(1).strip()
    return facts


def _packages(root: Path) -> list[dict[str, str]]:
    path = root / "Packages" / "manifest.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    dependencies = data.get("dependencies", {})
    if not isinstance(dependencies, dict):
        return []
    return [
        {
            "name": str(name),
            "version": _display_package_version(str(version)),
            "source": _package_source(str(version)),
        }
        for name, version in sorted(dependencies.items())
    ]


def _package_source(version: str) -> str:
    if version.startswith("file:"):
        return "local"
    if version.startswith("git") or ".git" in version:
        return "git"
    return "registry"


def _display_package_version(version: str) -> str:
    if not version.startswith("file:"):
        return version
    raw = version[5:]
    name = PureWindowsPath(raw).name or PurePosixPath(raw).name
    return f"file:{name or '<local>'}"


def _build_scenes(root: Path) -> list[dict[str, Any]]:
    path = root / "ProjectSettings" / "EditorBuildSettings.asset"
    try:
        source = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    scenes: list[dict[str, Any]] = []
    current_enabled = False
    for line in source.splitlines():
        enabled = re.search(r"\benabled:\s*(\d+)", line)
        if enabled:
            current_enabled = enabled.group(1) == "1"
        scene = re.search(r"\bpath:\s*(Assets/.*\.unity)\s*$", line)
        if scene:
            scenes.append({"path": scene.group(1), "enabled": current_enabled})
    return scenes


def _scenes(root: Path, paths: Iterable[str]) -> list[dict[str, Any]]:
    """List every scene asset and distinguish build scenes from samples/vendor scenes."""
    build = {item["path"]: item["enabled"] for item in _build_scenes(root)}
    scene_paths = {
        path for path in paths if PurePosixPath(path).suffix.lower() == ".unity"
    } | set(build)
    assets = root / "Assets"
    if assets.is_dir():
        with suppress(OSError):
            scene_paths.update(
                path.relative_to(root).as_posix()
                for path in assets.rglob("*.unity")
                if path.is_file()
            )
    return [
        {
            "path": path,
            "enabled": bool(build.get(path, False)),
            "in_build": path in build,
            "ownership": classify_ownership(path),
        }
        for path in sorted(scene_paths)
    ]


def _asmdefs(root: Path, paths: Iterable[str]) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for relative in paths:
        if not relative.endswith(".asmdef"):
            continue
        try:
            data = json.loads((root / Path(relative)).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        results.append(
            {
                "path": relative,
                "name": data.get("name", PurePosixPath(relative).stem),
                "references": data.get("references", []),
                "auto_referenced": data.get("autoReferenced", True),
            }
        )
    return results


def _test_files(paths: Iterable[str]) -> list[str]:
    results = []
    for path in paths:
        pure = PurePosixPath(path)
        if pure.suffix.lower() == ".meta":
            continue
        parts = {part.lower() for part in pure.parts[:-1]}
        stem = pure.stem
        if (
            "test" in parts
            or "tests" in parts
            or stem.startswith("test_")
            or stem.endswith(("_test", "_tests", "Test", "Tests"))
        ):
            results.append(path)
    return results[:200]


def _project_test_files(paths: Iterable[str]) -> list[str]:
    return [path for path in _test_files(paths) if classify_ownership(path) == "project-owned"]


def _vendor_test_files(paths: Iterable[str]) -> list[str]:
    return [path for path in _test_files(paths) if classify_ownership(path) == "vendor"]


def _ownership_roots(paths: Iterable[str], ownership: str) -> list[str]:
    roots: set[str] = set()
    for path in paths:
        if classify_ownership(path) != ownership:
            continue
        if path.endswith(".meta"):
            path = path[:-5]
        parts = PurePosixPath(path).parts
        if not parts:
            continue
        root = None
        for index, part in enumerate(parts[:-1] or parts):
            lowered = part.lower()
            if ownership == "generated" and (
                lowered in GENERATED_SEGMENTS or lowered.startswith("generated")
            ):
                root = "/".join(parts[: index + 1])
                break
            if ownership == "vendor" and lowered in VENDOR_SEGMENTS:
                root = "/".join(parts[: index + 1])
                break
        roots.add(root or "/".join(parts[: min(2, len(parts))]))
    return sorted(roots)[:50]


__all__ = [
    "classify_ownership",
    "collect_project_facts",
    "collect_serialized_reference_edges",
    "is_unity_project",
]
