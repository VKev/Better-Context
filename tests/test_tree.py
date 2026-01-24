"""Tests for directory tree builder."""

from better_context.tree import (
    DirectoryNode,
    build_directory_tree,
    render_tree_ascii,
    render_tree_simple,
    get_directory_summary,
    _ensure_path_exists,
    _calculate_recursive_counts,
)


def test_directory_node_creation():
    """Test DirectoryNode can be created."""
    node = DirectoryNode(name="test", path="test")
    assert node.name == "test"
    assert node.path == "test"
    assert node.files == []
    assert node.subdirs == []


def test_directory_node_total_files():
    """Test recursive file count."""
    root = DirectoryNode(name="root", path=".")
    root.files = ["a.py", "b.py"]

    child = DirectoryNode(name="child", path="child")
    child.files = ["c.py"]
    root.subdirs.append(child)

    assert root.get_total_files() == 3


def test_ensure_path_exists():
    """Test path creation in tree."""
    root = DirectoryNode(name="root", path=".")
    nodes = {".": root}

    _ensure_path_exists(nodes, "src/lib/utils", root)

    assert "src" in nodes
    assert "src/lib" in nodes
    assert "src/lib/utils" in nodes
    assert nodes["src"].name == "src"
    assert nodes["src/lib"].name == "lib"


def test_calculate_recursive_counts():
    """Test recursive count calculation."""
    root = DirectoryNode(name="root", path=".")
    root.files = ["a.py"]

    child = DirectoryNode(name="child", path="child")
    child.files = ["b.py", "c.py"]
    root.subdirs.append(child)

    _calculate_recursive_counts(root)

    assert root.file_count == 3
    assert child.file_count == 2


def test_render_tree_ascii_simple():
    """Test ASCII tree rendering."""
    root = DirectoryNode(name="project", path=".")
    root.files = ["README.md"]

    src = DirectoryNode(name="src", path="src")
    src.files = ["main.py"]
    root.subdirs.append(src)

    result = render_tree_ascii(root)

    assert "project/" in result
    assert "src/" in result
    assert "main.py" in result
    assert "README.md" in result


def test_render_tree_simple():
    """Test directory-only tree rendering."""
    root = DirectoryNode(name="project", path=".")
    root.files = ["README.md"]

    src = DirectoryNode(name="src", path="src")
    src.files = ["main.py"]
    root.subdirs.append(src)

    result = render_tree_simple(root)

    assert "src/" in result
    assert "main.py" not in result


def test_get_directory_summary():
    """Test directory summary stats."""
    root = DirectoryNode(name="project", path=".")
    root.files = ["main.py"]
    root.file_count = 3
    root.language_breakdown = {"python": 2}

    src = DirectoryNode(name="src", path="src")
    src.language_breakdown = {"python": 1}
    root.subdirs.append(src)

    summary = get_directory_summary(root)

    assert summary["path"] == "."
    assert summary["total_files"] == 3
    assert summary["direct_files"] == 1
    assert summary["languages"]["python"] == 3
