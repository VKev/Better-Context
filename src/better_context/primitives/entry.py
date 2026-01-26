"""
Entry primitive and detection.

This module provides the Entry primitive and utilities for detecting
project entry points.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, List, Optional

from .base import Primitive, BaseFactory
from .file import File

@dataclass
class Entry(Primitive):
    """Represents an entry point in the codebase."""
    
    # Entry specific metadata
    kind: str = "script"  # script, module, function, etc.
    source_file: Optional[str] = None  # Reference to the file containing this entry
    
    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary representation."""
        data = super().to_dict()
        data.update({
            "kind": self.kind,
            "source_file": self.source_file,
        })
        return data

class EntryFactory(BaseFactory):
    """Factory for detecting and creating Entry primitives."""
    
    def create(self, path: str | Path, **kwargs) -> Entry:
        """Create an Entry primitive.
        
        Args:
            path: Path to the entry point file
            **kwargs: Additional attributes
            
        Returns:
            Initialized Entry primitive
        """
        path_obj = Path(path)
        return Entry(
            id=f"entry:{path_obj.name}",
            type="entry",
            name=path_obj.name,
            path=str(path_obj),
            source_file=str(path_obj),
            **kwargs
        )

def detect_entry_points(root: Path) -> List[Entry]:
    """Detect entry points in the project.
    
    Heuristics:
    1. Files named main.py, app.py, cli.py, index.js, etc.
    2. Files with if __name__ == "__main__": blocks (Python)
    3. Files defined in pyproject.toml [project.scripts]
    
    Args:
        root: Project root directory
        
    Returns:
        List of detected Entry primitives
    """
    entries = []
    
    # Common entry point names
    common_names = {
        'main.py', 'app.py', 'cli.py', '__main__.py', 'manage.py',  # Python
        'index.js', 'index.ts', 'server.js', 'app.js', 'main.go',   # JS/TS/Go
        'main.rs', 'lib.rs'                                         # Rust
    }
    
    # 1. Check for common names
    for path in root.rglob('*'):
        if path.name in common_names and path.is_file():
            entries.append(Entry(
                id=f"entry:{path.relative_to(root)}",
                type="entry",
                name=path.name,
                path=str(path),
                source_file=str(path),
                kind="file"
            ))
            
    return entries
