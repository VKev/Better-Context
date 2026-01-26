from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from ..ignore import should_ignore, should_ignore_dir


@dataclass
class ProjectTooling:
    package_manager: str | None = None
    package_file: str | None = None
    frameworks: list[str] = field(default_factory=list)
    workspace_type: str = "single"


@dataclass
class ProjectDetection:
    root: Path
    tooling: ProjectTooling
    source_dirs: list[str]
    test_dirs: list[str]


def detect_project_tooling(root: Path, ignore_patterns: list[str]) -> ProjectDetection:
    root = root.resolve()
    package_manager: str | None = None
    package_file: str | None = None
    frameworks: list[str] = []
    workspace_type = "single"

    def check_file(relative_path: str) -> bool:
        return (root / relative_path).exists()

    if check_file("pnpm-lock.yaml"):
        package_manager = "pnpm"
        package_file = "package.json" if check_file("package.json") else None
    elif check_file("yarn.lock"):
        package_manager = "yarn"
        package_file = "package.json" if check_file("package.json") else None
    elif check_file("package-lock.json"):
        package_manager = "npm"
        package_file = "package.json" if check_file("package.json") else None
    elif check_file("package.json"):
        package_manager = "npm"
        package_file = "package.json"
    elif check_file("uv.lock"):
        package_manager = "uv"
        package_file = "pyproject.toml" if check_file("pyproject.toml") else None
    elif check_file("poetry.lock"):
        package_manager = "poetry"
        package_file = "pyproject.toml" if check_file("pyproject.toml") else None
    elif check_file("Pipfile.lock"):
        package_manager = "pipenv"
        package_file = "Pipfile"
    elif check_file("requirements.txt"):
        package_manager = "pip"
    elif check_file("pyproject.toml"):
        package_manager = "unknown"
        package_file = "pyproject.toml"
    elif check_file("Cargo.lock"):
        package_manager = "cargo"
        package_file = "Cargo.toml" if check_file("Cargo.toml") else None
    elif check_file("Cargo.toml"):
        package_manager = "cargo"
        package_file = "Cargo.toml"
    elif check_file("go.mod"):
        package_manager = "go"
        package_file = "go.mod"

    package_json_path = root / "package.json"
    package_json_allowed = package_json_path.exists() and not should_ignore(
        str(package_json_path.relative_to(root)), ignore_patterns
    )

    if check_file("pnpm-workspace.yaml") or (
        package_json_allowed and _has_string(package_json_path, "workspaces")
    ):
        workspace_type = "monorepo"

    frameworks = _detect_frameworks(root, ignore_patterns)

    source_dirs = _detect_directories(root, ignore_patterns, {"src", "lib", "app"})
    test_dirs = _detect_directories(root, ignore_patterns, {"tests", "test", "__tests__"})

    tooling = ProjectTooling(
        package_manager=package_manager,
        package_file=package_file,
        frameworks=frameworks,
        workspace_type=workspace_type,
    )
    return ProjectDetection(
        root=root,
        tooling=tooling,
        source_dirs=source_dirs,
        test_dirs=test_dirs,
    )


def detect_tooling(root: Path, ignore_patterns: list[str]) -> ProjectDetection:
    return detect_project_tooling(root, ignore_patterns)


def _detect_frameworks(root: Path, ignore_patterns: list[str]) -> list[str]:
    frameworks: list[str] = []
    package_json = root / "package.json"
    pyproject = root / "pyproject.toml"

    if package_json.exists() and not should_ignore(
        str(package_json.relative_to(root)), ignore_patterns
    ):
        content = _safe_read_text(package_json)
        if content:
            if "react" in content:
                frameworks.append("react")
            if "next" in content:
                frameworks.append("next")
            if "vue" in content:
                frameworks.append("vue")
            if "svelte" in content:
                frameworks.append("svelte")
            if "vite" in content:
                frameworks.append("vite")
            if "express" in content:
                frameworks.append("express")

    if pyproject.exists() and not should_ignore(
        str(pyproject.relative_to(root)), ignore_patterns
    ):
        content = _safe_read_text(pyproject)
        if content:
            if "pytest" in content:
                frameworks.append("pytest")
            if "fastapi" in content:
                frameworks.append("fastapi")
            if "django" in content:
                frameworks.append("django")
            if "flask" in content:
                frameworks.append("flask")

    return sorted(set(frameworks))


def _detect_directories(
    root: Path, ignore_patterns: list[str], candidates: set[str]
) -> list[str]:
    found: list[str] = []
    for name in sorted(candidates):
        path = root / name
        if not path.exists():
            continue
        if should_ignore_dir(name, ignore_patterns):
            continue
        found.append(name)
    return found


def _safe_read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ""


def _has_string(path: Path, value: str) -> bool:
    content = _safe_read_text(path)
    return value in content
