"""Tests for Python language adapter."""

from better_context.languages.python import PythonAdapter


def test_python_adapter_properties():
    """Test adapter properties."""
    adapter = PythonAdapter()
    assert adapter.language == "python"
    assert ".py" in adapter.extensions
    assert adapter.supports_ast() is False


def test_parse_simple_function():
    """Test parsing a simple function."""
    adapter = PythonAdapter()
    source = '''
def hello(name: str) -> str:
    """Say hello."""
    return f"Hello, {name}!"
'''
    result = adapter.parse_file("test.py", source)
    
    assert len(result.chunks) == 1
    chunk = result.chunks[0]
    assert chunk.name == "hello"
    assert chunk.type == "function"
    assert "name: str" in chunk.signature
    assert chunk.exported is True


def test_parse_async_function():
    """Test parsing async function."""
    adapter = PythonAdapter()
    source = '''
async def fetch_data(url: str) -> dict:
    """Fetch data from URL."""
    pass
'''
    result = adapter.parse_file("test.py", source)
    
    assert len(result.chunks) == 1
    chunk = result.chunks[0]
    assert chunk.name == "fetch_data"
    assert chunk.metadata.get("is_async") is True
    assert "async def" in chunk.signature


def test_parse_class():
    """Test parsing a class."""
    adapter = PythonAdapter()
    source = '''
class User:
    """A user model."""
    
    def __init__(self, name: str):
        self.name = name
    
    def greet(self) -> str:
        return f"Hello, {self.name}"
'''
    result = adapter.parse_file("test.py", source)
    
    # Should have: class User, __init__, greet
    assert len(result.chunks) == 3
    
    class_chunk = next(c for c in result.chunks if c.type == "class")
    assert class_chunk.name == "User"
    
    methods = [c for c in result.chunks if c.type == "method"]
    assert len(methods) == 2
    
    # Methods should have class as parent
    for method in methods:
        assert method.parent == class_chunk.id


def test_parse_imports():
    """Test parsing import statements."""
    adapter = PythonAdapter()
    source = '''
import os
import sys
from pathlib import Path
from typing import List, Optional
from . import sibling
from ..parent import thing
'''
    result = adapter.parse_file("test.py", source)
    
    assert len(result.imports) >= 5
    
    # Check os import
    os_import = next(i for i in result.imports if i.module == "os")
    assert os_import.symbols == []
    assert os_import.is_relative is False
    
    # Check from pathlib import
    pathlib_import = next(i for i in result.imports if i.module == "pathlib")
    assert "Path" in pathlib_import.symbols
    
    # Check relative import
    sibling_import = next(i for i in result.imports if i.module == ".")
    assert sibling_import.is_relative is True


def test_parse_exports_with_all():
    """Test parsing exports with __all__."""
    adapter = PythonAdapter()
    source = '''
__all__ = ["foo", "bar"]

def foo():
    pass

def bar():
    pass

def _private():
    pass
'''
    result = adapter.parse_file("test.py", source)
    
    # Should export only foo and bar
    assert len(result.exports) == 2
    export_names = [e.name for e in result.exports]
    assert "foo" in export_names
    assert "bar" in export_names
    assert "_private" not in export_names


def test_parse_exports_inferred():
    """Test parsing exports when __all__ is not defined."""
    adapter = PythonAdapter()
    source = '''
def public_func():
    pass

def _private_func():
    pass

class PublicClass:
    pass
'''
    result = adapter.parse_file("test.py", source)
    
    # Should export public_func and PublicClass
    export_names = [e.name for e in result.exports]
    assert "public_func" in export_names
    assert "PublicClass" in export_names
    assert "_private_func" not in export_names


def test_parse_decorated_function():
    """Test parsing function with decorators."""
    adapter = PythonAdapter()
    source = '''
@decorator
@another.decorator
def decorated_func():
    pass
'''
    result = adapter.parse_file("test.py", source)
    
    assert len(result.chunks) == 1
    chunk = result.chunks[0]
    decorators = chunk.metadata.get("decorators", [])
    assert "decorator" in decorators
    assert "another.decorator" in decorators
