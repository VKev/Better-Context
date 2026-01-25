# Better Context

> AI Agent Codebase Intelligence CLI - Generate AGENTS.md hierarchies

[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

**Better Context** transforms unstructured codebases into structured, AI-consumable context using graph theory and fractal summarization. It generates hierarchical AGENTS.md files that AI agents can progressively consume without overwhelming their context windows.

## Quick Start

```bash
# Install
pip install better-context

# Analyze a project
better-context all ./my-project
```

This scans your codebase, builds a dependency graph, calculates file importance using PageRank, and generates AGENTS.md files at every level of your project hierarchy.

## Why Better Context?

Traditional approaches to giving AI agents codebase context fall short:

| Approach | Problem |
|----------|---------|
| Dump entire files | Overwhelms context windows |
| Grep-based discovery | Misses relationships |
| Flat documentation | Lacks navigation structure |

**Better Context** solves this with:

- **Mathematical file ranking** via PageRank centrality
- **Dependency graph analysis** with cycle detection
- **Fractal summarization** with hierarchical AGENTS.md files
- **Progressive disclosure** - agents load only what they need
- **Zero-dependency core** - works anywhere Python runs

## What It Does

1. **Scans** your codebase, detecting languages and filtering binary files
2. **Parses** functions, classes, imports, and exports using dual-mode parsing (regex fallback + optional tree-sitter AST)
3. **Builds** a dependency graph showing what imports what
4. **Calculates** PageRank centrality to rank files by structural importance
5. **Detects** circular dependencies using Tarjan's SCC algorithm
6. **Generates** hierarchical AGENTS.md files with progressive disclosure

## Installation

### From PyPI

```bash
pip install better-context
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

## Usage

### Commands

| Command | Description |
|---------|-------------|
| `better-context all [path]` | Scan and generate AGENTS.md (common workflow) |
| `better-context scan [path]` | Scan codebase and generate manifest |
| `better-context agents` | Generate AGENTS.md files from manifest |
| `better-context stats` | Show codebase statistics |
| `better-context graph` | Export dependency graph |
| `better-context focus <file>` | Generate context centered on a specific file |
| `better-context optimize` | Select optimal context within token budget |
| `better-context verify` | Check if generated context is stale |
| `better-context clean` | Remove generated files |

### Examples

```bash
# Analyze current directory
better-context all .

# Analyze specific project with verbose output
better-context all ./my-project -v

# Generate only the manifest (for debugging)
better-context scan --out manifest.json

# Export dependency graph as Mermaid
better-context graph -f mermaid > deps.md

# Export as Graphviz DOT
better-context graph -f dot > deps.dot

# Export as JSON (for custom visualization)
better-context graph -f json > deps.json

# Show statistics as JSON
better-context stats --json

# Generate focused context for a specific file
better-context focus src/auth/jwt.py --depth 3

# Focus mode with JSON output
better-context focus src/api/handler.py --json

# Select optimal context within 8000 token budget
better-context optimize --budget 8000

# Optimize with keywords to boost relevance
better-context optimize -b 4000 -k auth user session

# Optimize for a specific task
better-context optimize -b 8000 --task "implement user authentication"

# Clean only cache files, keep AGENTS.md
better-context clean --cache-only
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
├── generator.py        # AGENTS.md generation
├── optimizer.py        # Token budget optimizer
├── semantic_anchor.py  # Content-addressable chunk IDs
├── template.py         # Template engine (zero-dep)
├── tree.py             # Directory tree builder
├── visualize.py        # Graph export (Mermaid, DOT, JSON)
├── errors.py           # Error handling
├── chunker.py          # Code chunking
└── languages/          # Language adapters
    ├── base.py         # Adapter interface
    ├── python.py       # Python adapter
    ├── typescript.py   # TypeScript/JS adapter
    └── go.py           # Go adapter (WIP)
```

## Roadmap

### Post-MVP Features

- **Bridge File Detection**: Use betweenness centrality to find critical connector files ✅
- **Auto-Generated Architecture Diagrams**: Mermaid diagrams from dependency graph ✅
- **Focus Mode**: Generate context centered on a specific file ✅
- **Token Budget Optimizer**: Select optimal context within token limits ✅
- **MCP Server Mode**: Run as a Model Context Protocol server
- **Semantic Anchors**: Content-addressable chunk IDs that survive refactoring ✅
- **Context Staleness Detection**: Hash-based verification of generated context ✅

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

## Troubleshooting

### "No files found"

Check your `.ctxignore` patterns and ensure the directory contains supported file types.

### "Circular dependency detected"

This is informational - circular dependencies are reported but don't prevent analysis. Consider refactoring to break the cycle at the suggested point.

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

---

Built with ❤️ for AI agents everywhere.
# better-agents-md
# better-agents-md
