"""Tests for Go language adapter."""

from better_context.languages.go import GoAdapter


def test_go_adapter_properties():
    """Test adapter properties."""
    adapter = GoAdapter()
    assert adapter.language == "go"
    assert ".go" in adapter.extensions
    assert adapter.supports_ast() is False


def test_parse_simple_function():
    """Test parsing a simple function."""
    adapter = GoAdapter()
    source = '''package main

func Hello(name string) string {
    return "Hello, " + name
}
'''
    result = adapter.parse_file("test.go", source)
    
    assert len(result.chunks) == 1
    chunk = result.chunks[0]
    assert chunk.name == "Hello"
    assert chunk.type == "function"
    assert "Hello" in chunk.signature
    assert "name string" in chunk.signature
    assert chunk.exported is True


def test_parse_unexported_function():
    """Test parsing an unexported function."""
    adapter = GoAdapter()
    source = '''package main

func helper() {
    // private function
}
'''
    result = adapter.parse_file("test.go", source)
    
    assert len(result.chunks) == 1
    chunk = result.chunks[0]
    assert chunk.name == "helper"
    assert chunk.exported is False


def test_parse_function_with_return_type():
    """Test parsing function with return type."""
    adapter = GoAdapter()
    source = '''package main

func GetUser(id int) (*User, error) {
    return nil, nil
}
'''
    result = adapter.parse_file("test.go", source)
    
    assert len(result.chunks) == 1
    chunk = result.chunks[0]
    assert chunk.name == "GetUser"
    assert chunk.type == "function"
    assert chunk.metadata.get("returns") is not None


def test_parse_method():
    """Test parsing a method with receiver."""
    adapter = GoAdapter()
    source = '''package main

type User struct {}

func (u *User) GetName() string {
    return u.name
}
'''
    result = adapter.parse_file("test.go", source)
    
    # Should have: User struct and GetName method
    assert len(result.chunks) == 2
    
    method = next(c for c in result.chunks if c.type == "method")
    assert method.name == "GetName"
    assert method.metadata.get("receiver_type") == "*User"
    assert method.metadata.get("receiver_name") == "u"
    assert method.exported is True


def test_parse_struct():
    """Test parsing a struct."""
    adapter = GoAdapter()
    source = '''package main

// User represents a user in the system.
type User struct {
    ID   int
    Name string
}
'''
    result = adapter.parse_file("test.go", source)
    
    assert len(result.chunks) == 1
    chunk = result.chunks[0]
    assert chunk.name == "User"
    assert chunk.type == "struct"
    assert chunk.exported is True
    assert chunk.docstring == "User represents a user in the system."
    # Fields should be captured
    assert len(chunk.metadata.get("fields", [])) > 0


def test_parse_interface():
    """Test parsing an interface."""
    adapter = GoAdapter()
    source = '''package main

// Reader is the interface for reading data.
type Reader interface {
    Read(p []byte) (n int, err error)
}
'''
    result = adapter.parse_file("test.go", source)
    
    assert len(result.chunks) == 1
    chunk = result.chunks[0]
    assert chunk.name == "Reader"
    assert chunk.type == "interface"
    assert chunk.exported is True
    assert "Reader" in chunk.docstring


def test_parse_single_import():
    """Test parsing single import."""
    adapter = GoAdapter()
    source = '''package main

import "fmt"

func main() {
    fmt.Println("Hello")
}
'''
    result = adapter.parse_file("test.go", source)
    
    assert len(result.imports) == 1
    imp = result.imports[0]
    assert imp.module == "fmt"
    assert imp.alias is None


def test_parse_aliased_import():
    """Test parsing aliased import."""
    adapter = GoAdapter()
    source = '''package main

import f "fmt"

func main() {
    f.Println("Hello")
}
'''
    result = adapter.parse_file("test.go", source)
    
    assert len(result.imports) == 1
    imp = result.imports[0]
    assert imp.module == "fmt"
    assert imp.alias == "f"


def test_parse_grouped_imports():
    """Test parsing grouped imports."""
    adapter = GoAdapter()
    source = '''package main

import (
    "fmt"
    "os"
    alias "github.com/pkg/errors"
)

func main() {}
'''
    result = adapter.parse_file("test.go", source)
    
    assert len(result.imports) >= 3
    
    modules = [i.module for i in result.imports]
    assert "fmt" in modules
    assert "os" in modules
    assert "github.com/pkg/errors" in modules
    
    # Check alias
    alias_import = next(i for i in result.imports if i.module == "github.com/pkg/errors")
    assert alias_import.alias == "alias"


def test_parse_side_effect_import():
    """Test parsing side-effect import (underscore)."""
    adapter = GoAdapter()
    source = '''package main

import _ "github.com/lib/pq"

func main() {}
'''
    result = adapter.parse_file("test.go", source)
    
    assert len(result.imports) == 1
    imp = result.imports[0]
    assert imp.module == "github.com/lib/pq"
    assert imp.is_type_only is True  # We use is_type_only for side-effect imports


def test_parse_exports():
    """Test parsing exports (capitalized names)."""
    adapter = GoAdapter()
    source = '''package main

func PublicFunc() {}

func privateFunc() {}

type PublicType struct {}

type privateType struct {}
'''
    result = adapter.parse_file("test.go", source)
    
    export_names = [e.name for e in result.exports]
    assert "PublicFunc" in export_names
    assert "PublicType" in export_names
    assert "privateFunc" not in export_names
    assert "privateType" not in export_names


def test_parse_package_metadata():
    """Test that package name is captured in metadata."""
    adapter = GoAdapter()
    source = '''package mypackage

func DoSomething() {}
'''
    result = adapter.parse_file("test.go", source)
    
    assert len(result.chunks) == 1
    assert result.chunks[0].metadata.get("package") == "mypackage"


def test_parse_go_doc_comment():
    """Test parsing Go doc comments."""
    adapter = GoAdapter()
    source = '''package main

// ProcessData takes data and processes it.
// It returns an error if processing fails.
func ProcessData(data []byte) error {
    return nil
}
'''
    result = adapter.parse_file("test.go", source)
    
    assert len(result.chunks) == 1
    chunk = result.chunks[0]
    assert chunk.docstring is not None
    assert "ProcessData takes data" in chunk.docstring
    assert "It returns an error" in chunk.docstring


def test_parse_type_alias():
    """Test parsing type aliases."""
    adapter = GoAdapter()
    source = '''package main

type MyInt = int
'''
    result = adapter.parse_file("test.go", source)
    
    assert len(result.chunks) == 1
    chunk = result.chunks[0]
    assert chunk.name == "MyInt"
    assert chunk.type == "type"
    assert chunk.metadata.get("alias_target") == "int"
