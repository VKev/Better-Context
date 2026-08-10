"""Configuration loader for better-context.

Loads settings from .ctx.json with sensible defaults and CLI override support.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class Config:
    """Configuration for better-context analysis."""

    # File Discovery
    include_patterns: list[str] = field(default_factory=lambda: ["**/*"])
    exclude_patterns: list[str] = field(default_factory=list)
    max_file_size_kb: int = 500

    # Chunking
    chunk_max_lines: int = 150
    chunk_min_lines: int = 10

    # Output
    output_dir: str = ".better-context"
    manifest_file: str = "manifest.json"
    generate_agents_md: bool = True

    # Analysis
    pagerank_damping: float = 0.85
    pagerank_iterations: int = 20

    # Unity runtime intelligence
    unity_asset_scope: str = "project-owned"
    unity_agents_asset_limit: int = 12
    unity_agents_object_limit: int = 8
    unity_editor_mode: str = "auto"
    unity_editor_required: bool = False
    unity_editor_timeout_seconds: int = 300
    unity_editor_path: str | None = None

    # Languages
    language_overrides: dict[str, str] = field(default_factory=dict)


def load_config(root: Path, config_path: Path | None = None) -> Config:
    """Load configuration from .ctx.json with fallback to defaults.

    Args:
        root: Project root directory
        config_path: Optional explicit path to config file

    Returns:
        Merged configuration
    """
    config = Config()

    # Determine config file path
    if config_path:
        ctx_file = config_path
    else:
        ctx_file = root / ".ctx.json"

    # Load if exists
    if ctx_file.exists():
        try:
            data = json.loads(ctx_file.read_text(encoding="utf-8"))
            config = merge_configs(config, data)
        except (json.JSONDecodeError, OSError) as e:
            print(f"Warning: Could not load config from {ctx_file}: {e}")

    return config


def merge_configs(base: Config, override: dict[str, Any]) -> Config:
    """Merge override dict into base config.

    Args:
        base: Base configuration
        override: Override values from file or CLI

    Returns:
        New config with merged values
    """
    # Get valid field names
    valid_fields = {f.name for f in base.__dataclass_fields__.values()}

    # Build new config dict
    merged = {}
    for name in valid_fields:
        if name in override:
            merged[name] = override[name]
        else:
            merged[name] = getattr(base, name)

    # Warn about unknown keys
    for key in override:
        if key not in valid_fields:
            print(f"Warning: Unknown config key '{key}' in .ctx.json")

    return Config(**merged)


def validate_config(config: Config) -> list[str]:
    """Validate configuration values.

    Args:
        config: Configuration to validate

    Returns:
        List of error messages (empty if valid)
    """
    errors = []

    if config.max_file_size_kb <= 0:
        errors.append("max_file_size_kb must be > 0")

    if not (0 < config.pagerank_damping < 1):
        errors.append("pagerank_damping must be between 0 and 1")

    if config.pagerank_iterations < 1:
        errors.append("pagerank_iterations must be >= 1")

    if config.chunk_max_lines < config.chunk_min_lines:
        errors.append("chunk_max_lines must be >= chunk_min_lines")

    if not isinstance(config.unity_asset_scope, str) or config.unity_asset_scope not in {
        "project-owned",
        "all",
    }:
        errors.append("unity_asset_scope must be 'project-owned' or 'all'")

    if (
        not isinstance(config.unity_agents_asset_limit, int)
        or isinstance(config.unity_agents_asset_limit, bool)
        or config.unity_agents_asset_limit <= 0
    ):
        errors.append("unity_agents_asset_limit must be a positive integer")

    if (
        not isinstance(config.unity_agents_object_limit, int)
        or isinstance(config.unity_agents_object_limit, bool)
        or config.unity_agents_object_limit <= 0
    ):
        errors.append("unity_agents_object_limit must be a positive integer")

    if config.unity_editor_mode not in {"auto", "open", "batch", "offline"}:
        errors.append("unity_editor_mode must be 'auto', 'open', 'batch', or 'offline'")

    if not isinstance(config.unity_editor_required, bool):
        errors.append("unity_editor_required must be a boolean")

    if (
        not isinstance(config.unity_editor_timeout_seconds, int)
        or isinstance(config.unity_editor_timeout_seconds, bool)
        or config.unity_editor_timeout_seconds <= 0
    ):
        errors.append("unity_editor_timeout_seconds must be a positive integer")

    if config.unity_editor_path is not None and not isinstance(config.unity_editor_path, str):
        errors.append("unity_editor_path must be a string or null")

    return errors
