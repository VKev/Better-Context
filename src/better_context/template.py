"""Template engine for AGENTS.md generation.

A simple, zero-dependency template engine for generating AGENTS.md files.
Supports variable substitution, conditionals, and loops.

Template Syntax:
- Variables: {{ variable_name }} or {{ nested.property }}
- Conditionals: {% if condition %}...{% endif %}
- Negated conditionals: {% if not condition %}...{% endif %}
- Loops: {% for item in collection %}...{% endfor %}
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


class TemplateError(Exception):
    """Error during template parsing or rendering."""
    pass


@dataclass
class SimpleTemplate:
    """Zero-dependency template engine for AGENTS.md generation.
    
    Example usage:
        template = SimpleTemplate("Hello {{ name }}!")
        result = template.render({"name": "World"})
        # result: "Hello World!"
    """
    
    template: str
    
    # Pattern for {{ variable }} or {{ nested.property }}
    VAR_PATTERN = re.compile(r'\{\{\s*([\w.]+)\s*\}\}')
    
    # Pattern for {% if condition %}...{% endif %} (supports 'not')
    IF_PATTERN = re.compile(
        r'\{%\s*if\s+(not\s+)?([\w.]+)\s*%\}(.*?)\{%\s*endif\s*%\}',
        re.DOTALL
    )
    
    # Pattern for {% if condition %}...{% else %}...{% endif %}
    IF_ELSE_PATTERN = re.compile(
        r'\{%\s*if\s+(not\s+)?([\w.]+)\s*%\}(.*?)\{%\s*else\s*%\}(.*?)\{%\s*endif\s*%\}',
        re.DOTALL
    )
    
    # Pattern for {% for item in collection %}...{% endfor %}
    FOR_PATTERN = re.compile(
        r'\{%\s*for\s+(\w+)\s+in\s+([\w.]+)\s*%\}(.*?)\{%\s*endfor\s*%\}',
        re.DOTALL
    )
    
    def render(self, context: dict[str, Any]) -> str:
        """Render the template with the given context.
        
        Args:
            context: Dictionary of values to substitute
            
        Returns:
            Rendered template string
        """
        result = self.template
        
        # Process if-else conditionals first (before simple if)
        result = self._process_if_else(result, context)
        
        # Process simple conditionals
        result = self._process_conditionals(result, context)
        
        # Process loops
        result = self._process_loops(result, context)
        
        # Substitute variables last
        result = self._substitute_vars(result, context)
        
        return result
    
    def _get_value(self, key: str, context: dict[str, Any]) -> Any:
        """Get nested value from context using dot notation.
        
        Args:
            key: Key in dot notation (e.g., "file.path")
            context: Context dictionary
            
        Returns:
            Value or None if not found
        """
        parts = key.split('.')
        value: Any = context
        
        for part in parts:
            if value is None:
                return None
            if isinstance(value, dict):
                value = value.get(part)
            elif hasattr(value, part):
                value = getattr(value, part)
            else:
                # Try __getitem__ for list/tuple indexing
                try:
                    idx = int(part)
                    value = value[idx]
                except (ValueError, IndexError, TypeError):
                    return None
                    
        return value
    
    def _is_truthy(self, value: Any) -> bool:
        """Check if a value is truthy for conditionals.
        
        Falsy values: None, False, 0, empty string, empty list/dict
        """
        if value is None:
            return False
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return value != 0
        if isinstance(value, str):
            return len(value) > 0
        if isinstance(value, (list, dict, tuple, set)):
            return len(value) > 0
        return True
    
    def _substitute_vars(self, text: str, context: dict[str, Any]) -> str:
        """Substitute {{ variable }} patterns."""
        def replace(match: re.Match[str]) -> str:
            key = match.group(1)
            value = self._get_value(key, context)
            if value is None:
                return ''
            return str(value)
        
        return self.VAR_PATTERN.sub(replace, text)
    
    def _process_if_else(self, text: str, context: dict[str, Any]) -> str:
        """Process {% if %}...{% else %}...{% endif %} patterns."""
        def replace(match: re.Match[str]) -> str:
            negated = match.group(1) is not None
            condition_key = match.group(2)
            if_body = match.group(3)
            else_body = match.group(4)
            
            value = self._get_value(condition_key, context)
            is_true = self._is_truthy(value)
            
            if negated:
                is_true = not is_true
            
            if is_true:
                return if_body
            return else_body
        
        return self.IF_ELSE_PATTERN.sub(replace, text)
    
    def _process_conditionals(self, text: str, context: dict[str, Any]) -> str:
        """Process {% if condition %}...{% endif %} patterns."""
        def replace(match: re.Match[str]) -> str:
            negated = match.group(1) is not None
            condition_key = match.group(2)
            body = match.group(3)
            
            value = self._get_value(condition_key, context)
            is_true = self._is_truthy(value)
            
            if negated:
                is_true = not is_true
            
            if is_true:
                return body
            return ''
        
        return self.IF_PATTERN.sub(replace, text)
    
    def _process_loops(self, text: str, context: dict[str, Any]) -> str:
        """Process {% for item in collection %}...{% endfor %} patterns."""
        def replace(match: re.Match[str]) -> str:
            var_name = match.group(1)
            collection_key = match.group(2)
            body = match.group(3)
            
            collection = self._get_value(collection_key, context)
            if not collection:
                return ''
            
            # Handle non-iterable
            try:
                iter(collection)
            except TypeError:
                return ''
            
            result = []
            for idx, item in enumerate(collection):
                # Create item context with loop variables
                item_context = {
                    **context,
                    var_name: item,
                    'loop': {
                        'index': idx,
                        'index1': idx + 1,
                        'first': idx == 0,
                        'last': idx == len(collection) - 1 if hasattr(collection, '__len__') else False,
                    }
                }
                # Recursively process body (for nested constructs)
                rendered_body = self._substitute_vars(body, item_context)
                # Also process nested conditionals in loop body
                rendered_body = self._process_conditionals(rendered_body, item_context)
                result.append(rendered_body)
            
            return ''.join(result)
        
        return self.FOR_PATTERN.sub(replace, text)


# Embedded template strings
ROOT_TEMPLATE = """# {{ project_name }}

