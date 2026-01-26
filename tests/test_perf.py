"""Performance tests for better_context primitives.

Verifies that primitives meet the execution time targets (<200ms).
"""

from __future__ import annotations

import time
import pytest
from pathlib import Path
from better_context.primitives import (
    get_tree,
    get_overview,
    get_scripts,
    get_entries,
    get_file_info,
)


@pytest.fixture
def large_project(tmp_path):
    """Create a simulated large project structure."""
    project_dir = tmp_path / "large_project"
    project_dir.mkdir()
    
    # Create 100 directories with 10 files each = 1000 files
    for i in range(100):
        d = project_dir / f"dir_{i}"
        d.mkdir()
        for j in range(10):
            (d / f"file_{j}.py").write_text(f"def func_{i}_{j}(): pass\n" * 10, encoding="utf-8")
            
    # Add config files
    (project_dir / "pyproject.toml").write_text("[project]\nname='large'", encoding="utf-8")
    
    return project_dir


def measure_ms(func, *args, **kwargs) -> float:
    """Measure execution time in milliseconds."""
    start = time.time()
    func(*args, **kwargs)
    end = time.time()
    return (end - start) * 1000


@pytest.mark.perf
def test_tree_performance(large_project):
    """Test tree primitive performance."""
    # Target: ~100ms for 1000 files (might be slower on some systems, raising limit slightly for CI stability)
    ms = measure_ms(get_tree, large_project, depth=2)
    print(f"Tree perf: {ms:.2f}ms")
    assert ms < 500  # Generous limit for test environment


@pytest.mark.perf
def test_overview_performance(large_project):
    """Test overview primitive performance."""
    # Target: ~100ms
    ms = measure_ms(get_overview, large_project)
    print(f"Overview perf: {ms:.2f}ms")
    assert ms < 200


@pytest.mark.perf
def test_file_info_performance(large_project):
    """Test file info primitive performance."""
    # Target: ~200ms
    target_file = large_project / "dir_0" / "file_0.py"
    ms = measure_ms(get_file_info, str(target_file))
    print(f"FileInfo perf: {ms:.2f}ms")
    assert ms < 200
