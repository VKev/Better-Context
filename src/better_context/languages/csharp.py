"""Small, dependency-free C# parser tuned for Unity project maps."""

from __future__ import annotations

import re

from .base import ChunkResult, ExportResult, ImportResult, ParseResult, generate_chunk_id


class CSharpAdapter:
    """Extract C# types, methods, namespaces, and using directives."""

    language = "csharp"
    extensions = [".cs"]

    _MODIFIER = (
        r"public|internal|protected|private|abstract|sealed|static|partial|readonly|"
        r"ref|new|unsafe|virtual|override|async|extern"
    )
    TYPE_PATTERN = re.compile(
        rf"^\s*(?P<mods>(?:(?:{_MODIFIER})\s+)*)"
        r"(?P<kind>class|interface|struct|enum|record(?:\s+(?:class|struct))?)\s+"
        r"(?P<name>[A-Za-z_]\w*)(?:\s*<[^>{}]+>)?"
        r"(?:\s*\([^)]*\))?(?:\s*:\s*(?P<bases>[^{{]+?))?\s*(?:\{{|where\b|$)",
        re.MULTILINE,
    )
    METHOD_PATTERN = re.compile(
        rf"^\s*(?P<mods>(?:(?:{_MODIFIER})\s+)*)"
        r"(?P<return>[A-Za-z_]\w*(?:\s*<[^;={}]+>)?(?:[?.\[\],]\w*)*)\s+"
        r"(?P<name>[A-Za-z_]\w*)\s*(?:<[^>{}]+>)?\s*\([^;{}]*\)"
        r"(?:\s*where\s+[^={]+)?\s*(?:=>|\{|$)",
        re.MULTILINE,
    )
    USING_PATTERN = re.compile(
        r"^\s*(?:global\s+)?using\s+(?:(?P<static>static)\s+)?"
        r"(?:(?P<alias>[A-Za-z_]\w*)\s*=\s*)?(?P<module>[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*)\s*;",
        re.MULTILINE,
    )
    NAMESPACE_PATTERN = re.compile(
        r"^\s*namespace\s+([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*)\s*(?:;|\{)",
        re.MULTILINE,
    )
    CONTROL_NAMES = {"if", "for", "foreach", "while", "switch", "catch", "using", "lock"}
    UNITY_BASES = {"MonoBehaviour", "ScriptableObject", "EditorWindow", "StateMachineBehaviour"}

    def parse_file(self, path: str, source: str) -> ParseResult:
        lines = source.splitlines()
        namespace_match = self.NAMESPACE_PATTERN.search(source)
        namespace = namespace_match.group(1) if namespace_match else None
        chunks: list[ChunkResult] = []

        type_chunks: list[ChunkResult] = []
        for match in self.TYPE_PATTERN.finditer(source):
            line = source.count("\n", 0, match.start()) + 1
            end = self._find_block_end(lines, line)
            modifiers = match.group("mods").split()
            kind = match.group("kind").split()[-1]
            name = match.group("name")
            bases = self._split_bases(match.group("bases"))
            unity_type = next((base for base in bases if base in self.UNITY_BASES), None)
            chunk = ChunkResult(
                id=generate_chunk_id(path, line, kind, name),
                type=kind,
                name=name,
                signature=self._signature(lines, line),
                start_line=line,
                end_line=end,
                exported="public" in modifiers or "protected" in modifiers,
                docstring=self._xml_doc(lines, line),
                metadata={
                    "namespace": namespace,
                    "bases": bases,
                    "unity_type": unity_type,
                    "partial": "partial" in modifiers,
                },
            )
            type_chunks.append(chunk)
            chunks.append(chunk)

        for match in self.METHOD_PATTERN.finditer(source):
            name = match.group("name")
            if name in self.CONTROL_NAMES:
                continue
            line = source.count("\n", 0, match.start()) + 1
            modifiers = match.group("mods").split()
            parent = next(
                (item for item in reversed(type_chunks) if item.start_line < line <= item.end_line),
                None,
            )
            chunks.append(
                ChunkResult(
                    id=generate_chunk_id(path, line, "method", name),
                    type="method",
                    name=name,
                    signature=self._signature(lines, line),
                    start_line=line,
                    end_line=self._find_block_end(lines, line),
                    parent=parent.id if parent else None,
                    exported="public" in modifiers or "protected" in modifiers,
                    docstring=self._xml_doc(lines, line),
                    metadata={"namespace": namespace, "return_type": match.group("return")},
                )
            )

        imports = [
            ImportResult(
                module=match.group("module"),
                alias=match.group("alias"),
                line=source.count("\n", 0, match.start()) + 1,
            )
            for match in self.USING_PATTERN.finditer(source)
        ]
        exports = [
            ExportResult(name=chunk.name, type=chunk.type, line=chunk.start_line)
            for chunk in chunks
            if chunk.exported
        ]
        return ParseResult(chunks=chunks, imports=imports, exports=exports)

    def supports_ast(self) -> bool:
        return False

    @staticmethod
    def _split_bases(value: str | None) -> list[str]:
        if not value:
            return []
        return [part.strip().split("<", 1)[0].split(".")[-1] for part in value.split(",")]

    @staticmethod
    def _signature(lines: list[str], line: int) -> str:
        if not lines:
            return ""
        value = lines[line - 1].strip()
        return value.split("{", 1)[0].split("=>", 1)[0].strip()

    @staticmethod
    def _find_block_end(lines: list[str], line: int) -> int:
        depth = 0
        opened = False
        for index in range(max(line - 1, 0), len(lines)):
            for char in lines[index]:
                if char == "{":
                    depth += 1
                    opened = True
                elif char == "}" and opened:
                    depth -= 1
                    if depth == 0:
                        return index + 1
            if not opened and ";" in lines[index]:
                return index + 1
        return len(lines) if opened else line

    @staticmethod
    def _xml_doc(lines: list[str], line: int) -> str | None:
        docs: list[str] = []
        index = line - 2
        while index >= 0 and lines[index].lstrip().startswith("///"):
            docs.insert(0, lines[index].lstrip()[3:].strip())
            index -= 1
        if not docs:
            return None
        text = " ".join(docs)
        return re.sub(r"</?[^>]+>", "", text).strip() or None


from . import register_adapter  # noqa: E402 - registry is initialized before adapters load

register_adapter(CSharpAdapter())

__all__ = ["CSharpAdapter"]
