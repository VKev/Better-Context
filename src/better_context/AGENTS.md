# src/better_context

> Core package logic, orchestration, and CLI entry points.

## 📋 Purpose

`better_context` orchestrates the scanning, parsing, and analysis of codebases to generate AI-consumable context. It coordinates language adapters and primitives to build dependency graphs, calculate centrality, and render hierarchical markdown.

## 🔑 Key Components

| Component | File | Responsibility |
|-----------|------|----------------|
| **CLI** | [`cli.py`](./cli.py) | Entry point for `better-context` commands. |
| **Scanner** | [`scanner.py`](./scanner.py) | Discovers files, handles ignores/binary detection. |
| **Graph** | [`graph.py`](./graph.py) | Builds dependency graphs and analyzes cycles. |
| **Centrality** | [`centrality.py`](./centrality.py) | Calculates PageRank for file importance. |
| **Generator** | [`generator.py`](./generator.py) | Renders AGENTS.md files from analysis. |
| **Orchestrator** | [`orchestrator.py`](./orchestrator.py) | high-level coordination of scan/parse/graph steps. |
| **Optimizer** | [`optimizer.py`](./optimizer.py) | Selects optimal context within token budgets. |

## 🏗️ Architecture & Layering

The package follows a strict layering model:

1.  **Orchestration Layer** (`cli.py`, `orchestrator.py`, `generator.py`): Coordinates high-level flows.
2.  **Analysis Layer** (`graph.py`, `centrality.py`, `optimizer.py`, `scanner.py`): Implements core algorithms.
3.  **Language Layer** (`languages/`): Handles syntax-specific parsing.
4.  **Primitives Layer** (`primitives/`): Defines shared data structures.

**Rule**: Upper layers import from lower layers. `primitives` must not import `languages` or `analysis`.

## 📦 Subpackages

- **[`languages/`](./languages/AGENTS.md)**: Language-specific parsing logic.
- **[`primitives/`](./primitives/AGENTS.md)**: Core data types and models.

## 🧪 Testing

- Tests are located in `tests/`.
- Run tests with `pytest`.
- Use fixtures in `tests/fixtures/` for integration tests.

## 🧭 Navigation

- **Parent**: [`../AGENTS.md`](../AGENTS.md)
- **Languages**: [`./languages/AGENTS.md`](./languages/AGENTS.md)
- **Primitives**: [`./primitives/AGENTS.md`](./primitives/AGENTS.md)
