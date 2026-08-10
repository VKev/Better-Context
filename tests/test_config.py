"""Tests for config module."""

from pathlib import Path

from better_context.config import Config, load_config, merge_configs, validate_config


def test_default_config():
    """Test default configuration values."""
    config = Config()
    assert config.max_file_size_kb == 500
    assert config.pagerank_damping == 0.85
    assert config.generate_agents_md is True
    assert config.unity_asset_scope == "project-owned"
    assert config.unity_agents_asset_limit == 12
    assert config.unity_agents_object_limit == 8
    assert config.unity_editor_mode == "auto"
    assert config.unity_editor_required is False
    assert config.unity_editor_timeout_seconds == 300
    assert config.unity_editor_path is None


def test_merge_configs():
    """Test merging override dict into config."""
    base = Config()
    override = {"max_file_size_kb": 1000, "pagerank_damping": 0.9}
    merged = merge_configs(base, override)

    assert merged.max_file_size_kb == 1000
    assert merged.pagerank_damping == 0.9
    assert merged.generate_agents_md is True  # Unchanged


def test_validate_config_valid():
    """Test validation of valid config."""
    config = Config()
    errors = validate_config(config)
    assert errors == []


def test_validate_config_invalid():
    """Test validation catches invalid values."""
    config = Config(max_file_size_kb=-1, pagerank_damping=2.0)
    errors = validate_config(config)

    assert len(errors) == 2
    assert any("max_file_size_kb" in e for e in errors)
    assert any("pagerank_damping" in e for e in errors)


def test_validate_unity_runtime_config():
    """Unity runtime scope and AGENTS.md limits have bounded values."""
    config = Config(
        unity_asset_scope="vendor-only",
        unity_agents_asset_limit=0,
        unity_agents_object_limit=-1,
        unity_editor_mode="invalid",
        unity_editor_required="yes",  # type: ignore[arg-type]
        unity_editor_timeout_seconds=0,
        unity_editor_path=42,  # type: ignore[arg-type]
    )

    errors = validate_config(config)

    assert any("unity_asset_scope" in error for error in errors)
    assert any("unity_agents_asset_limit" in error for error in errors)
    assert any("unity_agents_object_limit" in error for error in errors)
    assert any("unity_editor_mode" in error for error in errors)
    assert any("unity_editor_required" in error for error in errors)
    assert any("unity_editor_timeout_seconds" in error for error in errors)
    assert any("unity_editor_path" in error for error in errors)


def test_merge_unity_runtime_config():
    """Unity runtime settings can be overridden from .ctx.json."""
    merged = merge_configs(
        Config(),
        {
            "unity_asset_scope": "all",
            "unity_agents_asset_limit": 20,
            "unity_agents_object_limit": 10,
        },
    )

    assert merged.unity_asset_scope == "all"
    assert merged.unity_agents_asset_limit == 20
    assert merged.unity_agents_object_limit == 10
