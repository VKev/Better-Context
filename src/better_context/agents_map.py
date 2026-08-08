"""Safe hierarchical AGENTS.md maps for Unity repositories."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from .graph import DependencyGraph
from .manifest import FileEntry, Manifest

BEGIN = "<!-- better-context-unity:begin -->"
END = "<!-- better-context-unity:end -->"
MANAGED_PATTERN = re.compile(re.escape(BEGIN) + r".*?" + re.escape(END), re.DOTALL)
UNITY_ROOTS = {"Assets", "Packages", "ProjectSettings"}
SUMMARY_FILE = ".ctx-summaries.json"
MAX_SUMMARY_LENGTH = 240


@dataclass
class MapResult:
    files_written: list[str] = field(default_factory=list)
    unchanged: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def generate_agents_map(
    manifest: Manifest,
    graph: DependencyGraph,
    output_root: Path,
    max_depth: int = -1,
    dry_run: bool = False,
    summaries: Mapping[str, str] | None = None,
) -> MapResult:
    """Create or refresh only the marked map block in each AGENTS.md."""
    output_root = output_root.resolve()
    unity = _is_unity_project(output_root)
    directories = _collect_directories(manifest, unity, max_depth)
    summaries = summaries or {}
    result = MapResult()

    for rel_dir in sorted(directories, key=lambda value: (value.count("/"), value)):
        target = output_root / Path(rel_dir) / "AGENTS.md" if rel_dir else output_root / "AGENTS.md"
        managed = _render_directory(
            rel_dir,
            directories,
            manifest,
            graph,
            unity,
            summaries,
        )
        try:
            current = target.read_text(encoding="utf-8") if target.exists() else ""
            updated = _merge_managed_block(current, managed)
            relative_target = target.relative_to(output_root).as_posix()
            if updated == current:
                result.unchanged.append(relative_target)
            else:
                result.files_written.append(relative_target)
                if not dry_run:
                    target.write_text(updated, encoding="utf-8")
        except OSError as exc:
            result.errors.append(f"{target}: {exc}")

    return result


def _is_unity_project(root: Path) -> bool:
    return (root / "Assets").is_dir() and (
        root / "ProjectSettings" / "ProjectVersion.txt"
    ).is_file()


def _collect_directories(manifest: Manifest, unity: bool, max_depth: int) -> set[str]:
    directories = {""}
    for entry in manifest.files:
        path = PurePosixPath(entry.path)
        if path.name == "AGENTS.md" or not path.parts:
            continue
        if unity and path.parts[0] not in UNITY_ROOTS:
            continue
        parent = path.parent
        while str(parent) != ".":
            if max_depth < 0 or len(parent.parts) <= max_depth:
                directories.add(parent.as_posix())
            parent = parent.parent
    return directories


def _render_directory(
    rel_dir: str,
    directories: set[str],
    manifest: Manifest,
    graph: DependencyGraph,
    unity: bool,
    summaries: Mapping[str, str],
) -> str:
    direct_files = [
        entry
        for entry in manifest.files
        if _parent(entry.path) == rel_dir and PurePosixPath(entry.path).name != "AGENTS.md"
    ]
    children = sorted(value for value in directories if value and _parent(value) == rel_dir)
    title = (
        "Unity project map" if not rel_dir and unity else f"Folder map: {rel_dir or 'repository'}"
    )
    lines = [BEGIN, f"## {title}", "", _purpose(rel_dir, unity), ""]
    if rel_dir in summaries:
        lines.extend([f"**Summary:** {_summary_cell(summaries[rel_dir])}", ""])

    if children:
        has_summaries = any(child in summaries for child in children)
        header = "| Folder | Purpose | Summary |" if has_summaries else "| Folder | Purpose |"
        divider = "|---|---|---|" if has_summaries else "|---|---|"
        lines.extend(["### Child folders", "", header, divider])
        for child in children:
            name = PurePosixPath(child).name
            row = f"| [`{name}/`]({name}/AGENTS.md) | {_purpose(child, unity)}"
            if has_summaries:
                row += f" | {_summary_cell(summaries.get(child, '—'))}"
            lines.append(row + " |")
        lines.append("")

    if direct_files:
        has_summaries = any(entry.path in summaries for entry in direct_files)
        header = "| File | Role | Summary |" if has_summaries else "| File | Role |"
        divider = "|---|---|---|" if has_summaries else "|---|---|"
        lines.extend(["### Files", "", header, divider])
        ordered_files = sorted(
            direct_files,
            key=lambda entry: (entry.path not in summaries, entry.path),
        )
        visible_limit = max(40, sum(entry.path in summaries for entry in direct_files))
        for entry in ordered_files[:visible_limit]:
            row = f"| `{PurePosixPath(entry.path).name}` | {_file_role(entry, graph)}"
            if has_summaries:
                row += f" | {_summary_cell(summaries.get(entry.path, '—'))}"
            lines.append(row + " |")
        if len(direct_files) > visible_limit:
            remaining = len(direct_files) - visible_limit
            row = f"| … | {remaining} additional files; inspect on demand."
            lines.append(row + (" | — |" if has_summaries else " |"))
        lines.append("")

    if rel_dir:
        lines.extend(["Parent map: [`../AGENTS.md`](../AGENTS.md)", ""])
    else:
        lines.extend(
            [
                "Read the maps from the repository root down to the target folder "
                "before editing there.",
                "Keep handwritten instructions outside this managed block; "
                "regeneration preserves them.",
                "",
            ]
        )

    lines.extend([END, ""])
    return "\n".join(lines)


def _parent(path: str) -> str:
    parent = PurePosixPath(path).parent
    return "" if str(parent) == "." else parent.as_posix()


def _purpose(path: str, unity: bool) -> str:
    name = PurePosixPath(path).name.lower() if path else ""
    purposes = {
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
    }
    if not path:
        return (
            "Navigation map for the Unity project."
            if unity
            else "Navigation map for the repository."
        )
    return purposes.get(name, f"Contents owned by `{path}`.")


def _file_role(entry: FileEntry, graph: DependencyGraph) -> str:
    suffix = PurePosixPath(entry.path).suffix.lower()
    if suffix == ".cs":
        types = [chunk for chunk in entry.chunks if chunk.type != "method"]
        labels = []
        for chunk in types[:3]:
            unity_type = chunk.metadata.get("unity_type")
            labels.append(f"{chunk.name} ({unity_type})" if unity_type else chunk.name)
        role = ", ".join(labels) if labels else "C# source"
        dependents = graph.in_degree(entry.path)
        return f"{role}; {dependents} dependent file(s)." if dependents else f"{role}."
    roles = {
        ".asmdef": "Unity assembly definition.",
        ".asmref": "Unity assembly reference.",
        ".unity": "Unity scene.",
        ".prefab": "Unity prefab.",
        ".asset": "Serialized Unity asset.",
        ".meta": "Unity asset identity and importer metadata.",
        ".json": "JSON configuration or package metadata.",
    }
    return roles.get(suffix, "Project file.")


def parse_summary_assignment(value: str) -> tuple[str, str]:
    """Parse a CLI PATH=TEXT summary assignment."""
    if "=" not in value:
        raise ValueError("Summary must use PATH=TEXT format")
    raw_path, raw_text = value.split("=", 1)
    return normalize_summary_path(raw_path), normalize_summary_text(raw_text)


def normalize_summary_path(value: str) -> str:
    """Normalize and validate a project-relative summary target."""
    normalized = value.strip().replace("\\", "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    normalized = normalized.rstrip("/")
    if normalized in {"", "."}:
        return ""
    path = PurePosixPath(normalized)
    if path.is_absolute() or ".." in path.parts or re.match(r"^[A-Za-z]:", normalized):
        raise ValueError("Summary path must be relative to the project root")
    return path.as_posix()


def normalize_summary_text(value: str) -> str:
    """Keep summaries compact enough for navigation maps."""
    normalized = " ".join(value.split())
    if not normalized:
        raise ValueError("Summary text cannot be empty")
    if len(normalized) > MAX_SUMMARY_LENGTH:
        raise ValueError(f"Summary text cannot exceed {MAX_SUMMARY_LENGTH} characters")
    return normalized


def load_summaries(root: Path) -> dict[str, str]:
    """Load optional persisted summaries from the project root."""
    path = root / SUMMARY_FILE
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Cannot read {SUMMARY_FILE}: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"{SUMMARY_FILE} must contain a JSON object")

    summaries: dict[str, str] = {}
    for raw_path, raw_text in data.items():
        if not isinstance(raw_path, str) or not isinstance(raw_text, str):
            raise ValueError(f"{SUMMARY_FILE} keys and values must be strings")
        summaries[normalize_summary_path(raw_path)] = normalize_summary_text(raw_text)
    return summaries


def save_summaries(root: Path, summaries: Mapping[str, str]) -> Path:
    """Persist optional summaries, or remove the empty ledger."""
    path = root / SUMMARY_FILE
    if summaries:
        ordered = {path or ".": text for path, text in sorted(summaries.items())}
        path.write_text(
            json.dumps(ordered, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    elif path.exists():
        path.unlink()
    return path


def summary_targets(manifest: Manifest, root: Path, max_depth: int = -1) -> set[str]:
    """Return file and folder paths that can appear in generated maps."""
    directories = _collect_directories(manifest, _is_unity_project(root), max_depth)
    files = {
        entry.path
        for entry in manifest.files
        if _parent(entry.path) in directories and PurePosixPath(entry.path).name != "AGENTS.md"
    }
    return directories | files


def _summary_cell(value: str) -> str:
    return " ".join(value.split()).replace("|", r"\|")


def _merge_managed_block(current: str, managed: str) -> str:
    if MANAGED_PATTERN.search(current):
        return MANAGED_PATTERN.sub(managed.rstrip(), current).rstrip() + "\n"
    if "Auto-generated context for AI agents" in current:
        return managed
    if not current.strip():
        return managed
    return current.rstrip() + "\n\n" + managed


def remove_managed_map(path: Path) -> bool:
    """Remove only this tool's block, preserving handwritten instructions."""
    try:
        current = path.read_text(encoding="utf-8")
    except OSError:
        return False
    if not MANAGED_PATTERN.search(current):
        return False
    updated = MANAGED_PATTERN.sub("", current).strip()
    if updated:
        path.write_text(updated + "\n", encoding="utf-8")
    else:
        path.unlink()
    return True


__all__ = [
    "BEGIN",
    "END",
    "MAX_SUMMARY_LENGTH",
    "MapResult",
    "SUMMARY_FILE",
    "generate_agents_map",
    "load_summaries",
    "normalize_summary_path",
    "parse_summary_assignment",
    "remove_managed_map",
    "save_summaries",
    "summary_targets",
]
