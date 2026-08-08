# Better Context Unity

Local, dependency-free Unity/C# codebase maps for coding agents.

This is a Unity-focused fork of
[`hoangnb24/better-agents-md`](https://github.com/hoangnb24/better-agents-md).
It keeps the upstream scanner, manifest, graph, focus, and token-budget tools,
then adds the pieces a Unity coding agent needs:

- Unity project detection without reading generated `.csproj` files.
- C# type, method, namespace, `using`, and Unity base-type extraction.
- Approximate C# file relationships from unique referenced type names.
- Unity-generated directory ignores.
- Safe hierarchical `AGENTS.md` maps under project-owned Unity folders.
- Stable `/` paths on Windows.

## Quick start

From this checkout:

```powershell
uv run better-context-unity --root D:\Path\To\UnityProject agents --dry-run
uv run better-context-unity --root D:\Path\To\UnityProject agents
```

Maps stay structural by default. When an AI agent decides that a durable
description would improve navigation, it can add optional summaries in the
same call:

```powershell
uv run better-context-unity --root D:\Path\To\UnityProject agents `
  --summary 'Assets/Scripts=Runtime gameplay scripts.' `
  --summary 'Assets/Scripts/GameManager.cs=Coordinates game state and scene transitions.'
```

`--summary PATH=TEXT` is repeatable and accepts a project-relative file or
folder. Summaries are stored in `.ctx-summaries.json`, so later `agents` runs
keep them without requiring the AI to repeat the text. To correct or remove
one:

```powershell
uv run better-context-unity --root D:\Path\To\UnityProject agents `
  --remove-summary 'Assets/Scripts/GameManager.cs'
```

The CLI does not call an LLM or invent summaries. It only validates and stores
text explicitly supplied by the caller. Summary text is limited to 240
characters to keep maps compact. `--dry-run` never changes either maps or the
summary store.

Install the custom CLI locally while developing the fork:

```powershell
uv tool install --editable .
better-context-unity --version
```

The `agents` command scans the project, writes
`.better-context/manifest.json`, and creates or refreshes project maps:

```text
UnityProject/
├── AGENTS.md
├── Assets/
│   ├── AGENTS.md
│   └── Scripts/
│       └── AGENTS.md
├── Packages/
│   └── AGENTS.md
└── ProjectSettings/
    └── AGENTS.md
```

## Safe AGENTS.md ownership

Generated content is enclosed by explicit markers:

```markdown
<!-- better-context-unity:begin -->
...managed map...
<!-- better-context-unity:end -->
```

Re-running the command replaces only that block. Handwritten instructions
outside the markers are preserved. `clean` also removes only the managed block;
it does not delete a mixed handwritten file.

For Unity projects, maps are limited to the repository root and the authored
`Assets`, `Packages`, and `ProjectSettings` trees. Generated or tool-owned
folders such as `Library`, `Temp`, `Logs`, `Obj`, `.codex`, `.agents`, `.serena`,
`.beads`, `.codegraph`, and `.cocoindex_code` are ignored.

## Agent routing

Better Context Unity is a persistent project-map and local orientation tool.
It does not replace stronger retrieval/editing tools:

```text
Root-to-folder navigation and AGENTS.md refresh -> Better Context Unity
Known symbol, call flow, dependency, blast radius -> CodeGraph
Unknown name or fuzzy business concept              -> CocoIndex
Exact semantic edit after target discovery          -> Serena
```

The inferred C# graph is intentionally approximate. A relationship is added
when a C# file references a uniquely declared project type. Use CodeGraph or
direct source verification before making behavior or refactor claims.

## Commands

| Command | Purpose |
|---|---|
| `agents` | Scan and safely refresh maps; optionally add/remove persisted summaries |
| `scan` | Create `.better-context/manifest.json` without changing maps |
| `overview` | Detect Unity/C# project metadata |
| `tree` | Show a compact directory summary |
| `file <path>` | Extract types, methods, imports, and exports |
| `deps <path>` | Show inferred file dependencies and dependents |
| `stats` | Show manifest and PageRank statistics |
| `focus <path>` | Build context around a known file |
| `graph` | Export Mermaid, DOT, or JSON graph data |
| `optimize` | Select code chunks within a token budget |
| `verify` | Check whether the saved manifest/map source state is stale |
| `clean` | Remove cache/output and only this tool's managed map blocks |

All commands accept `--root PATH` before the subcommand. Structured commands
default to JSON where supported.

## Configuration

Optional `.ctx.json`:

```json
{
  "max_file_size_kb": 500,
  "chunk_max_lines": 150,
  "chunk_min_lines": 10,
  "output_dir": ".better-context",
  "manifest_file": "manifest.json",
  "generate_agents_md": true,
  "pagerank_damping": 0.85,
  "pagerank_iterations": 20
}
```

Optional `.ctxignore` uses gitignore-like patterns and extends the built-in
Unity ignores:

```gitignore
Assets/Plugins/
Assets/ThirdParty/
Assets/External/
Assets/Generated/
```

Use these exclusions only when those folders are genuinely imported or
generated rather than project-owned source.

## Development

```powershell
uv run --extra dev pytest
uv run --extra dev ruff check src tests
uv run --extra dev mypy src
```

The parser is regex-based by design: fast, local, and dependency-free. Add an
AST parser only when measured C# accuracy requires it.

## Upstream and license

The upstream repository is retained as the `upstream` Git remote. Add your own
fork as `origin` before pushing. The project uses the MIT License; see
[`LICENSE`](LICENSE).
