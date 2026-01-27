# Better Context

> AI Agent Codebase Intelligence CLI

[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

**Better Context** transforms unstructured codebases into structured, AI-consumable context using graph theory and fast primitives. It provides data primitives that AI agents can query on-demand, along with deep analysis tools for dependency graphs, centrality metrics, and token-optimized context selection.

## Quick Start

```bash
# Run directly with uv (no install required)
uvx better-context overview
uvx better-context tree --depth 2

# Or install from PyPI
pip install better-context
better-context overview

# Deep analysis (requires indexing first)
better-context scan
better-context stats
better-context focus src/main.py
```

The fast primitives (`overview`, `tree`, `scripts`, `entries`, `file`, `deps`) return structured data in ~50-200ms without requiring a full codebase scan. For deeper analysis like PageRank centrality and dependency graphs, run `scan` first.

## Why Better Context?

Traditional approaches to giving AI agents codebase context fall short:

| Approach | Problem |
|----------|---------|
| Dump entire files | Overwhelms context windows |
| Grep-based discovery | Misses relationships |
| Flat documentation | Lacks navigation structure |

**Better Context** solves this with a two-tier approach:

### Fast Primitives (no indexing required)

| Primitive | Purpose | Target Time |
|-----------|---------|-------------|
| `overview` | Project type, framework, package manager | ~100ms |
| `tree` | Directory structure with file counts | ~50ms |
| `scripts` | Available commands from package files | ~50ms |
| `entries` | Entry point detection (CLI, main, server) | ~50ms |
| `file <path>` | Single file metadata, chunks, imports, exports | ~200ms |
| `deps <path>` | Dependencies and dependents for a file | ~100ms |

### Deep Analysis (requires `scan` first)

- **PageRank centrality** for mathematical file importance ranking
- **Dependency graph analysis** with cycle detection
- **Coupling metrics** (Ca/Ce/I/A/D) for architectural health
- **Architecture layer detection** with violation reporting
- **Call graph analysis** at the function level
- **Token budget optimization** for precise context selection
- **Focus mode** for ego-centric context around a specific file
- **Semantic anchors** for refactor-stable code references

## What It Does

1. **Primal Scan**: Fast discovery of project structure and capabilities
2. **On-Demand Parsing**: Parse only what's needed, when it's needed
3. **Graph Analysis**: Build dependency graphs for deep understanding
4. **Context Optimization**: Fit the most relevant code into limited token windows
5. **Format Flexibility**: Output as JSON (for tools), Markdown (for LLMs), or Human (for people)

## Installation

### Run Directly with uv (Recommended)

No installation required! Just use `uvx` to run directly:

```bash
# Run any command directly
uvx better-context overview
uvx better-context tree --depth 2
uvx better-context scan

# Run from git before PyPI release
uvx --from "git+https://github.com/better-context/better-context.git" better-context overview

# With optional dependencies (tree-sitter for enhanced parsing)
uvx --from "better-context[full]" better-context overview
```

### From PyPI

```bash
pip install better-context
```

### With uv

```bash
uv add better-context
```

### With Optional Dependencies

```bash
# Full installation with tree-sitter, rich CLI, typer
pip install "better-context[full]"
```

### Development Installation

```bash
git clone https://github.com/better-context/better-context
cd better-context
pip install -e ".[dev]"
```

## Commands

### Fast Primitives

These commands return structured data without requiring a manifest. Default output is JSON; use `--format human` or `--format markdown` for alternative formats.

| Command | Description |
|---------|-------------|
| `better-context overview` | Project metadata (language, framework, package manager) |
| `better-context tree` | Directory structure with file counts |
| `better-context scripts` | Runnable scripts from package files (npm, poetry, make) |
| `better-context entries` | Entry points (CLI commands, main scripts, servers) |
| `better-context file <path>` | File metadata, chunks, imports, and exports |
| `better-context deps <path>` | Dependencies and dependents for a file |

### Deep Analysis

These commands require running `better-context scan` first to build the manifest.

| Command | Description |
|---------|-------------|
| `better-context scan [path]` | Index codebase and generate manifest |
| `better-context stats` | Codebase statistics with PageRank centrality |
| `better-context graph` | Export dependency graph (Mermaid, DOT, JSON) |
| `better-context focus <file>` | Ego-centric context centered on a file |
| `better-context optimize` | Select optimal context within token budget |
| `better-context verify` | Check if manifest is stale |
| `better-context clean` | Remove generated files and caches |

### Examples

```bash
# Fast primitives (no scan required)
better-context overview                          # Project metadata as JSON
better-context overview --format human           # Human-readable output
better-context tree --depth 3                    # Directory tree, 3 levels deep
better-context scripts --format markdown         # Scripts as markdown table
better-context entries                           # Find entry points
better-context file src/auth/jwt.py              # Analyze single file
better-context file src/api/routes.ts --format human

# Deep analysis (run scan first)
better-context scan                              # Index codebase
better-context scan --out manifest.json          # Custom output path
better-context stats                             # PageRank-ranked files
better-context stats --json                      # Stats as JSON

# Dependency graph export
better-context graph -f mermaid > deps.md        # Mermaid diagram
better-context graph -f dot > deps.dot           # Graphviz DOT
better-context graph -f json > deps.json         # JSON for custom tools

# Focus mode
better-context focus src/auth/jwt.py             # Context around a file
better-context focus src/auth/jwt.py --depth 2   # Limit exploration depth
better-context focus src/auth/jwt.py --json      # Output as JSON

# Token budget optimization
better-context optimize --budget 8000            # Select best context
better-context optimize -b 4000 -k auth user     # Boost relevance by keywords
better-context optimize -b 8000 --task "fix auth bug"

# Maintenance
better-context verify                            # Check if manifest is stale
better-context clean                             # Remove all generated files
better-context clean --cache-only                # Keep manifest, remove cache
```

### Global Options

| Option | Description |
|--------|-------------|
| `--root PATH` | Project root directory (default: current) |
| `--config PATH` | Path to .ctx.json config file |
| `-v, --verbose` | Increase verbosity (-v, -vv, -vvv) |
| `--no-color` | Disable colored output |
| `--version` | Show version |

## Configuration

### .ctx.json

Create a `.ctx.json` file in your project root to customize behavior:

```json
{
  "max_file_size_kb": 500,
  "chunk_max_lines": 150,
  "chunk_min_lines": 10,
  "pagerank_damping": 0.85,
  "pagerank_iterations": 20,
  "output_dir": ".better-context",
  "generate_agents_md": true,
  "language_overrides": {
    ".h": "cpp",
    ".m": "objc"
  }
}
```

#### Configuration Options

| Option | Default | Description |
|--------|---------|-------------|
| `max_file_size_kb` | 500 | Skip files larger than this |
| `chunk_max_lines` | 150 | Maximum lines per code chunk |
| `chunk_min_lines` | 10 | Minimum lines to form a chunk |
| `pagerank_damping` | 0.85 | PageRank damping factor (0-1) |
| `pagerank_iterations` | 20 | PageRank convergence iterations |
| `output_dir` | .better-context | Directory for manifest output |
| `generate_agents_md` | true | Whether to generate AGENTS.md |
| `language_overrides` | {} | Map extensions to languages |

### .ctxignore

Create a `.ctxignore` file (gitignore-like syntax) to exclude files:

```gitignore
# Dependencies (ignored by default, but you can customize)
node_modules/
vendor/

# Large generated files
*.bundle.js
*.min.js
*.map

# Project-specific exclusions
legacy/
docs/generated/

# But include important fixtures
!fixtures/critical/
```

#### Default Ignores

These patterns are always ignored (you don't need to specify them):

- Version control: `.git/`, `.svn/`, `.hg/`
- Dependencies: `node_modules/`, `vendor/`, `venv/`, `__pycache__/`
- Build outputs: `dist/`, `build/`, `target/`, `.next/`
- IDE files: `.idea/`, `.vscode/`, `*.swp`
- Lock files: `package-lock.json`, `yarn.lock`, `poetry.lock`
- Our output: `.better-context/`

## How It Works

### Architecture

```
┌─────────────┐    ┌─────────────┐    ┌─────────────┐    ┌─────────────┐
│   Scanner   │───▶│   Parser    │───▶│   Graph     │───▶│  Generator  │
│             │    │             │    │   Analysis  │    │             │
│ • Walk tree │    │ • Chunks    │    │ • PageRank  │    │ • Templates │
│ • Binary    │    │ • Imports   │    │ • Cycles    │    │ • AGENTS.md │
│   detect    │    │ • Exports   │    │ • Layers    │    │   hierarchy │
└─────────────┘    └─────────────┘    └─────────────┘    └─────────────┘
```

### 1. Scanning Phase

The scanner walks your codebase and discovers files:
- Detects binary files via extension check (O(1)) and null-byte detection
- Applies ignore patterns (.ctxignore + defaults)
- Computes content hashes for caching
- Detects programming language from extensions

### 2. Parsing Phase

Each file is parsed using language-specific adapters:
- **Regex mode** (zero dependencies): Pattern matching for function/class boundaries
- **AST mode** (with tree-sitter): Full syntax tree parsing for accuracy

Currently supported languages:
- Python (.py, .pyi, .pyw)
- TypeScript (.ts, .tsx)
- JavaScript (.js, .jsx, .mjs, .cjs)
- Go (.go) - coming soon

### 3. Graph Analysis Phase

Build and analyze the dependency graph:

- **Dependency Graph**: Directed graph where edges represent imports
- **PageRank Centrality**: Ranks files by structural importance
  - Files imported by many important files rank higher
  - Based on Google's original algorithm (damping factor 0.85)
- **Cycle Detection**: Tarjan's SCC algorithm finds circular dependencies
- **Topological Layers**: Kahn's algorithm assigns files to dependency layers

### 4. Generation Phase

Generate hierarchical AGENTS.md files:

```
project/
├── AGENTS.md                 # Project overview, architecture
├── src/
│   ├── AGENTS.md            # src/ module overview
│   └── api/
│       └── AGENTS.md        # API module detail
```

Each AGENTS.md contains:
- **Purpose**: What this module does
- **Key Files**: Ranked by centrality with descriptions
- **Public API**: Exported symbols with signatures
- **Dependencies**: Internal and external imports
- **Circular Dependencies**: Warnings if detected
- **Navigation**: Links to parent/child modules

## Output: AGENTS.md Hierarchy

### Root AGENTS.md Example

```markdown
# my-project

> Auto-generated context for AI agents. Last updated: 2026-01-24T10:30:00Z

## 📋 Purpose

A Python project with 42 files.

## 🔑 Key Files (by Centrality)

| File | Score | Why It Matters |
|------|-------|----------------|
| `src/core/utils.py` | 0.1523 | 15 exports - 8 dependents |
| `src/api/routes.py` | 0.0891 | 6 exports - 5 dependents |
| `src/models/user.py` | 0.0654 | type definitions |

## ⚠️ Circular Dependencies

The following cycles were detected:
- auth.py → session.py → user.py → auth.py

## 🧭 Navigation

- **Source code?** Start with: [`./src/AGENTS.md`](./src/AGENTS.md)
- **Tests?** Start with: [`./tests/AGENTS.md`](./tests/AGENTS.md)
```

## Supported Languages

| Language | Extensions | Import Parsing | Export Parsing |
|----------|------------|----------------|----------------|
| Python | .py, .pyi, .pyw | ✅ | ✅ |
| TypeScript | .ts, .tsx | ✅ | ✅ |
| JavaScript | .js, .jsx, .mjs, .cjs | ✅ | ✅ |
| Go | .go | 🚧 (coming soon) | 🚧 |

## Algorithm Details

### PageRank Centrality

Files are ranked using the PageRank algorithm:

```
PR(f) = (1-d)/N + d × Σ PR(g)/L(g) for all g importing f
```

Where:
- `d` = damping factor (0.85)
- `N` = total files
- `L(g)` = number of files that `g` imports

**Intuition**: A file is important if:
1. Many files import it (direct importance)
2. *Important* files import it (transitive importance)

### Cycle Detection (Tarjan's SCC)

Circular dependencies are detected using Tarjan's strongly connected components algorithm:
- O(V + E) complexity
- Finds *all* cycles, not just one
- Reports suggested break points (the edge from the most-imported file)

### Topological Layers (Kahn's Algorithm)

Files are assigned to layers for bottom-up understanding:
- **Layer 0**: Files with no imports (foundations)
- **Layer N**: Files that only import from layers 0..N-1

## Development

```bash
# Install dev dependencies
pip install -e ".[dev]"

# Run tests
pytest

# Run performance tests (opt-in)
BC_PERF=1 pytest -m perf

# Run tests with coverage
pytest --cov=src/better_context

# Type checking
mypy src/

# Linting
ruff check src/

# Format code
ruff format src/
```

### Project Structure

```
src/better_context/
├── cli.py              # CLI entry point and command handlers
├── config.py           # Configuration loader (.ctx.json)
├── ignore.py           # .ctxignore pattern matching
├── scanner.py          # File discovery and binary detection
├── manifest.py         # Manifest JSON schema
├── graph.py            # Dependency graph construction
├── centrality.py       # PageRank and cycle detection
├── resolution.py       # Import resolution
├── optimizer.py        # Token budget optimizer
├── focus.py            # Ego-centric context generation
├── semantic_anchor.py  # Content-addressable chunk IDs
├── staleness.py        # Manifest freshness detection
├── tree.py             # Directory tree builder
├── visualize.py        # Graph export (Mermaid, DOT, JSON)
├── errors.py           # Error handling
├── chunker.py          # Code chunking
├── cache.py            # Incremental parse caching
├── callgraph.py        # Function-level call graph analysis
├── coupling.py         # Coupling metrics (Ca/Ce/I/A/D)
├── architecture.py     # Architecture layer detection
├── orchestrator.py     # High-level analysis coordination
├── primitives/         # Fast data primitives
│   ├── overview.py     # Project metadata extraction
│   ├── tree.py         # Directory structure
│   ├── scripts.py      # Script extraction
│   ├── entries.py      # Entry point detection
│   ├── file_info.py    # Single file analysis
│   ├── deps.py         # Dependency lookup
│   └── formatters.py   # Output formatters (JSON, human, markdown)
└── languages/          # Language adapters
    ├── base.py         # Adapter interface
    ├── python.py       # Python adapter
    ├── typescript.py   # TypeScript/JavaScript adapter
    └── go.py           # Go adapter
```

## Roadmap

### Implemented Features

- **Fast Primitives**: Sub-200ms queries for project metadata, tree, scripts, entries, file info, and dependencies
- **Bridge File Detection**: Betweenness centrality identifies critical connector files
- **Auto-Generated Architecture Diagrams**: Mermaid diagrams from dependency graph
- **Focus Mode**: Ego-centric context centered on a specific file
- **Token Budget Optimizer**: Greedy and knapsack algorithms for budget-constrained selection
- **Semantic Anchors**: Content-addressable chunk IDs that survive refactoring
- **Context Staleness Detection**: Hash-based verification of manifest freshness
- **Coupling Metrics**: Ca/Ce/I/A/D metrics for architectural health analysis
- **Architecture Layer Detection**: Automatic classification into presentation/application/domain/infrastructure layers
- **Call Graph Analysis**: Function-level call tracking and hot path detection
- **Incremental Caching**: Hash-based parse cache for fast subsequent scans

### Planned Features

- **MCP Server Mode**: Run as a Model Context Protocol server for IDE integration

## Focus Mode

Focus Mode generates ego-centric context centered on a specific file. Instead of analyzing the entire codebase, it radiates outward from a focal file to find the most relevant context.

### How It Works

1. **Bidirectional BFS**: Explores both dependencies (what the file imports) and dependents (what imports the file)
2. **Distance-Weighted Scoring**: Files are scored by `centrality × (decay ^ distance)`
3. **Categorization**: Automatically identifies related tests, type definitions, and shared modules

### Usage

```bash
# Generate focused context for a file
better-context focus src/auth/jwt.py

# Limit exploration depth (default: 3)
better-context focus src/auth/jwt.py --depth 2

# Adjust score decay (default: 0.8)
better-context focus src/auth/jwt.py --decay 0.5

# Output as JSON for programmatic use
better-context focus src/auth/jwt.py --json

# Save to file
better-context focus src/auth/jwt.py -o focus-context.md
```

### Output

Focus Mode generates a focused AGENTS.md containing:

- **Summary**: Neighborhood size, depth explored, dependency counts
- **Direct Dependencies**: Files the focal file imports (ranked by relevance)
- **Direct Dependents**: Files that import the focal file
- **Extended Neighborhood**: Files 2+ hops away
- **Related Tests**: Test files in the neighborhood
- **Shared Types**: Type definition files
- **Suggested Reading Order**: Optimal sequence for understanding the code

## Token Budget Optimizer

The Token Budget Optimizer selects the mathematically optimal subset of code chunks that fit within a token budget, maximizing value using constrained optimization.

### How It Works

1. **PageRank Weighting**: Chunks are scored by their file's PageRank centrality
2. **Relevance Scoring**: Optional keyword/task matching boosts relevant chunks
3. **Diversity Penalty**: Penalizes selecting similar chunks to encourage variety
4. **Greedy/Knapsack Selection**: Efficient algorithms for budget-constrained selection

### Algorithm

```
Maximize: Σ(PageRank × relevance × diversity) / tokens_used
Subject to: tokens_used ≤ budget
```

### Usage

```bash
# Select optimal context within 8000 token budget
better-context optimize --budget 8000

# Boost chunks matching specific keywords
better-context optimize -b 4000 -k auth user session

# Optimize for a specific task
better-context optimize -b 8000 --task "implement user authentication"

# Use knapsack algorithm for true optimality
better-context optimize -b 4000 -a knapsack

# Output as JSON
better-context optimize -b 8000 --json
```

### Options

| Option | Description |
|--------|-------------|
| `--budget, -b` | Token budget (default: 8000) |
| `--keywords, -k` | Keywords to boost relevance |
| `--task, -t` | Task description for relevance scoring |
| `--algorithm, -a` | `greedy` (default) or `knapsack` |
| `--diversity` | Diversity penalty factor 0-1 (default: 0.3) |
| `--json` | Output as JSON |
| `--output, -o` | Output file path |

### Output

The optimizer outputs a ranked list of chunks with:
- File path and chunk name
- Token count and efficiency score
- PageRank and relevance scores
- Budget utilization summary

## Semantic Anchors

Semantic Anchors provide content-addressable chunk IDs that survive refactoring. Instead of `file:line`-based references that break when code moves, semantic anchors are derived from `hash(normalized_AST)`.

### How It Works

1. **AST Normalization**: Code is normalized by removing comments, whitespace, and string contents
2. **Content Hashing**: A SHA-256 hash of the normalized code produces a stable 16-character ID
3. **Anchor Mapping**: The system tracks anchor → location mappings
4. **Move Detection**: When code moves, the same anchor maps to the new location

### Benefits

- **Durable Agent Memory**: References to code remain valid across refactoring
- **Stable Context Links**: Links between context and code survive file reorganization
- **Change Detection**: Different anchors indicate semantic changes (not just whitespace)

### Example

```python
# Same anchor regardless of location
def hello(name: str) -> str:
    return f"Hello, {name}!"

# semantic_anchor: "a3f2e8c9b1d4a5f7"
# This stays the same even if the function moves to a different file
```

### API

```python
from better_context import compute_semantic_anchor, AnchorMapping

# Compute anchor for a chunk
anchor = compute_semantic_anchor(
    source=source_code,
    start_line=10,
    end_line=20,
    language="python",
    name="hello",
    chunk_type="function",
)

# Track anchor locations
mapping = AnchorMapping()
update_anchor_mapping(mapping, anchor, "src/utils.py", 10, "src/utils.py:10:function:hello")

# Resolve anchor to current location
path, line = resolve_anchor(mapping, anchor)
```

## Coupling Metrics

Better Context calculates Robert C. Martin's package coupling metrics to evaluate module stability and architectural health:

| Metric | Name | Description |
|--------|------|-------------|
| **Ca** | Afferent Coupling | Number of modules that depend ON this module |
| **Ce** | Efferent Coupling | Number of modules this module depends ON |
| **I** | Instability | Ce / (Ca + Ce) — 0 = stable, 1 = unstable |
| **A** | Abstractness | Abstract definitions / total definitions |
| **D** | Distance | \|A + I - 1\| — 0 = ideal (on the main sequence) |

### Zone Analysis

Modules are classified into architectural zones:

- **Main Sequence** (D ≈ 0): Healthy balance of stability and abstractness
- **Zone of Pain** (I ≈ 0, A ≈ 0): Stable but concrete — hard to extend
- **Zone of Uselessness** (I ≈ 1, A ≈ 1): Unstable and abstract — likely unused

### API

```python
from better_context import calculate_all_coupling_metrics, generate_zone_report

# Calculate metrics for all files
metrics = calculate_all_coupling_metrics(graph, file_entries)

# Generate zone classification report
report = generate_zone_report(metrics)
print(f"Files on main sequence: {len(report.on_main_sequence)}")
print(f"Files in zone of pain: {len(report.zone_of_pain)}")
```

## Architecture Layer Detection

Better Context automatically classifies files into architectural layers using directory naming patterns, import direction analysis, and export type analysis:

| Layer | Description | Examples |
|-------|-------------|----------|
| **Presentation** | UI components, views, pages | `components/`, `pages/`, `views/` |
| **Application** | Use cases, handlers, controllers | `handlers/`, `controllers/`, `usecases/` |
| **Domain** | Business logic, models, entities | `models/`, `domain/`, `entities/` |
| **Infrastructure** | Database, external APIs, adapters | `db/`, `adapters/`, `repositories/` |
| **Shared** | Cross-cutting utilities, types | `utils/`, `types/`, `helpers/` |

### Layer Violation Detection

The tool detects when lower layers import from higher layers (e.g., infrastructure importing from presentation), which violates clean architecture principles.

### API

```python
from better_context import analyze_architecture

# Analyze architecture and detect violations
report = analyze_architecture(graph, file_entries)

for violation in report.violations:
    print(f"{violation.source_path} ({violation.source_layer}) "
          f"imports {violation.target_path} ({violation.target_layer})")
```

## Call Graph Analysis

Better Context builds function-level call graphs showing which functions call which other functions, enabling deeper code flow understanding beyond file-level imports.

### Features

- **Call Site Extraction**: Identifies function calls within function bodies
- **Symbol Resolution**: Resolves call targets to specific chunk IDs
- **Forward/Reverse Indices**: Quick lookup of callers and callees
- **Hot Path Detection**: Identifies frequently-called functions
- **Impact Analysis**: Determines what's affected by changing a function

### API

```python
from better_context import build_call_graph, get_callers, get_callees

# Build call graph from manifest
call_graph = build_call_graph(manifest)

# Find all functions that call a specific function
callers = get_callers(call_graph, "src/auth.py:validate_token")

# Find all functions called by a specific function
callees = get_callees(call_graph, "src/api/routes.py:handle_request")
```

## Troubleshooting

### "Manifest not found"

Run `better-context scan` first to index the codebase. The `stats`, `graph`, `focus`, `optimize`, `verify`, and `deps` commands require an existing manifest.

### "No files found"

Check your `.ctxignore` patterns and ensure the directory contains supported file types (Python, TypeScript, JavaScript, Go).

### "Circular dependency detected"

This is informational — circular dependencies are reported but don't prevent analysis. Consider refactoring to break the cycle at the suggested point.

### "File too large"

Increase `max_file_size_kb` in `.ctx.json` or add the file to `.ctxignore`.

## Contributing

Contributions are welcome! Please see [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

1. Fork the repository
2. Create a feature branch
3. Run tests (`pytest`)
4. Submit a pull request

## License

MIT License - see [LICENSE](LICENSE) for details.
