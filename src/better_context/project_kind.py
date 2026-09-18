"""Single source of truth for which game-engine project kind a root is.

Detection is filesystem-based and authored-file-based: a generated `.csproj` or an
incidental `package.json` must never decide the kind. Unity is checked first because
a Unity project can legitimately carry Node tooling; Cocos is checked before the
generic Node/TypeScript branch for the same reason.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

ProjectKind = Literal["unity", "cocos", "repository"]

UNITY_KIND = "unity"
COCOS_KIND = "cocos"
REPOSITORY_KIND = "repository"

#: Accepted values for the `project_kind` config key.
CONFIGURABLE_KINDS = ("auto", UNITY_KIND, COCOS_KIND, REPOSITORY_KIND)


def is_unity_project(root: Path) -> bool:
    """A Unity project authors `Assets/` and `ProjectSettings/ProjectVersion.txt`."""
    return (root / "Assets").is_dir() and (
        root / "ProjectSettings" / "ProjectVersion.txt"
    ).is_file()


def is_cocos_project(root: Path) -> bool:
    """A Cocos Creator project authors `assets/` and a `package.json` with `creator`.

    Cocos Creator writes `{"creator": {"version": "3.8.8"}}` into the project
    `package.json`; that field is the authored marker. The directory check is
    case-sensitive on purpose so a Unity `Assets/` tree cannot match.
    """
    if not (root / "assets").is_dir():
        return False
    return cocos_creator_version(root) != ""


def cocos_creator_version(root: Path) -> str:
    """Return the declared Cocos Creator version, or an empty string."""
    package_file = root / "package.json"
    if not package_file.is_file():
        return ""
    try:
        data = json.loads(package_file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    if not isinstance(data, dict):
        return ""
    creator = data.get("creator")
    if not isinstance(creator, dict):
        return ""
    version = creator.get("version")
    return str(version) if isinstance(version, (str, int, float)) else ""


def detect_project_kind(root: Path) -> ProjectKind:
    """Classify `root` as a Unity project, a Cocos Creator project, or neither."""
    if is_unity_project(root):
        return UNITY_KIND
    if is_cocos_project(root):
        return COCOS_KIND
    return REPOSITORY_KIND


def resolve_project_kind(root: Path, configured: str | None = None) -> ProjectKind:
    """Apply an explicit `project_kind` override, falling back to detection.

    An override is only honored when it names a supported kind; `auto`, an empty
    value, and anything unrecognized fall back to detection so a stale config
    cannot silently mislabel a project.
    """
    if configured:
        value = str(configured).strip().lower()
        if value in {UNITY_KIND, COCOS_KIND, REPOSITORY_KIND}:
            return value  # type: ignore[return-value]
    return detect_project_kind(root)


__all__ = [
    "COCOS_KIND",
    "CONFIGURABLE_KINDS",
    "ProjectKind",
    "REPOSITORY_KIND",
    "UNITY_KIND",
    "cocos_creator_version",
    "detect_project_kind",
    "is_cocos_project",
    "is_unity_project",
    "resolve_project_kind",
]
