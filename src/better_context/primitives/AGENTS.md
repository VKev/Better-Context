# src/better_context/primitives

> Core data structures, types, and fundamental building blocks.

## 📋 Purpose

This directory defines the shared vocabulary and data models used throughout the system. These primitives are the "currency" exchanged between the scanner, parsers, graph analyzer, and generator. They are designed to be stable, serializable, and dependency-light.

## 🔑 Key Types

| File | Key Classes/Types | Description |
|------|-------------------|-------------|
| **File Info** | [`file_info.py`](./file_info.py) | `FileInfo`: Metadata about a source file (path, size, hash). |
| **Entries** | [`entries.py`](./entries.py) | `Entry`: Represents a code element (function, class). |
| **Deps** | [`deps.py`](./deps.py) | `Dependency`: Represents an import relationship. |
| **Tree** | [`tree.py`](./tree.py) | Directory tree structures. |
| **Project** | [`project.py`](./project.py) | `Project`: Top-level container for analysis results. |

## 📏 Invariants & Rules

- **No Upward Dependencies**: Primitives must **never** import from `languages` or `better_context` core. They are the leaf nodes of the dependency graph.
- **Immutability**: Prefer immutable data classes (`@dataclass(frozen=True)`) for core models to prevent accidental side effects during analysis.
- **Serialization**: Models should be easily serializable to JSON (for caching and output).

## 🔄 Change Guidance

- **High Impact**: specific primitives are used everywhere. Changing a field in `FileInfo` or `Dependency` will ripple through the entire codebase (parsers, graph, generator).
- **Versioning**: If the serialization format changes, ensure backward compatibility or bump the manifest version.

## 🧭 Navigation

- **Parent**: [`../AGENTS.md`](../AGENTS.md)
