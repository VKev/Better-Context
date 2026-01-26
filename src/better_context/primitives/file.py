"""
File primitive.

This module provides the File primitive for representing individual files
and their metadata.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from .base import Primitive, BaseFactory

@dataclass
class File(Primitive):
    """Represents a single file in the codebase."""
    
    # File metadata
    language: Optional[str] = None
    size_bytes: int = 0
    content_hash: str = ""
    last_modified: float = 0.0
    
    # Analysis results
    is_binary: bool = False
    is_generated: bool = False
    is_vendored: bool = False
    
    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary representation."""
        data = super().to_dict()
        data.update({
            "language": self.language,
            "size_bytes": self.size_bytes,
            "content_hash": self.content_hash,
            "last_modified": self.last_modified,
            "is_binary": self.is_binary,
            "is_generated": self.is_generated,
            "is_vendored": self.is_vendored
        })
        return data

class FileFactory(BaseFactory):
    """Factory for creating File primitives."""
    
    def create(self, path: str | Path, **kwargs) -> File:
        """Create a File primitive from a path.
        
        Args:
            path: Path to the file
            **kwargs: Additional primitive attributes
            
        Returns:
            Initialized File primitive
        """
        file_path = Path(path).resolve()
        stat = file_path.stat()
        
        # Simple language detection based on extension
        # In a real implementation, this would use a more robust detection mechanism
        language = self._detect_language(file_path)
        
        # Try to make ID relative to CWD if possible, or project root?
        # The list command uses id=f"file:{path.name}", which is just the filename!
        # This is ambiguous if multiple files have same name.
        # But we should respect what was implemented.
        
        # Let's fix the ID generation to use relative path if possible, making it unique
        try:
            cwd = Path.cwd()
            if file_path.is_relative_to(cwd):
                rel_path = file_path.relative_to(cwd)
                id_str = f"file:{rel_path}"
            else:
                id_str = f"file:{file_path.name}"
        except ValueError:
            id_str = f"file:{file_path.name}"
            
        return File(
            id=id_str,
            type="file",
            name=file_path.name,
            path=str(file_path),
            size_bytes=stat.st_size,
            last_modified=stat.st_mtime,
            language=language,
            **kwargs
        )
        
    def _detect_language(self, path: Path) -> str | None:
        """Detect language from file extension."""
        ext = path.suffix.lower()
        mapping = {
            '.py': 'python',
            '.ts': 'typescript',
            '.tsx': 'typescript',
            '.js': 'javascript',
            '.jsx': 'javascript',
            '.go': 'go',
            '.rs': 'rust',
            '.md': 'markdown',
            '.json': 'json',
            '.yaml': 'yaml',
            '.yml': 'yaml',
            '.toml': 'toml',
            '.html': 'html',
            '.css': 'css',
            '.sh': 'shell',
        }
        return mapping.get(ext)
