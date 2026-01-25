"""Tests for focus mode (ego-centric context)."""

import pytest
from better_context.graph import build_graph_from_edges, DependencyGraph
from better_context.focus import (
    compute_focus_context,
    generate_focus_markdown,
    FocusConfig,
    FocusedFile,
    FocusedContext,
    _is_test_file,
    _is_type_file,
)


def test_is_test_file():
    """Test detection of test files."""
    assert _is_test_file("test_auth.py")
    assert _is_test_file("auth_test.py")
    assert _is_test_file("auth.test.ts")
    assert _is_test_file("auth.spec.js")
    assert _is_test_file("tests/auth.py")
    assert _is_test_file("src/test/auth.py")
    assert not _is_test_file("auth.py")
    assert not _is_test_file("testimony.py")
    assert not _is_test_file("contest.py")


def test_is_type_file():
    """Test detection of type definition files."""
    assert _is_type_file("types.py")
    assert _is_type_file("interfaces.ts")
    assert _is_type_file("models.py")
    assert _is_type_file("schemas.py")
    assert _is_type_file("foo.d.ts")
    assert _is_type_file("foo.pyi")
    assert _is_type_file("src/types/user.ts")
    assert not _is_type_file("auth.py")
    assert not _is_type_file("controller.ts")


def test_compute_focus_context_empty_graph():
    """Test focus context on empty graph."""
    graph = build_graph_from_edges([])
    centrality = {}
    
    context = compute_focus_context("missing.py", graph, centrality)
    
    assert context.focal_file == "missing.py"
    assert len(context.files) == 0
    assert context.total_files_in_neighborhood == 0


def test_compute_focus_context_single_file():
    """Test focus context with single node (no dependencies)."""
    graph = build_graph_from_edges([], nodes=["focal.py"])
    centrality = {"focal.py": 1.0}
    
    context = compute_focus_context("focal.py", graph, centrality)
    
    assert context.focal_file == "focal.py"
    assert len(context.files) == 1
    assert context.files[0].path == "focal.py"
    assert context.files[0].distance == 0
    assert context.files[0].direction == "focal"


def test_compute_focus_context_direct_dependencies():
    """Test focus context finds direct dependencies."""
    # focal.py imports utils.py and config.py
    edges = [
        ("focal.py", "utils.py"),
        ("focal.py", "config.py"),
    ]
    graph = build_graph_from_edges(edges)
    centrality = {"focal.py": 0.3, "utils.py": 0.5, "config.py": 0.2}
    
    context = compute_focus_context("focal.py", graph, centrality)
    
    assert context.focal_file == "focal.py"
    assert len(context.files) == 3  # focal + 2 deps
    assert len(context.dependencies) == 2
    
    # Check distances
    focal = next(f for f in context.files if f.path == "focal.py")
    assert focal.distance == 0
    
    utils = next(f for f in context.files if f.path == "utils.py")
    assert utils.distance == 1
    assert utils.direction == "dependency"
    
    config = next(f for f in context.files if f.path == "config.py")
    assert config.distance == 1
    assert config.direction == "dependency"


def test_compute_focus_context_direct_dependents():
    """Test focus context finds direct dependents."""
    # app.py and api.py import focal.py
    edges = [
        ("app.py", "focal.py"),
        ("api.py", "focal.py"),
    ]
    graph = build_graph_from_edges(edges)
    centrality = {"focal.py": 0.5, "app.py": 0.3, "api.py": 0.2}
    
    context = compute_focus_context("focal.py", graph, centrality)
    
    assert context.focal_file == "focal.py"
    assert len(context.files) == 3  # focal + 2 dependents
    assert len(context.dependents) == 2
    
    app = next(f for f in context.files if f.path == "app.py")
    assert app.distance == 1
    assert app.direction == "dependent"


def test_compute_focus_context_bidirectional():
    """Test focus context handles bidirectional relationships."""
    # focal.py imports utils.py, and utils.py imports focal.py (cycle)
    edges = [
        ("focal.py", "utils.py"),
        ("utils.py", "focal.py"),
    ]
    graph = build_graph_from_edges(edges)
    centrality = {"focal.py": 0.5, "utils.py": 0.5}
    
    context = compute_focus_context("focal.py", graph, centrality)
    
    utils = next(f for f in context.files if f.path == "utils.py")
    assert utils.direction == "both"


def test_compute_focus_context_transitive():
    """Test focus context finds transitive dependencies."""
    # focal.py -> middle.py -> leaf.py
    edges = [
        ("focal.py", "middle.py"),
        ("middle.py", "leaf.py"),
    ]
    graph = build_graph_from_edges(edges)
    centrality = {"focal.py": 0.3, "middle.py": 0.4, "leaf.py": 0.3}
    
    context = compute_focus_context("focal.py", graph, centrality, FocusConfig(max_depth=3))
    
    assert len(context.files) == 3
    
    leaf = next(f for f in context.files if f.path == "leaf.py")
    assert leaf.distance == 2


