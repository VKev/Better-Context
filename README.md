# Better Context Unity

Local Unity/C# codebase intelligence and hierarchical maps for coding agents.

This is a Unity-focused fork of
[`hoangnb24/better-agents-md`](https://github.com/hoangnb24/better-agents-md).
It keeps the upstream scanner, manifest, graph, focus, and token-budget tools,
then adds the pieces a Unity coding agent needs:

- Batch Roslyn analysis for C# types, public methods, properties, events,
  constructors, extension methods, and operator overloads.
- Symbol-resolved C# dependencies and function calls. Comments, strings,
  namespace names, `.meta` files, shader includes, and same-name collisions do
  not create C# file edges.
- Unity YAML runtime intelligence for scene/prefab GameObject hierarchies,
  built-in and script components, ScriptableObject instances, persistent
  UnityEvents, prefab instances, Animator controllers, animation clips,
  materials, and serialized mesh assets.
- A companion Unity Editor package for authoritative TextureImporter, Sprite
  subasset/local-ID, Sprite Atlas, audio/video/font/terrain/static asset, and
  `MonoScript.GetClass` component identity facts. It communicates only through
  atomic files in `.better-context/`; no port or MCP server is opened.
- Exact scene, prefab, ScriptableObject, controller, material, animation, and
  script relationships resolved through structured object references and Unity
  GUIDs. Roslyn confirms all C# types and callable UnityEvent targets.
- Unity-generated directory ignores.
- Safe hierarchical `AGENTS.md` maps with project facts, PageRank, public API,
  named dependencies/dependents, call flows, coupling metrics, inferred layers,
  cycles, layer violations, edit ownership, and validation rules.
- Stable `/` paths on Windows.

Roslyn requires a .NET 8 or newer SDK. The first C# scan builds a bundled helper
and restores `Microsoft.CodeAnalysis.CSharp`; later scans reuse a content-hashed
user cache. If Roslyn is unavailable, Better Context still inventories C#
symbols with its fallback adapter but deliberately omits C# dependency/call
edges instead of guessing from names.

## Quick start

From this checkout:

```powershell
uv run better-context-unity --root D:\Path\To\UnityProject editor install --revision v1.6.0
uv run better-context-unity --root D:\Path\To\UnityProject editor sync --mode auto
uv run better-context-unity --root D:\Path\To\UnityProject agents --dry-run
uv run better-context-unity --root D:\Path\To\UnityProject agents
```

The UPM dependency uses Unity's documented
[Git subfolder syntax](https://docs.unity3d.com/2022.3/Documentation/Manual/upm-git.html)
and should be pinned to a release tag or exact commit. `agents` reuses a fresh Editor snapshot and
refreshes a stale one automatically. It asks the already-open Editor first; if
the project is closed, it runs the exact version declared by
`ProjectSettings/ProjectVersion.txt` in batch mode. When the bridge or matching
Editor is unavailable, analysis continues offline with an explicit coverage
warning unless `unity_editor_required` is enabled. Stale Editor data is never
merged into the manifest.

Roslyn-derived responsibilities are limited to facts verified in code: declared
types, Unity base classes, documented summaries, and exposed members. When an AI
agent has verified a more specific business responsibility, it can persist that
description in the same call:

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

The CLI does not call an LLM or invent business behavior. It only validates and
stores text explicitly supplied by the caller. Summary text is limited to 240
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
Persistent symbol/dependency/call inventory             -> Better Context Unity
Deep dynamic dispatch or exact edit-time call path       -> CodeGraph
Unknown name or fuzzy business concept              -> CocoIndex
Exact semantic edit after target discovery          -> Serena
```

Each C# edge is backed by a Roslyn-resolved source symbol and records its
reference kind, symbol name, and source line in the manifest. Unity serialized
edges are backed by GUID identity. Architecture layers remain explicitly
heuristic and should not be treated as authored design intent.

## Generated AGENTS.md intelligence

The root map contains:

- Unity/product version, build scenes, packages, asmdefs, and ownership counts.
- Key project-owned files ranked by PageRank.
- File/symbol/dependency/call metrics and project-owned circular components.
- Inferred architecture layers with detailed source-to-target violations.
- Resolved cross-file call evidence for feature flow.
- Test/build/change rules and vendor/generated edit boundaries.
- `focus` and token-budget `optimize` commands for deeper task context.

Folder maps add verified structural responsibility, key public API with semantic
anchors, named dependencies and dependents, Ca/Ce/I/A/D coupling metrics,
function calls, and exact Unity serialized references. `.meta` sidecars are
hidden from file tables and can never be C# dependency targets. Parsed FBX,
animation, material, and mesh facts may be shown in the nearest bounded art map.
Pure art and other low-signal assets receive path-only navigation without an
invented code-like responsibility. Sprite sheets, platform overrides,
non-default importers, or assets with verified runtime references may receive a
bounded detail row. Art maps stop
at `Assets/<group>/<child>`; deeper paths are folded into the nearest map and
each table is capped. Vendor/generated trees still stop at a clearly labeled
boundary. Regeneration safely removes only stale managed blocks below collapsed
boundaries.

Unity runtime asset summaries stay deliberately compact in `AGENTS.md`. The
full object/component topology remains in `.better-context/manifest.json` and
can be queried without regenerating context:

```powershell
better-context-unity --root D:\Path\To\UnityProject unity list --kind prefab --format human
better-context-unity --root D:\Path\To\UnityProject unity show Assets/UI/Shop.prefab --depth 3
better-context-unity --root D:\Path\To\UnityProject unity show Assets/Characters/Hero.fbx --depth 2
better-context-unity --root D:\Path\To\UnityProject unity show Assets/UI/BuffIcon.png
better-context-unity --root D:\Path\To\UnityProject unity bindings --type ShopView --method Buy
better-context-unity --root D:\Path\To\UnityProject unity components --asset Assets/UI/Shop.prefab --type UnityEngine.UI.Image
```

`unity list` defaults to 50 assets. `unity show` defaults to hierarchy depth 2;
use `--depth -1` for the full hierarchy. Binding filters use exact,
case-insensitive asset/type/method matching. These read-only commands require a
fresh manifest and print an `agents` refresh hint when it is missing or stale.
`unity show` retains full importer, platform override, hidden subasset, Sprite
local ID/rect/pivot/border/PPU, and selected component facts on demand; pixel,
thumbnail, and base64 image data are never stored.

### Unity Editor asset and component intelligence

The companion package exports Unity-authoritative facts with
[`AssetDatabase.LoadAllAssetsAtPath`](https://docs.unity3d.com/2022.3/Documentation/ScriptReference/AssetDatabase.LoadAllAssetsAtPath.html),
[`TextureImporter`](https://docs.unity3d.com/2022.3/Documentation/ScriptReference/TextureImporter.html), other available
importers, and `MonoScript.GetClass`. Scene and prefab hierarchy still comes
from the structured YAML parser: the bridge does not open, modify, or save a
scene. Built-in and package UI components such as `Image`, `Button`, layout
groups, TMP, physics, rendering, audio, navigation, particles, and directors
receive bounded field/reference summaries. Unknown components receive at most
12 scalar/vector/color/reference fields and no inferred responsibility.

Direct `AssetDatabase.GetDependencies(path, false)` results may become graph
edges. Self edges, `.meta`, cache, and generated paths are rejected; Sprite
references remain file-level edges whose evidence records the exact Sprite
name, local ID, and Sprite ID.

### FBX model intelligence

FBX support is zero-dependency and covers binary FBX 7.x plus structural ASCII
FBX. The analyzer reports scene-node hierarchy, mesh control-point and polygon
counts, material/texture names, skeleton bones, and animation stacks/layers/
curve counts. The adjacent Unity `ModelImporter` `.fbx.meta` file supplies the
Unity-authoritative rig/avatar mode, humanoid mapping, imported skeleton,
animation clip splits/events, mesh/material settings, and copied-avatar GUID.
Those GUIDs become verified dependency edges; free-text names never do.

The structural parser does not evaluate animated transforms, decode curve
samples for playback, bake avatars, or replace Unity import validation. Use the
Unity Editor when those runtime/import results are required. The extracted
shape follows Unity's documented [`ModelImporter`](https://docs.unity3d.com/ScriptReference/ModelImporter.html)
surface and Autodesk's documented [FBX scene graph](https://help.autodesk.com/cloudhelp/2018/ENU/FBX-Developer-Help/nodes_and_scene_graph/fbx_scenes.html).

## Commands

| Command | Purpose |
|---|---|
| `agents` | Scan and safely refresh maps; optionally add/remove persisted summaries |
| `scan` | Create `.better-context/manifest.json` without changing maps |
| `overview` | Detect Unity/C# project metadata |
| `tree` | Show a compact directory summary |
| `file <path>` | Extract types, methods, imports, and exports |
| `deps <path>` | Show named dependencies/dependents with resolved symbols and lines |
| `editor install` | Pin the companion UPM package by Git revision |
| `editor status` | Report package, exact Unity executable, and snapshot freshness |
| `editor sync` | Refresh Editor facts through an open Editor or exact-version batch process |
| `unity list` | List runtime, model, texture, Sprite Atlas, shader, audio, video, and other static Unity assets |
| `unity show <path>` | Show full GameObject/component/model/runtime data for one Unity asset |
| `unity bindings` | Query persistent UnityEvent bindings by asset, target type, or method |
| `unity components` | Query exact component types, selected fields, and named references |
| `stats` | Show manifest and PageRank statistics |
| `focus <path>` | Build context around a known file |
| `graph [--kind dependency\|call]` | Export dependency or function-call graph as Mermaid, DOT, or JSON |
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
  "pagerank_iterations": 20,
  "unity_asset_scope": "project-owned",
  "unity_agents_asset_limit": 12,
  "unity_agents_object_limit": 8,
  "unity_editor_mode": "auto",
  "unity_editor_required": false,
  "unity_editor_timeout_seconds": 300,
  "unity_editor_path": null
}
```

`unity_asset_scope` accepts `project-owned` (default) or `all`. The two positive
limits cap Unity asset and object previews in generated `AGENTS.md`; they do not
discard full manifest data. `.ctxignore` still takes precedence over the scope.
`unity_editor_mode` accepts `auto`, `open`, `batch`, or `offline`. A configured
`unity_editor_path` and `UNITY_EDITOR_PATH` are accepted only when they match the
project's exact Unity version; otherwise Unity Hub's matching install is used.

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
dotnet build src/better_context/roslyn_helper/BetterContext.Roslyn.csproj -c Release
uv run --extra dev pytest
uv run --extra dev ruff check src tests
uv run --extra dev mypy src
```

## Upstream and license

The upstream repository is retained as the `upstream` Git remote. Add your own
fork as `origin` before pushing. The project uses the MIT License; see
[`LICENSE`](LICENSE).

The UnityEvent, Animator, and Unity asset back-reference capabilities in
[`pirua-game/ai_game_base_analysis_cli_mcp_tool`](https://github.com/pirua-game/ai_game_base_analysis_cli_mcp_tool)
were used as prior-art capability references. Better Context Unity's parser and
schema are an independent standard-library implementation: `gdep` is not a
runtime dependency, no MCP server is registered, and no `.gdep` directory or
second `AGENTS.md` owner is created.
