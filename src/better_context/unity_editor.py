"""Unity Editor snapshot bridge used to enrich offline project analysis.

The Python side communicates with the companion UPM package through atomic
request/snapshot files under ``.better-context``.  No socket or long-running
Python service is required.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

EDITOR_BRIDGE_VERSION = "1.6.0"
EDITOR_SNAPSHOT_SCHEMA = "1.0.0"
EDITOR_PACKAGE_NAME = "com.vkev.better-context.editor"
EDITOR_PACKAGE_PATH = "unity-package/com.vkev.better-context.editor"
EDITOR_REPOSITORY = "https://github.com/VKev/Better-Context.git"

_RELEVANT_SUFFIXES = {
    ".aif",
    ".aiff",
    ".anim",
    ".asset",
    ".avi",
    ".bmp",
    ".controller",
    ".cs",
    ".cubemap",
    ".exr",
    ".fbx",
    ".flac",
    ".gif",
    ".hdr",
    ".jpeg",
    ".jpg",
    ".lighting",
    ".mat",
    ".mixer",
    ".mov",
    ".mp3",
    ".mp4",
    ".ogg",
    ".otf",
    ".overridecontroller",
    ".physicsmaterial2d",
    ".physicmaterial",
    ".playable",
    ".png",
    ".prefab",
    ".psd",
    ".rendertexture",
    ".shader",
    ".shadergraph",
    ".shadersubgraph",
    ".spriteatlas",
    ".terrainlayer",
    ".tga",
    ".tif",
    ".tiff",
    ".ttf",
    ".unity",
    ".wav",
    ".webm",
}


@dataclass
class EditorSnapshotStatus:
    """Freshness and availability state for one Editor snapshot."""

    state: str
    message: str
    snapshot_path: Path
    source_hash: str
    snapshot: dict[str, Any] | None = None
    errors: list[str] = field(default_factory=list)


@dataclass
class EditorSyncResult:
    """Result of requesting a fresh snapshot from an open or batch Editor."""

    success: bool
    mode: str
    message: str
    snapshot_path: Path
    snapshot: dict[str, Any] | None = None
    errors: list[str] = field(default_factory=list)


def editor_state_dir(root: Path, output_dir: str = ".better-context") -> Path:
    return root.resolve() / output_dir


def editor_snapshot_path(root: Path, output_dir: str = ".better-context") -> Path:
    return editor_state_dir(root, output_dir) / "editor-snapshot.json"


def editor_request_path(root: Path, output_dir: str = ".better-context") -> Path:
    return editor_state_dir(root, output_dir) / "editor-request.json"


def project_unity_version(root: Path) -> str:
    """Read the exact Unity editor version declared by the project."""
    path = root / "ProjectSettings" / "ProjectVersion.txt"
    try:
        source = path.read_text(encoding="utf-8-sig")
    except OSError:
        return ""
    match = re.search(r"^m_EditorVersion:\s*(\S+)\s*$", source, re.MULTILINE)
    return match.group(1) if match else ""


def compute_package_lock_hash(root: Path) -> str:
    """Hash package declarations that affect importer and MonoScript identity."""
    digest = hashlib.sha256()
    for relative in ("Packages/manifest.json", "Packages/packages-lock.json"):
        path = root / Path(relative)
        digest.update(relative.encode())
        try:
            digest.update(path.read_bytes())
        except OSError:
            digest.update(b"<missing>")
    return digest.hexdigest()


def compute_editor_source_hash(root: Path) -> str:
    """Return a cheap deterministic fingerprint for Editor-visible inputs.

    Binary payloads are represented by size and nanosecond mtime while their
    ``.meta`` importer data participates directly.  This avoids hashing large
    models, audio, and textures on every freshness check.
    """
    root = root.resolve()
    digest = hashlib.sha256()
    candidates: list[Path] = []
    assets = root / "Assets"
    if assets.is_dir():
        for path in assets.rglob("*"):
            if not path.is_file():
                continue
            suffix = path.suffix.lower()
            if suffix in _RELEVANT_SUFFIXES or path.name.endswith(".meta"):
                candidates.append(path)
    for relative in (
        "Packages/manifest.json",
        "Packages/packages-lock.json",
        "ProjectSettings/ProjectVersion.txt",
    ):
        path = root / Path(relative)
        if path.is_file():
            candidates.append(path)
    for path in sorted(candidates, key=lambda value: value.relative_to(root).as_posix()):
        relative = path.relative_to(root).as_posix()
        try:
            stat = path.stat()
        except OSError:
            continue
        digest.update(relative.encode("utf-8", "surrogatepass"))
        digest.update(b"\0")
        digest.update(str(stat.st_size).encode())
        digest.update(b"\0")
        digest.update(str(stat.st_mtime_ns).encode())
        digest.update(b"\n")
    return digest.hexdigest()


def _atomic_write_json(
    path: Path,
    value: dict[str, Any],
    *,
    trailing_newline: bool = False,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    serialized = json.dumps(value, indent=2)
    if trailing_newline:
        serialized += "\n"
    temporary.write_text(serialized, encoding="utf-8")
    os.replace(temporary, path)


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None
    return value if isinstance(value, dict) else None


def get_editor_snapshot_status(
    root: Path,
    output_dir: str = ".better-context",
) -> EditorSnapshotStatus:
    """Validate a snapshot against the current project without reusing stale data."""
    root = root.resolve()
    path = editor_snapshot_path(root, output_dir)
    source_hash = compute_editor_source_hash(root)
    snapshot = _read_json(path)
    if snapshot is None:
        state = "missing" if not path.exists() else "corrupt"
        return EditorSnapshotStatus(
            state,
            (
                "Unity Editor snapshot is missing."
                if state == "missing"
                else "Unity Editor snapshot is corrupt."
            ),
            path,
            source_hash,
        )
    problems: list[str] = []
    if snapshot.get("schema_version") != EDITOR_SNAPSHOT_SCHEMA:
        problems.append("snapshot schema mismatch")
    if snapshot.get("bridge_version") != EDITOR_BRIDGE_VERSION:
        problems.append("bridge version mismatch")
    expected_unity = project_unity_version(root)
    if expected_unity and snapshot.get("unity_version") != expected_unity:
        problems.append("Unity version mismatch")
    if snapshot.get("source_hash") != source_hash:
        problems.append("project assets changed")
    if snapshot.get("package_lock_hash") != compute_package_lock_hash(root):
        problems.append("package lock changed")
    if snapshot.get("status", "ok") != "ok":
        problems.append("Editor export reported failure")
    if problems:
        return EditorSnapshotStatus(
            "stale",
            "Unity Editor snapshot is stale: " + ", ".join(problems) + ".",
            path,
            source_hash,
            errors=problems,
        )
    return EditorSnapshotStatus(
        "fresh",
        "Unity Editor snapshot is fresh.",
        path,
        source_hash,
        snapshot=normalize_editor_snapshot(snapshot),
    )


def _process_running(process_id: int) -> bool:
    if process_id <= 0:
        return False
    try:
        os.kill(process_id, 0)
    except (OSError, PermissionError):
        return False
    return True


def is_project_open(root: Path) -> bool:
    """Return whether Unity records a live Editor process for the project."""
    value = _read_json(root / "Library" / "EditorInstance.json") or {}
    raw_pid = value.get("process_id", value.get("processId", 0))
    try:
        process_id = int(raw_pid)
    except (TypeError, ValueError):
        process_id = 0
    return _process_running(process_id)


def _version_from_editor_path(path: Path) -> str:
    lowered = [part.casefold() for part in path.parts]
    try:
        editor_index = lowered.index("editor")
    except ValueError:
        return ""
    if editor_index >= 1 and path.parts[editor_index - 1].casefold() != "hub":
        return path.parts[editor_index - 1]
    return ""


def _query_editor_version(path: Path) -> str:
    try:
        result = subprocess.run(
            [str(path), "-version"],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    output = "\n".join((result.stdout, result.stderr))
    match = re.search(r"\b\d{4}\.\d+\.\d+[abfp]\d+\b", output)
    return match.group(0) if match else ""


def discover_unity_editor(root: Path, configured_path: str | None = None) -> Path | None:
    """Find an executable matching the exact version in ProjectVersion.txt."""
    version = project_unity_version(root)
    candidates: list[Path] = []
    if configured_path:
        candidates.append(Path(configured_path).expanduser())
    environment_path = os.environ.get("UNITY_EDITOR_PATH")
    if environment_path:
        candidates.append(Path(environment_path).expanduser())
    if os.name == "nt" and version:
        for base in (
            os.environ.get("PROGRAMFILES"),
            os.environ.get("PROGRAMFILES(X86)"),
            r"C:\Program Files",
        ):
            if base:
                candidates.append(
                    Path(base) / "Unity" / "Hub" / "Editor" / version / "Editor" / "Unity.exe"
                )
    seen: set[Path] = set()
    for candidate in candidates:
        try:
            resolved = candidate.resolve()
        except OSError:
            continue
        if resolved in seen or not resolved.is_file():
            continue
        seen.add(resolved)
        detected = _version_from_editor_path(resolved) or _query_editor_version(resolved)
        if not version or detected == version:
            return resolved
    return None


def _write_request(root: Path, output_dir: str, mode: str) -> dict[str, Any]:
    nonce = uuid.uuid4().hex
    request = {
        "schema_version": EDITOR_SNAPSHOT_SCHEMA,
        "bridge_version": EDITOR_BRIDGE_VERSION,
        "requested_at": datetime.now(timezone.utc).isoformat(),
        "project_root": root.resolve().as_posix(),
        "mode": mode,
        "nonce": nonce,
        "source_hash": compute_editor_source_hash(root),
        "package_lock_hash": compute_package_lock_hash(root),
        "response_path": editor_snapshot_path(root, output_dir).resolve().as_posix(),
    }
    _atomic_write_json(editor_request_path(root, output_dir), request)
    return request


def _wait_for_snapshot(
    root: Path,
    output_dir: str,
    nonce: str,
    timeout_seconds: int,
) -> dict[str, Any] | None:
    deadline = time.monotonic() + timeout_seconds
    path = editor_snapshot_path(root, output_dir)
    while time.monotonic() < deadline:
        snapshot = _read_json(path)
        if snapshot and snapshot.get("nonce") == nonce:
            return snapshot
        time.sleep(0.25)
    return None


def sync_editor_snapshot(
    root: Path,
    *,
    mode: str = "auto",
    output_dir: str = ".better-context",
    timeout_seconds: int = 300,
    editor_path: str | None = None,
) -> EditorSyncResult:
    """Request an Editor snapshot, preferring an already-open project."""
    root = root.resolve()
    snapshot_path = editor_snapshot_path(root, output_dir)
    if mode not in {"auto", "open", "batch"}:
        return EditorSyncResult(False, mode, f"Unsupported Editor mode: {mode}", snapshot_path)
    expected_unity = project_unity_version(root)
    if not expected_unity:
        return EditorSyncResult(
            False,
            mode,
            "ProjectVersion.txt does not declare a Unity version.",
            snapshot_path,
        )

    open_project = is_project_open(root)
    selected = mode
    batch_command: list[str] | None = None
    if mode == "auto":
        selected = "open" if open_project else "batch"
    if selected == "open":
        if not open_project:
            return EditorSyncResult(
                False,
                selected,
                "The target project is not open in Unity Editor.",
                snapshot_path,
            )
        request = _write_request(root, output_dir, "open")
        snapshot = _wait_for_snapshot(root, output_dir, request["nonce"], timeout_seconds)
        if snapshot is None:
            return EditorSyncResult(
                False,
                selected,
                "The open Unity Editor did not answer the snapshot request before timeout; "
                "batch fallback was not attempted because the project is locked.",
                snapshot_path,
            )
    else:
        if open_project:
            return EditorSyncResult(
                False,
                selected,
                "Batch export is unsafe while this project is open in another Unity Editor.",
                snapshot_path,
            )
        executable = discover_unity_editor(root, editor_path)
        if executable is None:
            return EditorSyncResult(
                False,
                selected,
                f"Unity Editor {expected_unity} was not found.",
                snapshot_path,
            )
        request = _write_request(root, output_dir, "batch")
        log_path = editor_state_dir(root, output_dir) / "editor-batch.log"
        batch_command = [
            str(executable),
            "-batchmode",
            "-nographics",
            "-quit",
            "-projectPath",
            str(root),
            "-executeMethod",
            "VKev.BetterContext.EditorBridge.Export",
            "-betterContextRequest",
            str(editor_request_path(root, output_dir).resolve()),
            "-logFile",
            str(log_path.resolve()),
        ]
        try:
            completed = subprocess.run(batch_command, timeout=timeout_seconds, check=False)
        except subprocess.TimeoutExpired:
            return EditorSyncResult(False, selected, "Unity batch export timed out.", snapshot_path)
        except OSError as exc:
            return EditorSyncResult(
                False,
                selected,
                f"Unity batch export could not start: {exc}",
                snapshot_path,
            )
        snapshot = _read_json(snapshot_path)
        if completed.returncode != 0 or not snapshot or snapshot.get("nonce") != request["nonce"]:
            return EditorSyncResult(
                False,
                selected,
                f"Unity batch export failed with exit code {completed.returncode}; see {log_path}.",
                snapshot_path,
            )

    status = get_editor_snapshot_status(root, output_dir)
    if (
        selected == "batch"
        and batch_command is not None
        and status.state == "stale"
        and set(status.errors).issubset({"project assets changed", "package lock changed"})
        and status.errors
    ):
        # A first import may create missing .meta files.  Re-export once with
        # the settled project fingerprint instead of accepting stale facts.
        request = _write_request(root, output_dir, "batch")
        try:
            completed = subprocess.run(batch_command, timeout=timeout_seconds, check=False)
        except (OSError, subprocess.SubprocessError) as exc:
            return EditorSyncResult(
                False,
                selected,
                f"Unity batch stabilization export failed: {exc}",
                snapshot_path,
            )
        snapshot = _read_json(snapshot_path)
        if completed.returncode != 0 or not snapshot or snapshot.get("nonce") != request["nonce"]:
            return EditorSyncResult(
                False,
                selected,
                "Unity batch stabilization export did not produce a matching snapshot.",
                snapshot_path,
            )
        status = get_editor_snapshot_status(root, output_dir)
    if status.state != "fresh" or status.snapshot is None:
        return EditorSyncResult(
            False,
            selected,
            status.message,
            snapshot_path,
            errors=status.errors,
        )
    return EditorSyncResult(
        True,
        selected,
        f"Unity Editor snapshot refreshed in {selected} mode.",
        snapshot_path,
        snapshot=status.snapshot,
        errors=[str(item.get("message", item)) for item in status.snapshot.get("errors", [])],
    )


def install_editor_package(root: Path, revision: str = "v1.6.0") -> tuple[bool, str]:
    """Pin the companion UPM package in Packages/manifest.json."""
    manifest_path = root / "Packages" / "manifest.json"
    try:
        original = manifest_path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError):
        return False, f"Could not read {manifest_path}."
    value = _read_json(manifest_path)
    if value is None:
        return False, f"Could not read {manifest_path}."
    dependencies = value.get("dependencies")
    if not isinstance(dependencies, dict):
        return False, "Packages/manifest.json has no dependencies object."
    revision = revision.strip()
    if not revision or any(character.isspace() for character in revision):
        return False, "Package revision must be a non-empty Git revision without whitespace."
    package_url = f"{EDITOR_REPOSITORY}?path=/{EDITOR_PACKAGE_PATH}#{revision}"
    if dependencies.get(EDITOR_PACKAGE_NAME) == package_url:
        return True, f"{EDITOR_PACKAGE_NAME} is already pinned to {revision}."
    dependencies[EDITOR_PACKAGE_NAME] = package_url
    value["dependencies"] = dependencies
    _atomic_write_json(
        manifest_path,
        value,
        trailing_newline=original.endswith(("\n", "\r")),
    )
    return True, f"Pinned {EDITOR_PACKAGE_NAME} to {revision}."


def editor_package_spec(root: Path) -> str:
    """Return the configured UPM dependency or an empty string."""
    value = _read_json(root / "Packages" / "manifest.json") or {}
    dependencies = value.get("dependencies", {})
    if not isinstance(dependencies, dict):
        return ""
    return str(dependencies.get(EDITOR_PACKAGE_NAME, ""))


def _facts(value: object) -> dict[str, Any]:
    if not isinstance(value, list):
        return {}
    result: dict[str, Any] = {}
    for item in value:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name", "")).strip()
        if name:
            result[name] = item.get("value", "")
    return result


def normalize_editor_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Normalize the compact C# DTO shape into query-friendly dictionaries."""
    normalized = dict(snapshot)
    assets: list[dict[str, Any]] = []
    for raw_asset in snapshot.get("assets", []):
        if not isinstance(raw_asset, dict):
            continue
        asset = dict(raw_asset)
        asset["facts"] = _facts(raw_asset.get("facts"))
        subassets: list[dict[str, Any]] = []
        for raw_subasset in raw_asset.get("subassets", []):
            if not isinstance(raw_subasset, dict):
                continue
            subasset = dict(raw_subasset)
            subasset["facts"] = _facts(raw_subasset.get("facts"))
            subassets.append(subasset)
        asset["subassets"] = subassets
        assets.append(asset)
    normalized["assets"] = assets
    normalized["assets_by_path"] = {
        str(item.get("path", "")).replace("\\", "/"): item
        for item in assets
        if item.get("path")
    }
    scripts = [item for item in snapshot.get("scripts", []) if isinstance(item, dict)]
    normalized["scripts"] = scripts
    normalized["scripts_by_guid"] = {
        str(item.get("guid", "")).lower(): item for item in scripts if item.get("guid")
    }
    subassets_by_identity: dict[str, dict[str, Any]] = {}
    for asset in assets:
        guid = str(asset.get("guid", "")).lower()
        for subasset in asset.get("subassets", []):
            local_id = str(subasset.get("local_id", ""))
            if guid and local_id:
                subassets_by_identity[f"{guid}:{local_id}"] = subasset
    normalized["subassets_by_identity"] = subassets_by_identity
    return normalized


__all__ = [
    "EDITOR_BRIDGE_VERSION",
    "EDITOR_PACKAGE_NAME",
    "EDITOR_SNAPSHOT_SCHEMA",
    "EditorSnapshotStatus",
    "EditorSyncResult",
    "compute_editor_source_hash",
    "compute_package_lock_hash",
    "discover_unity_editor",
    "editor_package_spec",
    "editor_request_path",
    "editor_snapshot_path",
    "get_editor_snapshot_status",
    "install_editor_package",
    "is_project_open",
    "normalize_editor_snapshot",
    "project_unity_version",
    "sync_editor_snapshot",
]
