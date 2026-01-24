"""Tests for template module."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from better_context.template import (
    SimpleTemplate,
    TemplateError,
    load_template,
    render_template,
    clear_template_cache,
    ROOT_TEMPLATE,
    DIRECTORY_TEMPLATE,
)


class TestVariableSubstitution:
    """Tests for variable substitution."""

    def test_simple_variable(self):
        """Test simple variable substitution."""
        t = SimpleTemplate("Hello {{ name }}!")
        assert t.render({"name": "World"}) == "Hello World!"

    def test_multiple_variables(self):
        """Test multiple variables in template."""
        t = SimpleTemplate("{{ greeting }}, {{ name }}!")
        result = t.render({"greeting": "Hi", "name": "Alice"})
        assert result == "Hi, Alice!"

    def test_nested_property(self):
        """Test nested property access with dot notation."""
        t = SimpleTemplate("Path: {{ file.path }}, Size: {{ file.size }}")
        result = t.render({"file": {"path": "main.py", "size": 1024}})
        assert result == "Path: main.py, Size: 1024"

    def test_deep_nesting(self):
        """Test deeply nested properties."""
        t = SimpleTemplate("{{ a.b.c.d }}")
        result = t.render({"a": {"b": {"c": {"d": "deep"}}}})
        assert result == "deep"

    def test_missing_variable(self):
        """Test missing variable renders as empty string."""
        t = SimpleTemplate("Value: {{ missing }}")
        assert t.render({}) == "Value: "

    def test_missing_nested(self):
        """Test missing nested property renders as empty string."""
        t = SimpleTemplate("{{ a.b.c }}")
        assert t.render({"a": {"b": {}}}) == ""

    def test_object_attributes(self):
        """Test accessing object attributes."""
        class Config:
            name = "test"
            value = 42
        
        t = SimpleTemplate("{{ cfg.name }}: {{ cfg.value }}")
        result = t.render({"cfg": Config()})
        assert result == "test: 42"


class TestConditionals:
    """Tests for conditional blocks."""

    def test_if_true(self):
        """Test if block with true condition."""
        t = SimpleTemplate("{% if show %}visible{% endif %}")
        assert t.render({"show": True}) == "visible"

    def test_if_false(self):
        """Test if block with false condition."""
        t = SimpleTemplate("{% if show %}visible{% endif %}")
        assert t.render({"show": False}) == ""

    def test_if_truthy_string(self):
        """Test if block with truthy string."""
        t = SimpleTemplate("{% if msg %}{{ msg }}{% endif %}")
        assert t.render({"msg": "hello"}) == "hello"

    def test_if_falsy_empty_string(self):
        """Test if block with empty string (falsy)."""
        t = SimpleTemplate("{% if msg %}visible{% endif %}")
        assert t.render({"msg": ""}) == ""

    def test_if_truthy_list(self):
        """Test if block with non-empty list."""
        t = SimpleTemplate("{% if items %}has items{% endif %}")
        assert t.render({"items": [1, 2, 3]}) == "has items"

    def test_if_falsy_empty_list(self):
        """Test if block with empty list."""
        t = SimpleTemplate("{% if items %}has items{% endif %}")
        assert t.render({"items": []}) == ""

    def test_if_not(self):
        """Test negated conditional."""
        t = SimpleTemplate("{% if not hidden %}visible{% endif %}")
        assert t.render({"hidden": False}) == "visible"
        assert t.render({"hidden": True}) == ""

    def test_if_else_true(self):
        """Test if-else with true condition."""
        t = SimpleTemplate("{% if show %}yes{% else %}no{% endif %}")
        assert t.render({"show": True}) == "yes"

    def test_if_else_false(self):
        """Test if-else with false condition."""
        t = SimpleTemplate("{% if show %}yes{% else %}no{% endif %}")
        assert t.render({"show": False}) == "no"

    def test_if_with_nested_property(self):
        """Test if block with nested property condition."""
        t = SimpleTemplate("{% if config.enabled %}on{% endif %}")
        assert t.render({"config": {"enabled": True}}) == "on"
        assert t.render({"config": {"enabled": False}}) == ""


class TestLoops:
    """Tests for loop blocks."""

    def test_simple_loop(self):
        """Test simple loop over list."""
        t = SimpleTemplate("{% for item in items %}{{ item }} {% endfor %}")
        assert t.render({"items": ["a", "b", "c"]}) == "a b c "

    def test_loop_with_objects(self):
        """Test loop over list of objects."""
        t = SimpleTemplate("{% for f in files %}{{ f.name }}{% endfor %}")
        files = [{"name": "a.py"}, {"name": "b.py"}]
        assert t.render({"files": files}) == "a.pyb.py"

    def test_empty_collection(self):
        """Test loop with empty collection."""
        t = SimpleTemplate("{% for x in items %}{{ x }}{% endfor %}")
        assert t.render({"items": []}) == ""

    def test_missing_collection(self):
        """Test loop with missing collection."""
        t = SimpleTemplate("{% for x in items %}{{ x }}{% endfor %}")
        assert t.render({}) == ""

    def test_loop_index(self):
        """Test loop.index variable."""
        t = SimpleTemplate("{% for x in items %}{{ loop.index }}{% endfor %}")
        assert t.render({"items": ["a", "b", "c"]}) == "012"

    def test_loop_index1(self):
        """Test loop.index1 variable (1-based)."""
        t = SimpleTemplate("{% for x in items %}{{ loop.index1 }}{% endfor %}")
        assert t.render({"items": ["a", "b", "c"]}) == "123"

    def test_loop_first_last(self):
        """Test loop.first and loop.last variables."""
        t = SimpleTemplate(
            "{% for x in items %}"
            "{% if loop.first %}[{% endif %}"
            "{{ x }}"
            "{% if loop.last %}]{% endif %}"
            "{% endfor %}"
        )
        assert t.render({"items": ["a", "b", "c"]}) == "[abc]"


class TestTemplateLoading:
    """Tests for template loading."""

    def test_load_root_template(self):
        """Test loading embedded root template."""
        t = load_template("root")
        assert "{{ project_name }}" in t.template

    def test_load_directory_template(self):
        """Test loading embedded directory template."""
        t = load_template("directory")
        assert "{{ directory_name }}" in t.template

    def test_load_module_template(self):
        """Test loading embedded module template."""
        t = load_template("module")
        assert "{{ module_name }}" in t.template

    def test_load_unknown_template(self):
        """Test loading unknown template raises error."""
        with pytest.raises(TemplateError):
            load_template("nonexistent")

    def test_template_caching(self):
        """Test that templates are cached."""
        clear_template_cache()
        t1 = load_template("root")
        t2 = load_template("root")
        assert t1 is t2

    def test_render_template_convenience(self):
        """Test render_template convenience function."""
        result = render_template("module", {
            "module_name": "Test",
            "module_path": "test.py",
            "overview": "A test module",
            "language": "python",
            "chunks": [],
            "imports": [],
        })
        assert "Test" in result
        assert "test.py" in result


class TestRealWorldTemplates:
    """Tests using the actual embedded templates."""

    def test_root_template_renders(self):
        """Test rendering the root template."""
        context = {
            "project_name": "my-project",
            "generated_at": "2026-01-24",
            "purpose": "A test project",
            "directory_tree": "src/\n  main.py",
            "key_files": [
                {"path": "main.py", "centrality": "0.85", "description": "Entry point"}
            ],
            "layers": [
                {"number": 0, "count": 2, "description": "Foundation"}
            ],
            "external_deps": "- requests\n- click",
            "dependency_diagram": "graph TD\n  A-->B",
            "has_cycles": False,
            "cycles": [],
            "metrics": {
                "total_files": 10,
                "total_chunks": 50,
                "internal_edges": 25,
                "external_packages": 5,
                "violations": 0,
            },
            "subdirectories": [
                {"purpose": "Source code", "path": "src"}
            ],
        }
        
        result = render_template("root", context)
        
        assert "my-project" in result
        assert "main.py" in result
        assert "Entry point" in result
        assert "Circular Dependencies" not in result  # has_cycles is False

    def test_root_template_with_cycles(self):
        """Test root template shows cycles when present."""
        context = {
            "project_name": "test",
            "generated_at": "",
            "purpose": "",
            "directory_tree": "",
            "key_files": [],
            "layers": [],
            "external_deps": "",
            "dependency_diagram": "",
            "has_cycles": True,
            "cycles": ["a.py → b.py → a.py"],
            "metrics": {"total_files": 0, "total_chunks": 0, "internal_edges": 0, "external_packages": 0},
            "subdirectories": [],
        }
        
        result = render_template("root", context)
        assert "Circular Dependencies" in result
        assert "a.py → b.py → a.py" in result
