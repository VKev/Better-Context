"""Python language adapter for better-context.

Provides regex-based parsing for Python source files.
Extracts functions, classes, methods, imports, and exports.
"""

from __future__ import annotations

import re
from typing import List, Optional, Tuple, Dict, Any

from .base import (
    ChunkResult,
    ImportResult,
    ExportResult,
    ParseResult,
    generate_chunk_id,
)
from ..semantic_anchor import compute_semantic_anchor


class PythonAdapter:
    """Python language adapter using regex-based parsing.
    
    Extracts:
    - Functions (def, async def)
    - Classes
    - Methods (detected by indentation within classes)
    - Import statements (import, from...import)
    - Exports (inferred from __all__ or public names)
    """

    language = "python"
    extensions = [".py", ".pyi", ".pyw"]

    # Regex patterns
    FUNCTION_PATTERN = re.compile(
        r"^(\s*)(async\s+)?def\s+(\w+)\s*\(([^)]*)\)\s*(?:->\s*([^:]+))?\s*:",
        re.MULTILINE
    )
    CLASS_PATTERN = re.compile(
        r"^(\s*)class\s+(\w+)(?:\s*\(([^)]*)\))?\s*:",
        re.MULTILINE
    )
    IMPORT_PATTERN = re.compile(
        r"^(from\s+([.\w]+)\s+)?import\s+(.+)$",
        re.MULTILINE
    )
    ALL_PATTERN = re.compile(
        r"^__all__\s*=\s*\[(.*?)\]",
        re.MULTILINE | re.DOTALL
    )
    DECORATOR_PATTERN = re.compile(r"^\s*@(\w+(?:\.\w+)*)", re.MULTILINE)

    def parse_file(self, path: str, source: str) -> ParseResult:
        """Parse Python source file.
        
        Args:
            path: File path for chunk ID generation
            source: Python source code
            
        Returns:
            ParseResult with chunks, imports, exports
        """
        chunks = self._extract_chunks(source, path)
        imports = self._extract_imports(source)
        exports = self._extract_exports(source, chunks)
        
        return ParseResult(
            chunks=chunks,
            imports=imports,
            exports=exports,
            errors=[],
        )

    def supports_ast(self) -> bool:
        """Python regex adapter doesn't use tree-sitter."""
        return False

    def _extract_chunks(self, source: str, path: str) -> List[ChunkResult]:
        """Extract function and class chunks from source."""
        chunks: List[ChunkResult] = []
        lines = source.split("\n")
        
        # Track class contexts for method detection
        class_contexts: List[Tuple[int, int, str]] = []  # (start, indent, name)
        
        # Find all classes first
        for match in self.CLASS_PATTERN.finditer(source):
            indent_str = match.group(1)
            indent = len(indent_str)
            name = match.group(2)
            bases = match.group(3) or ""
            line_num = source[:match.start()].count("\n") + 1
            
            # Find class end
            end_line = self._find_block_end(lines, line_num, indent)
            
            # Signature
            signature = f"class {name}"
            if bases:
                signature += f"({bases})"
            
            # Get docstring
            docstring = self._extract_docstring(lines, line_num)
            
            # Get decorators
            decorators = self._get_decorators(lines, line_num)
            
            # Check if exported
            exported = not name.startswith("_")
            
            # Compute semantic anchor (content-addressable ID)
            semantic_anchor = compute_semantic_anchor(
                source=source,
                start_line=line_num,
                end_line=end_line,
                language="python",
                name=name,
                chunk_type="class",
            )
            
            chunk = ChunkResult(
                id=generate_chunk_id(path, line_num, "class", name),
                type="class",
                name=name,
                signature=signature,
                start_line=line_num,
                end_line=end_line,
                parent=None,
                exported=exported,
                docstring=docstring,
                metadata={
                    "bases": bases,
                    "decorators": decorators,
                },
                semantic_anchor=semantic_anchor,
            )
            chunks.append(chunk)
            class_contexts.append((line_num, indent, chunk.id))
        
        # Find all functions
        for match in self.FUNCTION_PATTERN.finditer(source):
            indent_str = match.group(1)
            indent = len(indent_str)
            is_async = match.group(2) is not None
            name = match.group(3)
            params = match.group(4) or ""
            return_type = match.group(5)
            line_num = source[:match.start()].count("\n") + 1
            
            # Determine if method or function
            parent_id = None
            chunk_type = "function"
            
            for class_start, class_indent, class_id in class_contexts:
                if line_num > class_start and indent > class_indent:
                    parent_id = class_id
                    chunk_type = "method"
                    break
            
            # Find function end
            end_line = self._find_block_end(lines, line_num, indent)
            
            # Build signature
            prefix = "async def " if is_async else "def "
            signature = f"{prefix}{name}({params})"
            if return_type:
                signature += f" -> {return_type.strip()}"
            
            # Get docstring
            docstring = self._extract_docstring(lines, line_num)
            
            # Get decorators
            decorators = self._get_decorators(lines, line_num)
            
            # Check if exported (public name at module level)
            exported = not name.startswith("_") and chunk_type == "function"
            
            # Compute semantic anchor (content-addressable ID)
            semantic_anchor = compute_semantic_anchor(
                source=source,
                start_line=line_num,
                end_line=end_line,
                language="python",
                name=name,
                chunk_type=chunk_type,
            )
            
            chunk = ChunkResult(
                id=generate_chunk_id(path, line_num, chunk_type, name),
                type=chunk_type,
                name=name,
                signature=signature,
                start_line=line_num,
                end_line=end_line,
                parent=parent_id,
                exported=exported,
                docstring=docstring,
                metadata={
                    "is_async": is_async,
                    "decorators": decorators,
                    "params": params,
                    "return_type": return_type.strip() if return_type else None,
                },
                semantic_anchor=semantic_anchor,
            )
            chunks.append(chunk)
        
        # Sort by line number
        chunks.sort(key=lambda c: c.start_line)
        
        return chunks

    def _extract_imports(self, source: str) -> List[ImportResult]:
        """Extract import statements from source."""
        imports: List[ImportResult] = []
        
        for match in self.IMPORT_PATTERN.finditer(source):
            line_num = source[:match.start()].count("\n") + 1
            from_part = match.group(1)
            module = match.group(2)
            import_part = match.group(3).strip()
            
            if from_part:
                # from X import Y, Z
                is_relative = module.startswith(".")
                symbols = [s.strip().split(" as ")[0].strip() 
                          for s in import_part.split(",")]
                
                imports.append(ImportResult(
                    module=module,
                    symbols=symbols,
                    alias=None,
                    is_relative=is_relative,
                    line=line_num,
                ))
            else:
                # import X, Y, Z or import X as alias
                for part in import_part.split(","):
                    part = part.strip()
                    if " as " in part:
                        mod, alias = part.split(" as ")
                        imports.append(ImportResult(
                            module=mod.strip(),
                            symbols=[],
                            alias=alias.strip(),
                            is_relative=False,
                            line=line_num,
                        ))
                    else:
                        imports.append(ImportResult(
                            module=part,
                            symbols=[],
                            alias=None,
                            is_relative=False,
                            line=line_num,
                        ))
        
        return imports

    def _extract_exports(
        self, source: str, chunks: List[ChunkResult]
    ) -> List[ExportResult]:
        """Extract exports from source.
        
        Python exports are inferred from:
        1. __all__ list if defined
        2. Public names (not starting with _) at module level
        """
        exports: List[ExportResult] = []
        
        # Check for __all__
        all_match = self.ALL_PATTERN.search(source)
        if all_match:
            all_content = all_match.group(1)
            # Parse string literals from __all__
            names = re.findall(r'["\'](\w+)["\']', all_content)
            line_num = source[:all_match.start()].count("\n") + 1
            
            for name in names:
                # Find the chunk for this export
                chunk = next((c for c in chunks if c.name == name), None)
                exports.append(ExportResult(
                    name=name,
                    type=chunk.type if chunk else "unknown",
                    line=chunk.start_line if chunk else line_num,
                    is_default=False,
                ))
        else:
            # Infer from public module-level definitions
            for chunk in chunks:
                if chunk.exported and chunk.parent is None:
                    exports.append(ExportResult(
                        name=chunk.name,
                        type=chunk.type,
                        line=chunk.start_line,
                        is_default=False,
                    ))
        
        return exports

    def _find_block_end(
        self, lines: List[str], start_line: int, start_indent: int
    ) -> int:
        """Find the end line of a Python block based on indentation.
        
        Args:
            lines: Source lines
            start_line: 1-based start line
            start_indent: Indentation level of the block start
            
        Returns:
            1-based end line number
        """
        end_line = start_line
        
        for i in range(start_line, len(lines)):
            line = lines[i]
            stripped = line.strip()
            
            # Skip empty lines and comments
            if not stripped or stripped.startswith("#"):
                continue
            
            # Calculate indent
            line_indent = len(line) - len(line.lstrip())
            
            # If we've dedented, the block has ended
            if line_indent <= start_indent and i > start_line - 1:
                break
            
            end_line = i + 1  # Convert to 1-based
        
        return end_line

    def _extract_docstring(self, lines: List[str], def_line: int) -> Optional[str]:
        """Extract docstring from after a definition.
        
        Args:
            lines: Source lines
            def_line: 1-based line number of the definition
            
        Returns:
            Docstring content or None
        """
        if def_line >= len(lines):
            return None
        
        # Look at the next line
        next_line = lines[def_line].strip()  # def_line is 1-based, so this is the line after
        
        # Check for triple-quoted string
        for quote in ('"""', "'''"):
            if next_line.startswith(quote):
                # Single-line docstring
                if next_line.endswith(quote) and len(next_line) > 6:
                    return next_line[3:-3].strip()
                
                # Multi-line docstring
                doc_lines = [next_line[3:]]
                for line in lines[def_line + 1:]:
                    if quote in line:
                        doc_lines.append(line[:line.index(quote)])
                        break
                    doc_lines.append(line)
                
                return "\n".join(doc_lines).strip()
        
        return None

    def _get_decorators(self, lines: List[str], def_line: int) -> List[str]:
        """Get decorators above a definition.
        
        Args:
            lines: Source lines
            def_line: 1-based line number of the definition
            
        Returns:
            List of decorator names
        """
        decorators: List[str] = []
        
        # Look backwards from the definition
        for i in range(def_line - 2, -1, -1):  # -2 because 1-based and we start above
            line = lines[i].strip()
            
            # Empty line or non-decorator ends the search
            if not line:
                break
            if not line.startswith("@"):
                break
            
            # Extract decorator name
            match = self.DECORATOR_PATTERN.match(lines[i])
            if match:
                decorators.insert(0, match.group(1))
        
        return decorators


# Create singleton instance for registration
python_adapter = PythonAdapter()

# Register with the adapter registry
from . import register_adapter
register_adapter(python_adapter)

# Export public API
__all__ = ["PythonAdapter"]
