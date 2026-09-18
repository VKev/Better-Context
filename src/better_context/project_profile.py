"""Per-engine profiles: the data that used to be inlined into the map renderer.

`agents_map` renders one map per directory. Which directories qualify, which file
suffixes carry signal, what a folder is called, and which testing rules apply are all
engine-specific — they used to be module constants plus a `unity: bool` parameter.
They are data here so a second engine (Cocos Creator) is a table entry rather than a
fork of the renderer.

Nothing in this module reads the filesystem; `project_kind` owns detection.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from .project_kind import COCOS_KIND, REPOSITORY_KIND, UNITY_KIND, ProjectKind

# Media and serialized-asset suffixes shared by every engine.
_COMMON_MEDIA_SUFFIXES = frozenset(
    {
        ".aif",
        ".aiff",
        ".avi",
        ".bmp",
        ".exr",
        ".flac",
        ".gif",
        ".hdr",
        ".jpeg",
        ".jpg",
        ".mov",
        ".mp3",
        ".mp4",
        ".ogg",
        ".otf",
        ".png",
        ".psd",
        ".svg",
        ".tga",
        ".tif",
        ".tiff",
        ".ttf",
        ".wav",
        ".webm",
    }
)

_UNITY_RUNTIME_SUFFIXES = _COMMON_MEDIA_SUFFIXES | {
    ".anim",
    ".asset",
    ".controller",
    ".cubemap",
    ".fbx",
    ".lighting",
    ".mat",
    ".mixer",
    ".overridecontroller",
    ".physicsmaterial2d",
    ".physicmaterial",
    ".playable",
    ".prefab",
    ".rendertexture",
    ".shader",
    ".shadergraph",
    ".shadersubgraph",
    ".spriteatlas",
    ".terrainlayer",
    ".unity",
}

_UNITY_ASSET_PATH_SUFFIXES = _UNITY_RUNTIME_SUFFIXES | {
    ".3ds",
    ".blend",
    ".dae",
    ".obj",
}

# Cocos Creator serializes scenes, prefabs, animation clips and materials as JSON,
# and ships sprite atlases as `.plist`/`.atlas` pairs.
_COCOS_RUNTIME_SUFFIXES = _COMMON_MEDIA_SUFFIXES | {
    ".anim",
    ".animgraph",
    ".atlas",
    ".chunk",
    ".effect",
    ".fnt",
    ".labelatlas",
    ".mtl",
    ".pac",
    ".plist",
    ".prefab",
    ".scene",
    ".spriteframe",
    ".tmx",
    ".tsx",
}

_COCOS_ASSET_PATH_SUFFIXES = _COCOS_RUNTIME_SUFFIXES | {
    ".fbx",
    ".gltf",
    ".glb",
    ".obj",
}


@dataclass(frozen=True)
class ProjectKindProfile:
    """Everything the map renderer needs to know about one project kind."""

    kind: ProjectKind
    label: str
    """Human-readable engine name used in headings and prose."""

    roots: frozenset[str] = frozenset()
    """Top-level directories that may receive maps. Empty means "no whitelist"."""

    config_roots: frozenset[str] = frozenset()
    """Roots whose every non-`.meta` file is map signal (project configuration)."""

    source_signal_suffixes: frozenset[str] = frozenset()
    runtime_suffixes: frozenset[str] = frozenset()
    asset_path_suffixes: frozenset[str] = frozenset()
    lifecycle_methods: frozenset[str] = frozenset()

    source_language_label: str = "source"
    """What the source files are called, e.g. `C#` or `TypeScript`."""

    asset_command: str = ""
    """CLI subcommand that inspects this engine's assets, e.g. `unity` or `cocos`."""

    serialized_id_label: str = "reference"
    """What a serialized asset reference is called, e.g. `GUID` or `uuid`."""

    directory_purposes: Mapping[str, str] = field(default_factory=dict)
    file_roles: Mapping[str, str] = field(default_factory=dict)
    ownership_notes: tuple[str, ...] = ()
    testing_rules: tuple[str, ...] = ()
    no_test_note: str = (
        "- No project test file was detected; targeted manual validation remains required."
    )

    @property
    def is_engine(self) -> bool:
        """True for a recognized game engine, false for a plain repository."""
        return self.kind != REPOSITORY_KIND

    def map_signal_suffix(self, suffix: str) -> bool:
        return suffix.lower() in self.source_signal_suffixes

    def runtime_suffix(self, suffix: str) -> bool:
        return suffix.lower() in self.runtime_suffixes

    def asset_path_suffix(self, suffix: str) -> bool:
        return suffix.lower() in self.asset_path_suffixes


