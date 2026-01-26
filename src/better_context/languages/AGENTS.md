# src/better_context/languages

> Language-specific adapters, parsers, and syntax handling.

## 📋 Purpose

This directory contains adapters that implement the parsing logic for different programming languages. Each adapter is responsible for extracting imports, exports, and code chunks from source files of a specific language.

## 🔑 Key Components

| File | Responsibility |
|------|----------------|
| **Base Adapter** | [`base.py`](./base.py) | Abstract base class defining the `LanguageAdapter` interface. |
| **Python** | [`python.py`](./python.py) | Python parser (imports, classes, functions). |
| **TypeScript** | [`typescript.py`](./typescript.py) | TS/JS parser (imports, exports, types). |
| **Go** | [`go.py`](./go.py) | Go parser (WIP). |

## 🧩 Architecture

- **Interface**: All adapters must inherit from `LanguageAdapter` in `base.py`.
- **Registration**: Adapters are typically registered or mapped by file extension in the parent `orchestrator` or factory.
- **Dependencies**: Adapters depend on `primitives` for data structures but should **not** depend on other language adapters.
- **Parsing**: Adapters may use regex (fast/simple) or `tree-sitter` (robust/AST) strategies.

## ➕ Adding a New Language

1.  Create a new file (e.g., `rust.py`).
2.  Inherit from `LanguageAdapter`.
3.  Implement `parse_imports`, `parse_exports`, and `chunkify`.
4.  Map the new adapter to file extensions in the main configuration/factory.
5.  Add tests with sample code in `tests/fixtures/`.

## ⚠️ Pitfalls

- **Performance**: Parsing runs on every file; keep it efficient. Avoid heavy imports at module level if possible.
- **Regex limitations**: Regex is fragile for complex syntax; prefer AST-based parsing for robustness when feasible.

## 🧭 Navigation

- **Parent**: [`../AGENTS.md`](../AGENTS.md)
- **Primitives**: [`../primitives/AGENTS.md`](../primitives/AGENTS.md)
