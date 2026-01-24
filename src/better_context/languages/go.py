"""Go language adapter for better-context.

Provides regex-based parsing for Go source files.
Extracts functions, methods, structs, interfaces, imports, and exports.
"""

from __future__ import annotations

import re
from typing import Dict, List, Optional, Any

from .base import (
    ChunkResult,
    ImportResult,
    ExportResult,
    ParseResult,
    generate_chunk_id,
)


class GoAdapter:
    """Go language adapter using regex-based parsing.
    
    Extracts:
    - Functions (func declarations without receiver)
    - Methods (func declarations with receiver)
    - Structs (type X struct)
    - Interfaces (type X interface)
    - Type aliases (type X = Y)
    - Import statements (single and grouped)
    - Exports (capitalized names are exported in Go)
    """

    language = "go"
    extensions = [".go"]

    # Regex patterns
    FUNCTION_PATTERN = re.compile(
        r"^func\s+(\w+)\s*\(([^)]*)\)\s*(?:\(([^)]*)\)|(\w+(?:\s*\*?\s*\w+)?))?\s*\{",
        re.MULTILINE
    )
    METHOD_PATTERN = re.compile(
        r"^func\s+\(\s*(\w+)\s+(\*?\s*\w+)\s*\)\s+(\w+)\s*\(([^)]*)\)\s*(?:\(([^)]*)\)|(\w+(?:\s*\*?\s*\w+)?))?\s*\{",
        re.MULTILINE
    )
    STRUCT_PATTERN = re.compile(
        r"^type\s+(\w+)\s+struct\s*\{",
        re.MULTILINE
    )
    INTERFACE_PATTERN = re.compile(
        r"^type\s+(\w+)\s+interface\s*\{",
        re.MULTILINE
    )
    TYPE_ALIAS_PATTERN = re.compile(
        r"^type\s+(\w+)\s*=\s*(.+)$",
        re.MULTILINE
    )
    TYPE_DEF_PATTERN = re.compile(
        r"^type\s+(\w+)\s+(\w+(?:\[[^\]]*\])?)$",
        re.MULTILINE
    )
    PACKAGE_PATTERN = re.compile(r"^package\s+(\w+)", re.MULTILINE)
    
    IMPORT_SINGLE_PATTERN = re.compile(
        r'^import\s+(?:(\w+|\.|\\_)\s+)?"([^"]+)"',
        re.MULTILINE
    )
    IMPORT_GROUP_START = re.compile(r"^import\s*\(", re.MULTILINE)
    IMPORT_GROUP_LINE = re.compile(
        r'^\s+(?:(\w+|\.|\\_)\s+)?"([^"]+)"',
        re.MULTILINE
    )

    def parse_file(self, path: str, source: str) -> ParseResult:
        """Parse Go source file.
        
        Args:
            path: File path for chunk ID generation
            source: Go source code
            
        Returns:
            ParseResult with chunks, imports, exports
        """
        package_name = self._extract_package(source)
        chunks = self._extract_chunks(source, path, package_name)
        imports = self._extract_imports(source)
        exports = self._infer_exports(chunks)
        
        return ParseResult(
            chunks=chunks,
            imports=imports,
            exports=exports,
            errors=[],
        )

    def supports_ast(self) -> bool:
        """Go regex adapter doesn't use tree-sitter."""
        return False

    def _extract_package(self, source: str) -> Optional[str]:
        """Extract package name from source."""
        match = self.PACKAGE_PATTERN.search(source)
        if match:
            return match.group(1)
        return None

    def _extract_chunks(
        self, source: str, path: str, package_name: Optional[str]
    ) -> List[ChunkResult]:
        """Extract function, method, struct, and interface chunks from source."""
        chunks: List[ChunkResult] = []
        lines = source.split("\n")
        
        # Extract methods first (more specific pattern)
        for match in self.METHOD_PATTERN.finditer(source):
            receiver_name = match.group(1)
            receiver_type = match.group(2)
            name = match.group(3)
            params = match.group(4) or ""
            returns_tuple = match.group(5)
            returns_single = match.group(6)
            returns = returns_tuple or returns_single or ""
            
            line_num = source[:match.start()].count("\n") + 1
            end_line = self._find_brace_block_end(lines, line_num - 1)
            
            signature = self._format_method_signature(
                name, receiver_name, receiver_type, params, returns
            )
            docstring = self._extract_go_doc(lines, line_num)
            exported = self._is_go_exported(name)
            
            chunk = ChunkResult(
                id=generate_chunk_id(path, line_num, "method", name),
                type="method",
                name=name,
                signature=signature,
                start_line=line_num,
                end_line=end_line,
                parent=None,
                exported=exported,
                docstring=docstring,
                metadata={
                    "receiver_name": receiver_name,
                    "receiver_type": receiver_type.strip(),
                    "params": params,
                    "returns": returns.strip() if returns else None,
                    "package": package_name,
                },
            )
            chunks.append(chunk)
        
        # Extract functions (excluding already matched methods)
        method_starts = {source[:m.start()].count("\n") + 1 for m in self.METHOD_PATTERN.finditer(source)}
        
        for match in self.FUNCTION_PATTERN.finditer(source):
            line_num = source[:match.start()].count("\n") + 1
            if line_num in method_starts:
                continue
            
            name = match.group(1)
            params = match.group(2) or ""
            returns_tuple = match.group(3)
            returns_single = match.group(4)
            returns = returns_tuple or returns_single or ""
            
            end_line = self._find_brace_block_end(lines, line_num - 1)
            
            signature = self._format_func_signature(name, params, returns)
            docstring = self._extract_go_doc(lines, line_num)
            exported = self._is_go_exported(name)
            
            chunk = ChunkResult(
                id=generate_chunk_id(path, line_num, "function", name),
                type="function",
                name=name,
                signature=signature,
                start_line=line_num,
                end_line=end_line,
                parent=None,
                exported=exported,
                docstring=docstring,
                metadata={
                    "params": params,
                    "returns": returns.strip() if returns else None,
                    "package": package_name,
                },
            )
            chunks.append(chunk)
        
        # Extract structs
        for match in self.STRUCT_PATTERN.finditer(source):
            name = match.group(1)
            line_num = source[:match.start()].count("\n") + 1
            end_line = self._find_brace_block_end(lines, line_num - 1)
            
            signature = f"type {name} struct"
            docstring = self._extract_go_doc(lines, line_num)
            exported = self._is_go_exported(name)
            
            fields = self._extract_struct_fields(lines, line_num, end_line)
            
            chunk = ChunkResult(
                id=generate_chunk_id(path, line_num, "struct", name),
                type="struct",
                name=name,
                signature=signature,
                start_line=line_num,
                end_line=end_line,
                parent=None,
                exported=exported,
                docstring=docstring,
                metadata={
                    "fields": fields,
                    "package": package_name,
                },
            )
            chunks.append(chunk)
        
        # Extract interfaces
        for match in self.INTERFACE_PATTERN.finditer(source):
            name = match.group(1)
            line_num = source[:match.start()].count("\n") + 1
            end_line = self._find_brace_block_end(lines, line_num - 1)
            
            signature = f"type {name} interface"
            docstring = self._extract_go_doc(lines, line_num)
            exported = self._is_go_exported(name)
            
            chunk = ChunkResult(
                id=generate_chunk_id(path, line_num, "interface", name),
                type="interface",
                name=name,
                signature=signature,
                start_line=line_num,
                end_line=end_line,
                parent=None,
                exported=exported,
                docstring=docstring,
                metadata={
                    "package": package_name,
                },
            )
            chunks.append(chunk)
        
        # Extract type aliases
        for match in self.TYPE_ALIAS_PATTERN.finditer(source):
            name = match.group(1)
            alias_target = match.group(2).strip()
            line_num = source[:match.start()].count("\n") + 1
            
            signature = f"type {name} = {alias_target}"
            docstring = self._extract_go_doc(lines, line_num)
            exported = self._is_go_exported(name)
            
            chunk = ChunkResult(
                id=generate_chunk_id(path, line_num, "type", name),
                type="type",
                name=name,
                signature=signature,
                start_line=line_num,
                end_line=line_num,
                parent=None,
                exported=exported,
                docstring=docstring,
                metadata={
                    "alias_target": alias_target,
                    "package": package_name,
                },
            )
            chunks.append(chunk)
        
        # Sort by line number
        chunks.sort(key=lambda c: c.start_line)
        
        return chunks

    def _extract_imports(self, source: str) -> List[ImportResult]:
        """Extract import statements from source."""
        imports: List[ImportResult] = []
        lines = source.split("\n")
        
        # Single imports: import "fmt" or import alias "path"
        for match in self.IMPORT_SINGLE_PATTERN.finditer(source):
            alias = match.group(1)
            module = match.group(2)
            line_num = source[:match.start()].count("\n") + 1
            
            imports.append(ImportResult(
                module=module,
                symbols=[],
                alias=alias if alias and alias not in (".", "_") else None,
                is_relative=False,
                line=line_num,
                is_type_only=alias == "_",
            ))
        
        # Grouped imports: import ( ... )
        in_import_group = False
        import_group_start = 0
        
        for i, line in enumerate(lines):
            line_num = i + 1
            stripped = line.strip()
            
            # Check for import group start
            if self.IMPORT_GROUP_START.match(stripped):
                in_import_group = True
                import_group_start = line_num
                continue
            
            # Check for import group end
            if in_import_group and stripped == ")":
                in_import_group = False
                continue
            
            # Parse import within group
            if in_import_group:
                match = self.IMPORT_GROUP_LINE.match(line)
                if match:
                    alias = match.group(1)
                    module = match.group(2)
                    
                    imports.append(ImportResult(
                        module=module,
                        symbols=[],
                        alias=alias if alias and alias not in (".", "_") else None,
                        is_relative=False,
                        line=line_num,
                        is_type_only=alias == "_",
                    ))
        
        return imports

    def _infer_exports(self, chunks: List[ChunkResult]) -> List[ExportResult]:
        """Infer exports from chunks based on Go's capitalization convention."""
        exports: List[ExportResult] = []
        
        for chunk in chunks:
            if chunk.exported:
                exports.append(ExportResult(
                    name=chunk.name,
                    type=chunk.type,
                    line=chunk.start_line,
                    is_default=False,
                ))
        
        return exports

    def _is_go_exported(self, name: str) -> bool:
        """Check if a name is exported in Go (starts with uppercase)."""
        return name[0].isupper() if name else False

    def _find_brace_block_end(self, lines: List[str], start_idx: int) -> int:
        """Find the end of a brace-delimited block.
        
        Args:
            lines: All source lines (0-indexed)
            start_idx: 0-indexed line where to start looking
            
        Returns:
            1-based line number of the closing brace
        """
        brace_count = 0
        in_string = False
        in_raw_string = False
        
        for idx in range(start_idx, len(lines)):
            line = lines[idx]
            i = 0
            
            while i < len(line):
                char = line[i]
                prev_char = line[i-1] if i > 0 else ''
                
                # Handle escape sequences
                if prev_char == '\\' and not in_raw_string:
                    i += 1
                    continue
                
                # Handle raw strings
                if char == '`':
                    in_raw_string = not in_raw_string
                    i += 1
                    continue
                
                # Skip raw string content
                if in_raw_string:
                    i += 1
                    continue
                
                # Handle regular strings
                if char == '"':
                    in_string = not in_string
                    i += 1
                    continue
                
                # Skip string content
                if in_string:
                    i += 1
                    continue
                
                # Handle single-line comments
                if char == '/' and i + 1 < len(line):
                    next_char = line[i + 1]
                    if next_char == '/':
                        break
                    elif next_char == '*':
                        i += 2
                        continue
                
                # Count braces
                if char == '{':
                    brace_count += 1
                elif char == '}':
                    brace_count -= 1
                    if brace_count == 0:
                        return idx + 1
                
                i += 1
        
        return len(lines)

    def _extract_go_doc(self, lines: List[str], def_line: int) -> Optional[str]:
        """Extract Go doc comment above a definition.
        
        Go uses // comments above the definition.
        
        Args:
            lines: Source lines
            def_line: 1-based line number of the definition
            
        Returns:
            Doc comment content or None
        """
        if def_line < 2:
            return None
        
        doc_lines: List[str] = []
        
        for i in range(def_line - 2, -1, -1):
            line = lines[i].strip()
            
            if line.startswith("//"):
                doc_lines.insert(0, line[2:].strip())
            else:
                break
        
        if doc_lines:
            return "\n".join(doc_lines)
        
        return None

    def _format_func_signature(
        self, name: str, params: str, returns: str
    ) -> str:
        """Format a function signature."""
        sig = f"func {name}({params})"
        if returns:
            returns = returns.strip()
            if "," in returns or returns.startswith("("):
                sig += f" {returns}"
            else:
                sig += f" {returns}"
        return sig

    def _format_method_signature(
        self,
        name: str,
        receiver_name: str,
        receiver_type: str,
        params: str,
        returns: str,
    ) -> str:
        """Format a method signature."""
        sig = f"func ({receiver_name} {receiver_type}) {name}({params})"
        if returns:
            returns = returns.strip()
            sig += f" {returns}"
        return sig

    def _extract_struct_fields(
        self, lines: List[str], start_line: int, end_line: int
    ) -> List[str]:
        """Extract struct field definitions.
        
        Args:
            lines: Source lines
            start_line: 1-based start line of struct
            end_line: 1-based end line of struct
            
        Returns:
            List of field definitions
        """
        fields: List[str] = []
        
        for i in range(start_line, min(end_line, len(lines))):
            line = lines[i].strip()
            
            if not line or line == "{" or line == "}" or line.startswith("//"):
                continue
            
            if line.startswith("type "):
                continue
            
            fields.append(line)
        
        return fields


# Create singleton instance for registration
go_adapter = GoAdapter()

# Register with the adapter registry
from . import register_adapter
register_adapter(go_adapter)

# Export public API
__all__ = ["GoAdapter"]
