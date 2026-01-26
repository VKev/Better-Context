"""
Project primitive and detection utilities.

This module provides the Project primitive and utilities for detecting
project boundaries and configuration.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, List, Any

from .base import Primitive, BaseFactory
from ..config import load_config, Config

@dataclass
class Project(Primitive):
    """Represents a project analysis target."""
    
    # Project-specific metadata
    config: Config = field(default_factory=Config)
    root_path: Path = field(default_factory=Path)
    
    def __post_init__(self):
        """Initialize path-based fields."""
        if not self.path and self.root_path:
            self.path = str(self.root_path)
            
    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary representation."""
        data = super().to_dict()
        data.update({
            "config": {
                k: v for k, v in self.config.__dict__.items()
                if not k.startswith('_')
            },
            "root_path": str(self.root_path)
        })
        return data

class ProjectFactory(BaseFactory):
    """Factory for creating Project primitives."""
    
    def create(self, path: str | Path, **kwargs) -> Project:
        """Create a Project primitive from a path.
        
        Args:
            path: Project root path
            **kwargs: Additional primitive attributes
            
        Returns:
            Initialized Project primitive
        """
        root = Path(path).resolve()
        
        # Load configuration
        config_path = kwargs.get('config_path')
        config = load_config(root, config_path)
        
        return Project(
            id=f"project:{root.name}",
            type="project",
            name=root.name,
            path=str(root),
            root_path=root,
            config=config,
            **{k: v for k, v in kwargs.items() if k != 'config_path'}
        )

def find_project_root(start_path: Path | str) -> Path:
    """Find the project root by looking for markers.
    
    Markers checked (in order):
    1. .ctx.json
    2. .git directory
    3. pyproject.toml
    4. setup.py
    5. package.json
    
    Args:
        start_path: Path to start searching from
        
    Returns:
        Detected project root path
    """
    current = Path(start_path).resolve()
    if current.is_file():
        current = current.parent
        
    # Walk up the tree
    for parent in [current] + list(current.parents):
        # Check for better-context config
        if (parent / ".ctx.json").exists():
            return parent
            
        # Check for git
        if (parent / ".git").exists():
            return parent
            
        # Check for common project markers
        if any((parent / marker).exists() for marker in [
            "pyproject.toml",
            "setup.py",
            "package.json",
            "go.mod",
            "Cargo.toml"
        ]):
            return parent
            
    # Fallback to current directory
    return Path(start_path).resolve()
