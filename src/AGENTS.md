# src

> Source code root for the `better_context` package.

## 📋 Purpose

This directory contains the source code for the `better-context` package, which provides AI agent codebase intelligence. The code is organized into a single top-level package with clear separation between core primitives, language implementations, and high-level logic.

## 📂 Directory Map

- **[`better_context/`](./better_context/AGENTS.md)**: The main package containing core logic, CLI, and submodules.
  - **[`better_context/languages/`](./better_context/languages/AGENTS.md)**: Language-specific adapters and parsers.
  - **[`better_context/primitives/`](./better_context/primitives/AGENTS.md)**: Foundational data structures and types.

## 🛠️ Key Workflows

- **Run tests**: `pytest` (from project root)
- **Type check**: `mypy src/`
- **Lint**: `ruff check src/`
- **Format**: `ruff format src/`

## 📦 Dependencies

- **Runtime**: Python 3.9+
- **Key Libraries**: `tree-sitter`, `rich`, `typer` (optional full dependencies)
- **Package Manager**: `uv` / `pip` (via `pyproject.toml`)

## 🧭 Navigation

- **Project Root**: [`../AGENTS.md`](../AGENTS.md)
- **Tests**: [`../tests/AGENTS.md`](../tests/AGENTS.md) (if available)
