"""Scripts primitive.

Extracts available commands from project configuration files.
"""

from __future__ import annotations

import json
try:
    import tomllib
except ImportError:
    try:
        import tomli as tomllib
    except ImportError:
        tomllib = None

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Any, Optional


@dataclass
class ScriptEntry:
    """Information about a runnable script."""
    name: str
    command: str
    run_as: str  # e.g. "npm run test" or "uv run pytest"
    source: str  # e.g. "package.json"

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "command": self.command,
            "run_as": self.run_as,
            "source": self.source,
        }


@dataclass
class ScriptsResult:
    """Result of scripts analysis."""
    package_file: Optional[str]
    package_manager: Optional[str]
    scripts: List[ScriptEntry]
    golden_commands: Dict[str, str]

    def to_dict(self) -> dict[str, object]:
        return {
            "package_file": self.package_file,
            "package_manager": self.package_manager,
            "scripts": [s.to_dict() for s in self.scripts],
            "golden_commands": self.golden_commands,
        }


def get_scripts(root: Path) -> ScriptsResult:
    """Alias for analyze_scripts."""
    return analyze_scripts(root)


def analyze_scripts(root: Path) -> ScriptsResult:
    """Analyze available scripts and commands.
    
    Args:
        root: Root directory to analyze
        
    Returns:
        ScriptsResult containing scripts and golden commands
    """
    root = root.resolve()
    
    scripts: List[ScriptEntry] = []
    golden_commands: Dict[str, str] = {}
    package_file = None
    package_manager = None
    
    # Check for pyproject.toml
    pyproject = root / "pyproject.toml"
    if pyproject.exists():
        package_file = "pyproject.toml"
        # Determine package manager
        if (root / "uv.lock").exists():
            package_manager = "uv"
        elif (root / "poetry.lock").exists():
            package_manager = "poetry"
        elif (root / "pdm.lock").exists():
            package_manager = "pdm"
        else:
            package_manager = "pip"
            
        try:
            content = tomllib.loads(pyproject.read_text(encoding="utf-8"))
            
            # Detect golden commands based on tools
            if "tool" in content:
                tools = content["tool"]
                
                # Test command
                if "pytest" in tools:
                    cmd = "pytest"
                    if package_manager == "uv":
                        cmd = "uv run pytest"
                    elif package_manager == "poetry":
                        cmd = "poetry run pytest"
                    elif package_manager == "pdm":
                        cmd = "pdm run pytest"
                    golden_commands["test"] = cmd
                    
                # Lint/Format commands
                if "ruff" in tools:
                    cmd_check = "ruff check"
                    cmd_fmt = "ruff format"
                    if package_manager and package_manager != "pip":
                        cmd_check = f"{package_manager} run {cmd_check}"
                        cmd_fmt = f"{package_manager} run {cmd_fmt}"
                    golden_commands["lint"] = cmd_check
                    golden_commands["format"] = cmd_fmt
                    
                # Type check
                if "mypy" in tools:
                    cmd = "mypy ."
                    if package_manager and package_manager != "pip":
                        cmd = f"{package_manager} run {cmd}"
                    golden_commands["typecheck"] = cmd
                    
            # Extract scripts if defined (e.g. poetry scripts or project.scripts)
            # Note: standard pyproject.toml [project.scripts] are entry points, not run scripts
            # But tools like hatch/pdm might have script sections
            
        except Exception:
            pass
            
    # Check for package.json
    pkg_json = root / "package.json"
    if pkg_json.exists():
        # Prefer package.json if pyproject didn't give much (or it's a mixed repo)
        # But if we found Python structure, maybe this is secondary.
        # For now, just overwrite if found, assuming Node if package.json exists
        # In mixed repos, we might want to return both?
        
        try:
            content = json.loads(pkg_json.read_text(encoding="utf-8"))
            
            # Determine package manager
            if (root / "pnpm-lock.yaml").exists():
                pm = "pnpm"
            elif (root / "yarn.lock").exists():
                pm = "yarn"
            elif (root / "bun.lockb").exists():
                pm = "bun"
            else:
                pm = "npm"
            
            if not package_manager: # Only override if not already set (prefer Python?)
                package_manager = pm
                package_file = "package.json"
            
            if "scripts" in content:
                for name, cmd in content["scripts"].items():
                    run_cmd = f"{pm} run {name}" if pm != "npm" or name != "start" and name != "test" else f"{pm} {name}"
                    if pm == "npm" and name not in ("start", "test"):
                        run_cmd = f"npm run {name}"
                        
                    scripts.append(ScriptEntry(
                        name=name,
                        command=cmd,
                        run_as=run_cmd,
                        source="package.json"
                    ))
                    
                    # Map common scripts to golden commands
                    if name in ("test", "build", "start", "lint", "format", "clean"):
                        golden_commands[name] = run_cmd
                        
        except Exception:
            pass
            
    # Check for Makefile
    makefile = root / "Makefile"
    if makefile.exists():
        try:
            content = makefile.read_text(encoding="utf-8")
            targets = []
            for line in content.splitlines():
                if line.startswith(('.PHONY:', 'PHONY:')):
                    continue
                if ':' in line and not line.startswith(('\t', ' ', '#', '.')):
                    target = line.split(':')[0].strip()
                    if target and '%' not in target:
                        scripts.append(ScriptEntry(
                            name=target,
                            command=f"make {target}",
                            run_as=f"make {target}",
                            source="Makefile"
                        ))
                        # Golden mappings
                        if target in ("test", "build", "install", "clean", "lint", "format"):
                            # Prefer package/tool specific commands over make? 
                            # Or prefer make if it wraps them?
                            # Let's prefer make as it's often the uniform interface
                            golden_commands[target] = f"make {target}"
        except Exception:
            pass

    # Sort scripts
    scripts.sort(key=lambda x: x.name)
    
    return ScriptsResult(
        package_file=package_file,
        package_manager=package_manager,
        scripts=scripts,
        golden_commands=golden_commands
    )