REPOSITORY_PROFILE = ProjectKindProfile(
    kind=REPOSITORY_KIND,
    label="repository",
    testing_rules=(
        "- Run the repository's detected test/build commands before changing public APIs.",
    ),
)


UNITY_PROFILE = ProjectKindProfile(
    kind=UNITY_KIND,
    label="Unity",
    roots=frozenset({"Assets", "Packages", "ProjectSettings"}),
    config_roots=frozenset({"Packages", "ProjectSettings"}),
    source_signal_suffixes=frozenset({".cs", ".asmdef", ".asmref", ".json", ".uxml", ".uss"}),
    runtime_suffixes=_UNITY_RUNTIME_SUFFIXES,
    asset_path_suffixes=_UNITY_ASSET_PATH_SUFFIXES,
    lifecycle_methods=frozenset(
        {
            "Awake",
            "OnEnable",
            "Start",
            "FixedUpdate",
            "Update",
            "LateUpdate",
            "OnDisable",
            "OnDestroy",
            "OnValidate",
            "Reset",
        }
    ),
    source_language_label="C#",
    asset_command="unity",
    serialized_id_label="GUID",
    directory_purposes={
        "assets": "Project-owned Unity assets and source code.",
        "packages": "Unity package declarations and embedded project packages.",
        "projectsettings": "Unity project configuration.",
        "scripts": "C# source code.",
        "runtime": "Runtime code and assets.",
        "editor": "Unity Editor-only tooling.",
        "tests": "Automated tests and their fixtures.",
        "gameplay": "Gameplay feature implementations.",
        "ui": "User interface code and assets.",
        "data": "Authored data and serialized configuration.",
        "resources": "Assets loaded through Unity Resources APIs.",
        "scenes": "Unity scenes.",
        "prefabs": "Reusable Unity prefab assets.",
        "art": "Visual art assets.",
        "audio": "Audio assets and configuration.",
    },
    file_roles={
        ".asmdef": "Unity assembly definition.",
        ".asmref": "Unity assembly reference.",
        ".unity": "Unity scene.",
        ".prefab": "Unity prefab.",
        ".asset": "Serialized Unity asset.",
        ".meta": "Unity asset identity and importer metadata.",
        ".json": "JSON configuration or package metadata.",
    },
    ownership_notes=(
        "- `.csproj`, `.sln`, and `.slnx` are Unity-generated even when present "
        "at repository root.",
    ),
    testing_rules=(
        "- Validate C# changes by compiling in Unity `{version}`; run relevant "
        "EditMode/PlayMode tests in Unity Test Runner.",
        "- For CLI automation, use Unity `-batchmode -runTests` with the intended "
        "test platform and capture its result XML.",
        "- Change `Packages/manifest.json` through Unity Package Manager when "
        "possible; review `packages-lock.json` together.",
        "- Prefer Unity Editor changes for `ProjectSettings`; do not hand-edit "
        "generated solution/project files.",
        "- Treat vendor, package, and generated boundaries above as read-only "
        "unless the task explicitly owns them.",
    ),
    no_test_note=(
        "- No project test file was detected; Unity compilation and targeted "
        "manual validation remain required."
    ),
)


