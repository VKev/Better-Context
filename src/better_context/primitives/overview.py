"""Overview primitive.

Detects high-level project information (type, framework, package manager).
"""

from __future__ import annotations

try:
    import tomllib
except ImportError:
    try:
        import tomli as tomllib
    except ImportError:
        tomllib = None
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Dict, Any


@dataclass
class OverviewResult:
    """Result of project overview analysis."""
    project_name: str
    primary_language: Optional[str]
    package_manager: Optional[str]
    package_file: Optional[str]
    frameworks: List[str]
    workspace_type: str  # "single" or "monorepo"
    source_dirs: List[str]
    test_dirs: List[str]

    def to_dict(self) -> dict[str, object]:
        return {
            "project_name": self.project_name,
            "primary_language": self.primary_language,
            "package_manager": self.package_manager,
            "package_file": self.package_file,
            "frameworks": self.frameworks,
            "workspace_type": self.workspace_type,
            "source_dirs": self.source_dirs,
            "test_dirs": self.test_dirs,
        }


def get_overview(root: Path) -> OverviewResult:
    """Alias for analyze_overview."""
    return analyze_overview(root)


def analyze_overview(root: Path) -> OverviewResult:
    """Analyze project overview.
    
    Args:
        root: Root directory to analyze
        
    Returns:
        OverviewResult containing detected project info
    """
    root = root.resolve()
    project_name = root.name
    primary_language = None
    package_manager = None
    package_file = None
    frameworks: List[str] = []
    workspace_type = "single"
    source_dirs: List[str] = []
    test_dirs: List[str] = []

    # Unity projects are identified from authored project files, never generated
    # .csproj files. This check runs first so incidental Python/Node tooling does
    # not replace the actual project type.
    is_unity = (
        (root / "Assets").is_dir()
        and (root / "ProjectSettings" / "ProjectVersion.txt").is_file()
    )
    if is_unity:
        primary_language = "csharp"
        package_manager = "unity-package-manager"
        package_file = "Packages/manifest.json"
        frameworks.append("unity")
        source_dirs.append("Assets")
        if (root / "Packages").is_dir():
            source_dirs.append("Packages")
        for candidate in ("Assets/Tests", "Assets/Editor/Tests"):
            if (root / candidate).is_dir():
                test_dirs.append(candidate)
    
    # 1. Detect Python
    pyproject = root / "pyproject.toml"
    setup_py = root / "setup.py"
    requirements = root / "requirements.txt"
    
    if pyproject.exists() and not primary_language:
        primary_language = "python"
        package_file = "pyproject.toml"
        try:
            content = tomllib.loads(pyproject.read_text(encoding="utf-8"))
            if "project" in content and "name" in content["project"]:
                project_name = content["project"]["name"]
            elif "tool" in content and "poetry" in content["tool"]:
                project_name = content["tool"]["poetry"].get("name", project_name)
                
            # Detect frameworks/libraries
            deps = []
            if "project" in content:
                deps.extend(content["project"].get("dependencies", []))
                deps.extend(content["project"].get("optional-dependencies", {}).values())
            if "tool" in content and "poetry" in content["tool"]:
                deps.extend(content["tool"]["poetry"].get("dependencies", {}).keys())
                
            deps_str = str(deps).lower()
            if "django" in deps_str: frameworks.append("django")
            if "flask" in deps_str: frameworks.append("flask")
            if "fastapi" in deps_str: frameworks.append("fastapi")
            if "pytest" in deps_str: frameworks.append("pytest")
            
        except Exception:
            pass
            
        # Detect package manager
        if (root / "uv.lock").exists(): package_manager = "uv"
        elif (root / "poetry.lock").exists(): package_manager = "poetry"
        elif (root / "pdm.lock").exists(): package_manager = "pdm"
        elif (root / "Pipfile").exists(): package_manager = "pipenv"
        else: package_manager = "pip"
        
    elif setup_py.exists() or requirements.exists():
        primary_language = "python"
        package_file = "setup.py" if setup_py.exists() else "requirements.txt"
        package_manager = "pip"

    # 2. Detect Node.js (override python if package.json exists? or mixed?)
    pkg_json = root / "package.json"
    if pkg_json.exists():
        # If we already found python, maybe it's mixed. 
        # But usually package.json implies JS/TS context.
        # Let's verify file counts to determine *primary* language later if needed.
        # For now, if no python found, assume JS.
        if not primary_language:
            primary_language = "javascript" # Default, refine to TS later
            package_file = "package.json"
            
            try:
                content = json.loads(pkg_json.read_text(encoding="utf-8"))
                if "name" in content:
                    project_name = content["name"]
                    
                # Detect deps
                deps = {}
                deps.update(content.get("dependencies", {}))
                deps.update(content.get("devDependencies", {}))
                
                if "typescript" in deps:
                    primary_language = "typescript"
                
                if "react" in deps: frameworks.append("react")
                if "next" in deps: frameworks.append("next.js")
                if "vue" in deps: frameworks.append("vue")
                if "svelte" in deps: frameworks.append("svelte")
                if "express" in deps: frameworks.append("express")
                if "jest" in deps: frameworks.append("jest")
                if "vitest" in deps: frameworks.append("vitest")
                
                if "workspaces" in content:
                    workspace_type = "monorepo"
                    
            except Exception:
                pass
                
            # Detect package manager
            if (root / "pnpm-lock.yaml").exists(): package_manager = "pnpm"
            elif (root / "yarn.lock").exists(): package_manager = "yarn"
            elif (root / "bun.lockb").exists(): package_manager = "bun"
            else: package_manager = "npm"

    # 3. Detect Go
    go_mod = root / "go.mod"
    if go_mod.exists() and not primary_language:
        primary_language = "go"
        package_file = "go.mod"
        package_manager = "go"
        try:
            content = go_mod.read_text(encoding="utf-8")
            for line in content.splitlines():
                if line.startswith("module"):
                    project_name = line.split()[1].split('/')[-1]
                    break
        except Exception:
            pass

    # 4. Detect source/test dirs
    # Common conventions
    common_src = ["src", "lib", "app", "cmd", "pkg", "core"]
    common_test = ["tests", "test", "__tests__", "spec"]
    
    for d in common_src:
        if (root / d).is_dir():
            source_dirs.append(d)
            
    for d in common_test:
        if (root / d).is_dir():
            test_dirs.append(d)
            
    # Fallback if no src dir found but we have code in root
    if not source_dirs:
        # Check for files in root
        has_code = any(
            f.suffix in {'.py', '.js', '.ts', '.go', '.rs', '.cs'}
            for f in root.iterdir() 
            if f.is_file()
        )
        if has_code:
            source_dirs.append(".")

    return OverviewResult(
        project_name=project_name,
        primary_language=primary_language,
        package_manager=package_manager,
        package_file=package_file,
        frameworks=sorted(list(set(frameworks))),
        workspace_type=workspace_type,
        source_dirs=sorted(source_dirs),
        test_dirs=sorted(test_dirs)
    )
