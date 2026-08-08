"""Context staleness detection for better-context.

Provides hash-based verification to detect when AGENTS.md files are stale
and need regeneration. This enables agents to trust generated context
by verifying it matches current source files.

Usage:
    from better_context.staleness import check_staleness, load_staleness_info
    
    result = check_staleness(Path("./project"))
    if result.is_stale:
        print(f"Context is stale: {len(result.changed)} files changed")
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Dict, List, Optional, Any

from .scanner import walk_repository, compute_file_hash
from .config import load_config


# Staleness info file name (stored alongside manifest)
STALENESS_FILE_NAME = "staleness.json"

# Pattern to extract source hash from AGENTS.md footer
SOURCE_HASH_PATTERN = re.compile(r'\*Source hash: ([a-f0-9]+)\*')


@dataclass
class StalenessInfo:
    """Staleness tracking info stored when context is generated.
    
    This is saved to .better-context/staleness.json and contains
    all the hashes needed to verify freshness.
    """
    
    source_hash: str  # Combined hash of all source files
    file_hashes: Dict[str, str]  # Per-file content hashes (path -> hash)
    generated_at: str  # ISO 8601 timestamp
    file_count: int  # Number of files when generated
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to JSON-serializable dict."""
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "StalenessInfo":
        """Create from JSON dict."""
        return cls(
            source_hash=data.get("source_hash", ""),
            file_hashes=data.get("file_hashes", {}),
            generated_at=data.get("generated_at", ""),
            file_count=data.get("file_count", 0),
        )


@dataclass
class StalenessResult:
    """Result of staleness check.
    
    Provides detailed information about what files have changed
    since context was generated.
    """
    
    is_stale: bool  # True if any files changed
    source_hash: str  # Current combined hash
    previous_hash: str  # Hash when context was generated
    changed: List[str] = field(default_factory=list)  # Modified files
    added: List[str] = field(default_factory=list)  # New files
    removed: List[str] = field(default_factory=list)  # Deleted files
    
    @property
    def total_changes(self) -> int:
        """Total number of file changes."""
        return len(self.changed) + len(self.added) + len(self.removed)
    
    @property
    def summary(self) -> str:
        """Human-readable summary of changes."""
        if not self.is_stale:
            return f"Context is up-to-date (source hash: {self.source_hash[:12]})"
        
        parts = []
        if self.changed:
            parts.append(f"{len(self.changed)} modified")
        if self.added:
            parts.append(f"{len(self.added)} added")
        if self.removed:
            parts.append(f"{len(self.removed)} removed")
        
        return f"Context is STALE - {', '.join(parts)}"


def compute_source_hash(file_hashes: Dict[str, str]) -> str:
    """Compute combined hash of all source files.
    
    Creates a deterministic hash by sorting file paths and
    hashing the concatenated path:hash pairs.
    
    Args:
        file_hashes: Dict mapping file paths to their content hashes
    
    Returns:
        16-character hex hash representing all source files
    """
    if not file_hashes:
        return "0" * 16
    
    # Sort by path for determinism
    sorted_items = sorted(file_hashes.items())
    
    # Create combined string: path1:hash1|path2:hash2|...
    combined = "|".join(f"{path}:{hash_}" for path, hash_ in sorted_items)
    
    return hashlib.sha256(combined.encode()).hexdigest()[:16]


def collect_current_hashes(
    root: Path,
    config_path: Optional[Path] = None,
) -> Dict[str, str]:
    """Collect content hashes for all source files in a project.
    
    Uses the same scanning logic as the main analysis pipeline.
    Excludes AGENTS.md files since they are our output, not input.
    
    Args:
        root: Project root directory
        config_path: Optional path to config file
    
    Returns:
        Dict mapping relative file paths to their content hashes
    """
    config = load_config(root, config_path)
    
    inventory = walk_repository(
        root,
        max_file_size_kb=config.max_file_size_kb,
    )
    
    # Exclude AGENTS.md files (our output, not source files)
    return {
        f.path: f.content_hash
        for f in inventory.files
        if not f.path.endswith("AGENTS.md")
    }


def check_staleness(
    root: Path,
    config_path: Optional[Path] = None,
) -> StalenessResult:
    """Check if generated context is stale relative to current source files.
    
    Compares current file hashes against those stored when context
    was last generated.
    
    Args:
        root: Project root directory
        config_path: Optional path to config file
    
    Returns:
        StalenessResult with detailed change information
    """
    root = root.resolve()
    
    # Load staleness info from previous generation
    staleness_info = load_staleness_info(root)
    if staleness_info is None:
        # No staleness info - treat as completely new
        current_hashes = collect_current_hashes(root, config_path)
        current_source_hash = compute_source_hash(current_hashes)
        
        return StalenessResult(
            is_stale=True,
            source_hash=current_source_hash,
            previous_hash="",
            added=sorted(current_hashes.keys()),
        )
    
    # Collect current hashes
    current_hashes = collect_current_hashes(root, config_path)
    current_source_hash = compute_source_hash(current_hashes)
    
    # Quick check: if source hashes match, nothing changed
    if current_source_hash == staleness_info.source_hash:
        return StalenessResult(
            is_stale=False,
            source_hash=current_source_hash,
            previous_hash=staleness_info.source_hash,
        )
    
    # Detailed diff to find what changed
    previous_hashes = staleness_info.file_hashes
    
    changed: List[str] = []
    added: List[str] = []
    removed: List[str] = []
    
    # Find modified and removed files
    for path, old_hash in previous_hashes.items():
        if path not in current_hashes:
            removed.append(path)
        elif current_hashes[path] != old_hash:
            changed.append(path)
    
    # Find added files
    for path in current_hashes:
        if path not in previous_hashes:
            added.append(path)
    
    return StalenessResult(
        is_stale=True,
        source_hash=current_source_hash,
        previous_hash=staleness_info.source_hash,
        changed=sorted(changed),
        added=sorted(added),
        removed=sorted(removed),
    )