COCOS_PROFILE = ProjectKindProfile(
    kind=COCOS_KIND,
    label="Cocos Creator",
    # `settings/` is authored and shared, `extensions/` holds project-local editor
    # plugins; `library/`, `temp/`, `build/`, `profiles/` and `local/` are generated
    # and are excluded by the ignore rules before they ever reach the map.
    roots=frozenset({"assets", "extensions", "settings", "build-templates"}),
    config_roots=frozenset({"settings", "build-templates"}),
    source_signal_suffixes=frozenset({".ts", ".js", ".mjs", ".json", ".effect", ".chunk"}),
    runtime_suffixes=_COCOS_RUNTIME_SUFFIXES,
    asset_path_suffixes=_COCOS_ASSET_PATH_SUFFIXES,
    lifecycle_methods=frozenset(
        {
            "onLoad",
            "start",
            "update",
            "lateUpdate",
            "onEnable",
            "onDisable",
            "onDestroy",
            "onFocusInEditor",
            "onLostFocusInEditor",
            "resetInEditor",
        }
    ),
    source_language_label="TypeScript",
    asset_command="cocos",
    serialized_id_label="uuid",
    directory_purposes={
        "assets": "Project-owned Cocos assets and TypeScript source.",
        "extensions": "Project-local Cocos Creator editor extensions.",
        "settings": "Cocos Creator project configuration shared by the team.",
        "build-templates": "Authored files injected into builds (not build output).",
        "scripts": "TypeScript source code.",
        "core": "Core runtime systems and simulation code.",
        "ui": "User interface scenes, prefabs, and controllers.",
        "scene": "Cocos scenes.",
        "scenes": "Cocos scenes.",
        "prefabs": "Reusable Cocos prefab assets.",
        "resources": "Assets loaded at runtime through `resources.load`.",
        "res": "Bundled runtime assets.",
        "main": "Startup scene and entry assets shipped in the main package.",
        "editor": "Editor-only assets and tooling.",
        "tests": "Automated tests and their fixtures.",
        "i18n": "Localized strings and language tables.",
        "art": "Visual art assets.",
        "audio": "Audio assets and configuration.",
        "data": "Authored data and serialized configuration.",
    },
    file_roles={
        ".scene": "Cocos scene (serialized JSON).",
        ".prefab": "Cocos prefab (serialized JSON).",
        ".anim": "Cocos animation clip.",
        ".effect": "Cocos effect/shader source.",
        ".meta": "Cocos asset identity (uuid) and importer metadata.",
        ".plist": "Sprite atlas or property list data.",
        ".json": "JSON configuration, data table, or package metadata.",
    },
    ownership_notes=(
        "- `library/`, `temp/`, `build/`, `profiles/`, and `local/` are Cocos-generated; "
        "delete and re-import instead of editing them.",
        "- Every asset has a sibling `.meta` holding its uuid. Never delete or hand-edit "
        "one: scenes and prefabs reference assets by uuid, and a new uuid silently breaks "
        "every reference.",
    ),
    testing_rules=(
        "- A clean `npx tsc --noEmit` is necessary but not sufficient; the real gate is a "
        "completed build for the target platform, not the Editor preview.",
        "- Rebuild scenes and prefabs through the Editor or the Cocos MCP tools; hand-edited "
        "`.scene`/`.prefab` JSON drifts from the class-ids compressed out of script uuids.",
        "- After editing a `.ts` file, refresh assets and wait for its `.meta` before running "
        "any tool that resolves uuids.",
        "- Treat vendor, extension, and generated boundaries above as read-only unless the "
        "task explicitly owns them.",
    ),
    no_test_note=(
        "- No project test file was detected; a completed platform build and targeted "
        "manual validation remain required."
    ),
)


_PROFILES: dict[str, ProjectKindProfile] = {
    UNITY_KIND: UNITY_PROFILE,
    COCOS_KIND: COCOS_PROFILE,
    REPOSITORY_KIND: REPOSITORY_PROFILE,
}


def profile_for_kind(kind: str | None) -> ProjectKindProfile:
    """Return the profile for a project kind, defaulting to the plain-repository one."""
    return _PROFILES.get(str(kind or REPOSITORY_KIND), REPOSITORY_PROFILE)


__all__ = [
    "COCOS_PROFILE",
    "ProjectKindProfile",
    "REPOSITORY_PROFILE",
    "UNITY_PROFILE",
    "profile_for_kind",
]
