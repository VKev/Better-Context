"""Tests for better_context primitives."""

from __future__ import annotations

import sys
import shutil
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from better_context.primitives.tree import analyze_tree
from better_context.primitives.entries import analyze_entry_points
from better_context.primitives.scripts import analyze_scripts
from better_context.primitives.overview import analyze_overview
from better_context.primitives.file_info import analyze_file
from better_context.primitives.deps import get_file_dependencies
from better_context.graph import build_graph_from_edges


@pytest.fixture
def python_project(tmp_path):
    """Create a temporary Python project for testing."""
    project_dir = tmp_path / "python_project"
    project_dir.mkdir()
    
    # Create pyproject.toml
    (project_dir / "pyproject.toml").write_text("""
[project]
name = "test-project"
version = "0.1.0"
dependencies = ["flask"]

[project.scripts]
test-cli = "src.cli:main"

[tool.pytest.ini_options]
addopts = "-v"
""", encoding="utf-8")

    # Create src structure
    src = project_dir / "src"
    src.mkdir()
    (src / "__init__.py").touch()
    
    # Create main file
    (src / "main.py").write_text("""
import os
from flask import Flask

def main():
    print("Hello")
""", encoding="utf-8")

    # Create cli file
    (src / "cli.py").write_text("""
import argparse
from .main import main

if __name__ == "__main__":
    main()
""", encoding="utf-8")

    return project_dir


@pytest.fixture
def node_project(tmp_path):
    """Create a temporary Node.js project for testing."""
    project_dir = tmp_path / "node_project"
    project_dir.mkdir()
    
    # Create package.json
    (project_dir / "package.json").write_text("""
{
  "name": "test-node",
  "scripts": {
    "test": "jest",
    "start": "node index.js"
  },
  "dependencies": {
    "express": "^4.17.1"
  },
  "bin": {
    "test-cli": "./bin/cli.js"
  }
}
""", encoding="utf-8")

    # Create files
    (project_dir / "index.js").write_text("console.log('Hello');", encoding="utf-8")
    bin_dir = project_dir / "bin"
    bin_dir.mkdir()
    (bin_dir / "cli.js").write_text("#!/usr/bin/env node", encoding="utf-8")
    
    return project_dir


class TestTreePrimitive:
    """Tests for tree primitive."""
    
    def test_analyze_tree_structure(self, python_project):
        result = analyze_tree(python_project)
        
        assert result.root == str(python_project)
        assert result.total_files == 4  # pyproject.toml, src/__init__.py, src/main.py, src/cli.py
        
        # Check directories
        dirs = {d.path: d for d in result.directories}
        assert "" in dirs  # Root
        assert "src" in dirs
        
        # Check file counts
        root_dir = dirs[""]
        assert root_dir.file_count == 1  # pyproject.toml
        
        src_dir = dirs["src"]
        assert src_dir.file_count == 3  # __init__, main, cli
        assert src_dir.extensions[".py"] == 3


class TestOverviewPrimitive:
    """Tests for overview primitive."""
    
    def test_python_project_overview(self, python_project):
        result = analyze_overview(python_project)
        
        assert result.project_name == "test-project"
        assert result.primary_language == "python"
        assert result.package_file == "pyproject.toml"
        assert "flask" in result.frameworks
        assert "src" in result.source_dirs
        
    def test_node_project_overview(self, node_project):
        result = analyze_overview(node_project)
        
        assert result.project_name == "test-node"
        assert result.primary_language == "javascript"
        assert result.package_file == "package.json"
        assert "express" in result.frameworks
        assert result.package_manager == "npm"  # Default without lockfile


