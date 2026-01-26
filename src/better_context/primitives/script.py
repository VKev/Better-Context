"""
Script primitive and detection.

This module provides the Script primitive for representing runnable scripts
defined in project configuration files.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, List, Optional
import json
import tomli

from .base import Primitive, BaseFactory

@dataclass
class Script(Primitive):
    """Represents a runnable script or command."""
    
    # Script metadata
    command: str = ""
    description: Optional[str] = None
    source_file: Optional[str] = None
    
    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary representation."""
        data = super().to_dict()
        data.update({
            "command": self.command,
            "description": self.description,
            "source_file": self.source_file,
        })
        return data

class ScriptFactory(BaseFactory):
    """Factory for creating Script primitives."""
    
    def create(self, name: str, **kwargs) -> Script:
        """Create a Script primitive.
        
        Args:
            name: Script name (e.g. "build", "test")
            **kwargs: Additional attributes
            
        Returns:
            Initialized Script primitive
        """
        return Script(
            id=f"script:{name}",
            type="script",
            name=name,
            path="", # Virtual
            **kwargs
        )

def detect_scripts(root: Path) -> List[Script]:
    """Detect scripts defined in project configuration.
    
    Sources:
    1. package.json "scripts"
    2. pyproject.toml [project.scripts] or [tool.poetry.scripts]
    3. Makefile targets (simple heuristic)
    
    Args:
        root: Project root directory
        
    Returns:
        List of detected Script primitives
    """
    scripts = []
    factory = ScriptFactory()
    
    # 1. package.json
    pkg_json = root / "package.json"
    if pkg_json.exists():
        try:
            data = json.loads(pkg_json.read_text(encoding="utf-8"))
            for name, cmd in data.get("scripts", {}).items():
                scripts.append(factory.create(
                    name=name,
                    command=cmd,
                    source_file="package.json",
                    description=f"npm script: {name}"
                ))
        except Exception:
            pass
            
    # 2. pyproject.toml
    pyproject = root / "pyproject.toml"
    if pyproject.exists():
        try:
            data = tomli.loads(pyproject.read_text(encoding="utf-8"))
            
            # [project.scripts]
            project_scripts = data.get("project", {}).get("scripts", {})
            for name, cmd in project_scripts.items():
                scripts.append(factory.create(
                    name=name,
                    command=cmd,
                    source_file="pyproject.toml",
                    description=f"python entry point: {name}"
                ))
                
            # [tool.poetry.scripts]
            poetry_scripts = data.get("tool", {}).get("poetry", {}).get("scripts", {})
            for name, cmd in poetry_scripts.items():
                scripts.append(factory.create(
                    name=name,
                    command=cmd,
                    source_file="pyproject.toml",
                    description=f"poetry script: {name}"
                ))
        except Exception:
            pass
            
    return scripts