> Auto-generated context for AI agents. Last updated: {{ generated_at }}

## 📋 Purpose

{{ purpose }}

## 📂 Structure

```
{{ directory_tree }}
```

## 🔑 Key Files (by Centrality)

| File | Score | Why It Matters |
|------|-------|----------------|
{% for file in key_files %}- `{{ file.path }}` | {{ file.centrality }} | {{ file.description }} |
{% endfor %}

## 🏗️ Architecture Layers

| Layer | Files | Description |
|-------|-------|-------------|
{% for layer in layers %}- {{ layer.number }} | {{ layer.count }} | {{ layer.description }} |
{% endfor %}

## 📦 Dependencies

### External (Top 10)
{{ external_deps }}

### Internal Cross-References
```mermaid
{{ dependency_diagram }}
```

{% if has_cycles %}
## ⚠️ Circular Dependencies

The following cycles were detected:
{% for cycle in cycles %}- {{ cycle }}
{% endfor %}
{% endif %}

## 📊 Metrics

- **Total Files**: {{ metrics.total_files }}
- **Total Definitions**: {{ metrics.total_chunks }}
- **Internal Dependencies**: {{ metrics.internal_edges }}
- **External Packages**: {{ metrics.external_packages }}
{% if metrics.violations %}- **Architectural Violations**: {{ metrics.violations }}
{% endif %}

## 🧭 Navigation

{% for dir in subdirectories %}- **{{ dir.purpose }}?** Start with: [`./{{ dir.path }}/AGENTS.md`](./{{ dir.path }}/AGENTS.md)
{% endfor %}

---
*Navigate to subdirectories for more detailed context.*
"""

DIRECTORY_TEMPLATE = """# {{ directory_name }}

> Auto-generated context for `{{ directory_path }}`

## 📋 Purpose

{{ purpose }}

## 📂 Contents

{% for file in files %}- `{{ file.name }}` - {{ file.description }}
{% endfor %}

{% if has_subdirs %}
## 📁 Subdirectories

{% for subdir in subdirs %}- [`{{ subdir.name }}/`](./{{ subdir.name }}/AGENTS.md) - {{ subdir.purpose }}
{% endfor %}
{% endif %}

## 🔑 Key Exports

{% for export in exports %}- `{{ export.name }}` ({{ export.type }}) - {{ export.description }}
{% endfor %}

## 📥 Dependencies

### Internal
{% for dep in internal_deps %}- `{{ dep.path }}` - {{ dep.symbols }}
{% endfor %}

### External
{% for dep in external_deps %}- `{{ dep.package }}` - {{ dep.symbols }}
{% endfor %}

---
*[← Back to parent](../AGENTS.md)*
"""

MODULE_TEMPLATE = """# {{ module_name }}

> {{ module_path }}

## Overview

{{ overview }}

## Exports

{% for chunk in chunks %}### {{ chunk.name }}

```{{ language }}
{{ chunk.signature }}
```

{% if chunk.docstring %}{{ chunk.docstring }}

{% endif %}{% endfor %}

## Imports

{% for imp in imports %}- `{{ imp.module }}`{% if imp.symbols %}: {{ imp.symbols }}{% endif %}
{% endfor %}
"""


# Template cache
_template_cache: dict[str, SimpleTemplate] = {}


def load_template(name: str, cache: bool = True) -> SimpleTemplate:
    """Load a template by name.
    
    Tries embedded templates first, then looks for external files.
    
    Args:
        name: Template name ('root', 'directory', 'module') or file path
        cache: Whether to cache loaded templates
        
    Returns:
        SimpleTemplate instance
        
    Raises:
        TemplateError: If template not found
    """
    if cache and name in _template_cache:
        return _template_cache[name]
    
    # Embedded templates
    templates = {
        'root': ROOT_TEMPLATE,
        'directory': DIRECTORY_TEMPLATE,
        'module': MODULE_TEMPLATE,
    }
    
    if name in templates:
        template = SimpleTemplate(templates[name])
        if cache:
            _template_cache[name] = template
        return template
    
    # Try loading from file
    template_path = Path(name)
    if not template_path.exists():
        # Try in templates directory relative to this file
        template_path = Path(__file__).parent / 'templates' / f'{name}.md'
    
    if template_path.exists():
        template = SimpleTemplate(template_path.read_text(encoding='utf-8'))
        if cache:
            _template_cache[name] = template
        return template
    
    raise TemplateError(f'Unknown template: {name}')


def render_template(name: str, context: dict[str, Any]) -> str:
    """Convenience function to load and render a template.
    
    Args:
        name: Template name
        context: Context dictionary
        
    Returns:
        Rendered template string
    """
    template = load_template(name)
    return template.render(context)


def clear_template_cache() -> None:
    """Clear the template cache."""
    _template_cache.clear()


# Export public API
__all__ = [
    'SimpleTemplate',
    'TemplateError',
    'load_template',
    'render_template',
    'clear_template_cache',
    'ROOT_TEMPLATE',
    'DIRECTORY_TEMPLATE',
    'MODULE_TEMPLATE',
]