def test_compute_focus_context_max_depth():
    """Test focus context respects max_depth."""
    # focal.py -> a.py -> b.py -> c.py -> d.py
    edges = [
        ("focal.py", "a.py"),
        ("a.py", "b.py"),
        ("b.py", "c.py"),
        ("c.py", "d.py"),
    ]
    graph = build_graph_from_edges(edges)
    centrality = {f: 0.2 for f in ["focal.py", "a.py", "b.py", "c.py", "d.py"]}
    
    # Depth 2: should find focal, a, b
    context = compute_focus_context("focal.py", graph, centrality, FocusConfig(max_depth=2))
    
    paths = {f.path for f in context.files}
    assert "focal.py" in paths
    assert "a.py" in paths
    assert "b.py" in paths
    assert "c.py" not in paths
    assert "d.py" not in paths


def test_compute_focus_context_score_decay():
    """Test that scores decay with distance."""
    edges = [
        ("focal.py", "near.py"),
        ("near.py", "far.py"),
    ]
    graph = build_graph_from_edges(edges)
    # Same centrality for all
    centrality = {"focal.py": 0.5, "near.py": 0.5, "far.py": 0.5}
    
    context = compute_focus_context("focal.py", graph, centrality, FocusConfig(decay_factor=0.5))
    
    focal = next(f for f in context.files if f.path == "focal.py")
    near = next(f for f in context.files if f.path == "near.py")
    far = next(f for f in context.files if f.path == "far.py")
    
    # Scores: focal = 0.5 * 0.5^0 = 0.5
    #         near  = 0.5 * 0.5^1 = 0.25
    #         far   = 0.5 * 0.5^2 = 0.125
    assert focal.score == pytest.approx(0.5, rel=0.01)
    assert near.score == pytest.approx(0.25, rel=0.01)
    assert far.score == pytest.approx(0.125, rel=0.01)


def test_compute_focus_context_test_files():
    """Test that test files are categorized."""
    edges = [
        ("test_focal.py", "focal.py"),
    ]
    graph = build_graph_from_edges(edges)
    centrality = {"focal.py": 0.5, "test_focal.py": 0.5}
    
    context = compute_focus_context("focal.py", graph, centrality, FocusConfig(include_tests=True))
    
    assert len(context.related_tests) == 1
    assert context.related_tests[0].path == "test_focal.py"


def test_compute_focus_context_type_files():
    """Test that type files are categorized."""
    edges = [
        ("focal.py", "types.py"),
    ]
    graph = build_graph_from_edges(edges)
    centrality = {"focal.py": 0.5, "types.py": 0.5}
    
    context = compute_focus_context("focal.py", graph, centrality, FocusConfig(include_types=True))
    
    assert len(context.shared_types) == 1
    assert context.shared_types[0].path == "types.py"


def test_generate_focus_markdown():
    """Test markdown generation."""
    # Create a simple context
    context = FocusedContext(
        focal_file="src/auth/jwt.py",
        files=[
            FocusedFile("src/auth/jwt.py", 0, "focal", 0.5, 0.5, "focal file"),
            FocusedFile("src/utils.py", 1, "dependency", 0.3, 0.24, "imported by focal (1 hop)"),
            FocusedFile("src/api/handler.py", 1, "dependent", 0.2, 0.16, "imports focal (1 hop)"),
        ],
        total_files_in_neighborhood=3,
        max_depth_used=1,
        dependencies=[FocusedFile("src/utils.py", 1, "dependency", 0.3, 0.24, "")],
        dependents=[FocusedFile("src/api/handler.py", 1, "dependent", 0.2, 0.16, "")],
        related_tests=[],
        shared_types=[],
    )
    
    md = generate_focus_markdown(context)
    
    assert "# Focus: jwt.py" in md
    assert "src/auth/jwt.py" in md
    assert "Direct Dependencies" in md
    assert "Direct Dependents" in md
    assert "src/utils.py" in md
    assert "src/api/handler.py" in md


def test_generate_focus_markdown_with_tests():
    """Test markdown includes test section."""
    context = FocusedContext(
        focal_file="auth.py",
        files=[
            FocusedFile("auth.py", 0, "focal", 0.5, 0.5, "focal file"),
            FocusedFile("test_auth.py", 1, "dependent", 0.2, 0.16, ""),
        ],
        total_files_in_neighborhood=2,
        max_depth_used=1,
        dependencies=[],
        dependents=[FocusedFile("test_auth.py", 1, "dependent", 0.2, 0.16, "")],
        related_tests=[FocusedFile("test_auth.py", 1, "dependent", 0.2, 0.16, "")],
        shared_types=[],
    )
    
    md = generate_focus_markdown(context)
    
    assert "Related Tests" in md
    assert "test_auth.py" in md


def test_files_sorted_by_score():
    """Test that files are sorted by score."""
    edges = [
        ("focal.py", "low.py"),
        ("focal.py", "high.py"),
    ]
    graph = build_graph_from_edges(edges)
    # high.py has higher centrality
    centrality = {"focal.py": 0.3, "low.py": 0.1, "high.py": 0.6}
    
    context = compute_focus_context("focal.py", graph, centrality)
    
    # After focal, high.py should come before low.py
    non_focal = [f for f in context.files if f.distance > 0]
    assert non_focal[0].path == "high.py"
    assert non_focal[1].path == "low.py"