def save_staleness_info(
    root: Path,
    file_hashes: Dict[str, str],
    generated_at: str,
    output_dir: Optional[str] = None,
) -> Path:
    """Save staleness tracking info after generating context.
    
    Called after AGENTS.md generation to record the state of
    source files for future staleness checks.
    
    Args:
        root: Project root directory
        file_hashes: Dict mapping file paths to content hashes
        generated_at: ISO 8601 timestamp of generation
        output_dir: Optional output directory name (default: .better-context)
    
    Returns:
        Path to the saved staleness file
    """
    root = root.resolve()
    output_dir_name = output_dir or ".better-context"
    staleness_path = root / output_dir_name / STALENESS_FILE_NAME
    
    info = StalenessInfo(
        source_hash=compute_source_hash(file_hashes),
        file_hashes=file_hashes,
        generated_at=generated_at,
        file_count=len(file_hashes),
    )
    
    staleness_path.parent.mkdir(parents=True, exist_ok=True)
    staleness_path.write_text(
        json.dumps(info.to_dict(), indent=2),
        encoding="utf-8",
    )
    
    return staleness_path


def load_staleness_info(root: Path, output_dir: Optional[str] = None) -> Optional[StalenessInfo]:
    """Load staleness info from a project.
    
    Args:
        root: Project root directory
        output_dir: Optional output directory name (default: .better-context)
    
    Returns:
        StalenessInfo if found, None otherwise
    """
    root = root.resolve()
    output_dir_name = output_dir or ".better-context"
    staleness_path = root / output_dir_name / STALENESS_FILE_NAME
    
    if not staleness_path.exists():
        return None
    
    try:
        data = json.loads(staleness_path.read_text(encoding="utf-8"))
        return StalenessInfo.from_dict(data)
    except (json.JSONDecodeError, KeyError, TypeError):
        return None


def get_staleness_footer(source_hash: str, generated_at: str) -> str:
    """Generate the staleness footer for AGENTS.md files.
    
    Args:
        source_hash: Combined source hash
        generated_at: ISO 8601 timestamp
    
    Returns:
        Markdown footer string with staleness info
    """
    return f"""---
*Generated by better-context-unity at {generated_at}*
*Source hash: {source_hash}*
*Verify: `better-context-unity verify`*
"""


def extract_source_hash_from_agents_md(agents_md_path: Path) -> Optional[str]:
    """Extract the source hash from an AGENTS.md file.
    
    Args:
        agents_md_path: Path to AGENTS.md file
    
    Returns:
        Source hash if found, None otherwise
    """
    if not agents_md_path.exists():
        return None
    
    try:
        content = agents_md_path.read_text(encoding="utf-8")
        match = SOURCE_HASH_PATTERN.search(content)
        if match:
            return match.group(1)
    except Exception:
        pass
    
    return None


def format_staleness_report(result: StalenessResult, verbose: bool = False) -> str:
    """Format a staleness result as a human-readable report.
    
    Args:
        result: StalenessResult from check_staleness
        verbose: Whether to include detailed file lists
    
    Returns:
        Formatted report string
    """
    lines = []
    
    if result.is_stale:
        lines.append(f"⚠ {result.summary}")
        lines.append("")
        
        if verbose or result.total_changes <= 10:
            if result.changed:
                lines.append("Modified files:")
                for path in result.changed[:20]:
                    lines.append(f"  - {path}")
                if len(result.changed) > 20:
                    lines.append(f"  ... and {len(result.changed) - 20} more")
            
            if result.added:
                lines.append("Added files:")
                for path in result.added[:20]:
                    lines.append(f"  + {path}")
                if len(result.added) > 20:
                    lines.append(f"  ... and {len(result.added) - 20} more")
            
            if result.removed:
                lines.append("Removed files:")
                for path in result.removed[:20]:
                    lines.append(f"  - {path}")
                if len(result.removed) > 20:
                    lines.append(f"  ... and {len(result.removed) - 20} more")
        
        lines.append("")
        lines.append("Run 'better-context-unity agents' to update.")
    else:
        lines.append(f"✓ {result.summary}")
    
    return "\n".join(lines)


# Export public API
__all__ = [
    "STALENESS_FILE_NAME",
    "StalenessInfo",
    "StalenessResult",
    "compute_source_hash",
    "collect_current_hashes",
    "check_staleness",
    "save_staleness_info",
    "load_staleness_info",
    "get_staleness_footer",
    "extract_source_hash_from_agents_md",
    "format_staleness_report",
]
