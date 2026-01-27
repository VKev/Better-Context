# src/better_context/primitives

> Fast data primitives and output formatters for AI agent queries.

## 📋 Purpose

This directory provides sub-200ms data primitives that AI agents can query on-demand without requiring a full codebase scan. It also contains the shared data models used throughout the system.

## 🔑 Fast Primitives

| Primitive | File | Description |
|-----------|------|-------------|
| **Overview** | [`overview.py`](./overview.py) | Project metadata (language, framework, package manager) |
| **Tree** | [`tree.py`](./tree.py) | Directory structure with file counts |
| **Scripts** | [`scripts.py`](./scripts.py) | Runnable scripts from package files |
| **Entries** | [`entries.py`](./entries.py) | Entry point detection (CLI, main, server) |
| **File Info** | [`file_info.py`](./file_info.py) | Single file metadata, chunks, imports, exports |
| **Deps** | [`deps.py`](./deps.py) | Dependencies and dependents for a file |
| **Formatters** | [`formatters.py`](./formatters.py) | Output formatters (JSON, human, markdown) |

## 🔧 Data Types

| File | Key Classes | Description |
|------|-------------|-------------|
| **Project** | [`project.py`](./project.py) | `ProjectDetection`, `ProjectTooling` |
| **Entry** | [`entry.py`](./entry.py) | `EntryPoint` data model |
| **Script** | [`script.py`](./script.py) | `Script` data model |
| **File** | [`file.py`](./file.py) | `FileInfo` data model |
| **Base** | [`base.py`](./base.py) | Shared utilities and timing helpers |

## 📏 Invariants & Rules

- **No Upward Dependencies**: Primitives must **never** import from `languages` or `better_context` core. They are the leaf nodes of the dependency graph.
- **Fast by Design**: Primitives target sub-200ms execution. Avoid heavy computation or full codebase traversal.
- **Output Flexibility**: All primitives support JSON (default), human-readable, and markdown output via `--format`.
- **Serialization**: Models should be easily serializable to JSON.

## 🔄 Change Guidance

- **High Impact**: Primitives are used by the CLI and exported in `__init__.py`. Changing signatures affects the public API.
- **Performance**: Monitor execution time. These are the hot path for AI agent queries.

## 🧭 Navigation

- **Parent**: [`../AGENTS.md`](../AGENTS.md)
