"""Tests for config module."""

from pathlib import Path
from better_context.config import Config, load_config, merge_configs, validate_config


def test_default_config():
    """Test default configuration values."""
    config = Config()
    assert config.max_file_size_kb == 500
    assert config.pagerank_damping == 0.85
    assert config.generate_agents_md is True


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
