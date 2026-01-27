# src/better_context

> Core package logic, orchestration, and CLI entry points.

## 📋 Purpose

`better_context` orchestrates the scanning, parsing, and analysis of codebases to generate AI-consumable context. It coordinates language adapters and primitives to build dependency graphs, calculate centrality metrics, and provide structured data for AI agents.

## 🔑 Key Components

| Component | File | Responsibility |
|-----------|------|----------------|
| **CLI** | [`cli.py`](./cli.py) | Entry point for `better-context` commands |
| **Scanner** | [`scanner.py`](./scanner.py) | Discovers files, handles ignores/binary detection |
| **Graph** | [`graph.py`](./graph.py) | Builds dependency graphs and analyzes cycles |
| **Centrality** | [`centrality.py`](./centrality.py) | Calculates PageRank for file importance |
| **Orchestrator** | [`orchestrator.py`](./orchestrator.py) | High-level coordination of scan/parse/graph steps |
| **Optimizer** | [`optimizer.py`](./optimizer.py) | Selects optimal context within token budgets |
| **Focus** | [`focus.py`](./focus.py) | Ego-centric context generation around a file |
| **Coupling** | [`coupling.py`](./coupling.py) | Ca/Ce/I/A/D metrics for architectural health |
| **Architecture** | [`architecture.py`](./architecture.py) | Layer detection and violation reporting |
| **Call Graph** | [`callgraph.py`](./callgraph.py) | Function-level call graph analysis |
| **Cache** | [`cache.py`](./cache.py) | Incremental parse caching |
| **Staleness** | [`staleness.py`](./staleness.py) | Manifest freshness detection |
| **Semantic Anchor** | [`semantic_anchor.py`](./semantic_anchor.py) | Content-addressable chunk IDs |

## 🏗️ Architecture & Layering

The package follows a strict layering model:

1. **Orchestration Layer** (`cli.py`, `orchestrator.py`): Coordinates high-level flows
2. **Analysis Layer** (`graph.py`, `centrality.py`, `optimizer.py`, `focus.py`, `coupling.py`, `architecture.py`, `callgraph.py`): Implements core algorithms
3. **Language Layer** (`languages/`): Handles syntax-specific parsing
4. **Primitives Layer** (`primitives/`): Defines shared data structures and fast queries

**Rule**: Upper layers import from lower layers. `primitives` must not import `languages` or `analysis`.

## 📦 Subpackages

- **[`languages/`](./languages/AGENTS.md)**: Language-specific parsing logic (Python, TypeScript, Go)
- **[`primitives/`](./primitives/AGENTS.md)**: Fast data primitives and output formatters

## 🧪 Testing

- Tests are located in `tests/`
- Run tests with `pytest`
- Use fixtures in `tests/fixtures/` for integration tests

## 🧭 Navigation

- **Parent**: [`../AGENTS.md`](../AGENTS.md)
- **Languages**: [`./languages/AGENTS.md`](./languages/AGENTS.md)
- **Primitives**: [`./primitives/AGENTS.md`](./primitives/AGENTS.md)