class TestScriptsPrimitive:
    """Tests for scripts primitive."""
    
    def test_python_scripts(self, python_project):
        # Add pytest to make it detect 'test' golden command (requires [tool.pytest...])
        # We added tool.pytest.ini_options, but maybe need dependency on pytest?
        # Our primitive checks [tool] keys.
        
        result = analyze_scripts(python_project)
        
        # Since we didn't add explicit script runner tools (like poetry/uv lock files), 
        # it might default to pip and minimal detection.
        # But we added [tool.pytest.ini_options], let's see if our primitive logic catches that.
        # The logic checks: if "tool" in content... if "pytest" in tools...
        # Yes, [tool.pytest.ini_options] puts "pytest" in tools? No, it puts "pytest" table.
        # Toml: [tool.pytest.ini_options] -> {"tool": {"pytest": {"ini_options": ...}}}
        # So "pytest" is in tools.
        
        assert "test" in result.golden_commands
        assert result.golden_commands["test"] == "pytest"
        
    def test_node_scripts(self, node_project):
        result = analyze_scripts(node_project)
        
        scripts = {s.name: s for s in result.scripts}
        assert "test" in scripts
        assert "start" in scripts
        
        assert result.golden_commands["test"] == "npm test"
        assert result.golden_commands["start"] == "npm start"


class TestEntriesPrimitive:
    """Tests for entries primitive."""
    
    def test_python_entries(self, python_project):
        result = analyze_entry_points(python_project)
        
        # Should find src.cli:main from pyproject.toml
        # And heuristic src/cli.py, src/main.py
        
        paths = [e.path for e in result.entry_points]
        assert "src/cli.py" in paths
        assert "src/main.py" in paths
        
        # Check types
        cli_entry = next(e for e in result.entry_points if e.path == "src/cli.py")
        assert cli_entry.type == "cli"
        
    def test_node_entries(self, node_project):
        result = analyze_entry_points(node_project)
        
        paths = [e.path for e in result.entry_points]
        # Implementation might strip ./ or not
        # bin/cli.js is standard relative path
        assert "bin/cli.js" in paths or "./bin/cli.js" in paths
        assert "index.js" in paths    # heuristic
        
        cli_entry = next(e for e in result.entry_points if e.path.endswith("bin/cli.js"))
        assert cli_entry.type == "cli"


class TestFileInfoPrimitive:
    """Tests for file info primitive."""
    
    def test_python_file_info(self, python_project):
        cli_path = python_project / "src" / "cli.py"
        result = analyze_file(cli_path, python_project)
        
        assert result.path == "src/cli.py"
        assert result.language == "python"
        
        # Check imports
        imports = {i["module"] for i in result.imports}
        assert "argparse" in imports
        assert ".main" in imports or "main" in imports  # relative import resolution
        
        # Check chunks (main block or function?)
        # cli.py has "if __name__ == '__main__':" which is not a function/class
        # But analyze_file uses regex chunker which finds funcs/classes.
        # It won't find the main block unless we support it.
        # But we imported main, so maybe we test main.py instead.
        
        main_path = python_project / "src" / "main.py"
        result_main = analyze_file(main_path, python_project)
        
        chunks = {c.name for c in result_main.chunks}
        assert "main" in chunks  # def main():


class TestDepsPrimitive:
    """Tests for deps primitive."""
    
    def test_dependencies(self, python_project):
        # We need a graph first. deps.py expects a populated DependencyGraph.
        # In a real run, `scan` populates this. Here we mock it or build a simple one.
        
        graph = build_graph_from_edges([
            ("src/cli.py", "src/main.py"),
            ("src/main.py", "flask"),  # External dep represented as node?
            # Usually graph only has internal nodes, external deps are properties
        ])
        
        # Test dependencies of cli.py
        result = get_file_dependencies("src/cli.py", graph)
        assert result.path == "src/cli.py"
        assert result.manifest_used is True
        
        deps = [d.path for d in result.dependencies]
        assert "src/main.py" in deps
        
    def test_deps_standalone(self, python_project):
        """Test getting dependencies without a graph (standalone mode)."""
        main_path = python_project / "src" / "main.py"
        from better_context.primitives.deps import get_deps
        
        result = get_deps(main_path)
        assert result.path == str(main_path)
        assert result.manifest_used is False
        assert len(result.dependents) == 0
        
        # main.py imports flask
        deps = {d.path for d in result.dependencies}
        assert "flask" in deps
        assert "os" in deps
        
        flask_dep = next(d for d in result.dependencies if d.path == "flask")
        assert flask_dep.is_internal is False
        assert flask_dep.symbols == ["Flask"]
