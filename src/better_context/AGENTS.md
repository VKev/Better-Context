# better_context

> Auto-generated context for `src/better_context`

## 📋 Purpose

src/better_context module

## 📂 Contents

- `architecture.py` - 13 exports - 1 dependents
- `cache.py` - 9 exports - 1 dependents
- `callgraph.py` - 16 exports - 1 dependents
- `coupling.py` - 13 exports - 1 dependents
- `__init__.py` - barrel export
- `centrality.py` - 14 exports
- `chunker.py` - 3 exports
- `cli.py` - 13 exports
- `config.py` - 4 exports - configuration
- `errors.py` - 20 exports
- `generator.py` - 5 exports
- `graph.py` - 30 exports
- `ignore.py` - 5 exports
- `manifest.py` - 17 exports
- `orchestrator.py` - 5 exports
- `resolution.py` - 15 exports
- `scanner.py` - 9 exports
- `template.py` - 5 exports
- `tree.py` - 9 exports
- `visualize.py` - 14 exports



## 📁 Subdirectories

- [`languages/`](./languages/AGENTS.md) - Language adapters



## 🔑 Key Exports

- `LayerClassification` (class) - 
- `LayerViolation` (class) - 
- `ArchitectureReport` (class) - 
- `detect_layer_from_path` (function) - 
- `detect_layer_from_exports` (function) - 
- `detect_layer_from_imports` (function) - 
- `classify_file_layer` (function) - 
- `classify_all_files` (function) - 
- `get_layer_map` (function) - 
- `detect_layer_violations` (function) - 
- `analyze_architecture` (function) - 
- `format_layer_summary` (function) - 
- `format_layer_violations` (function) - 
- `CacheEntry` (class) - 
- `CacheStats` (class) - 
- `Cache` (class) - 
- `IncrementalCache` (class) - 
- `get_default_cache_dir` (function) - 
- `create_cache` (function) - 
- `scan_with_cache` (function) - 


## 📥 Dependencies

### Internal
- `better_context.config` - Config, load_config, validate_config
- `better_context.manifest` - (
- `better_context.errors` - (
- `better_context.coupling` - (
- `better_context.architecture` - (
- `better_context.callgraph` - (
- `.graph` - DependencyGraph
- `.manifest` - FileEntry
- `.manifest` - FileEntry
- `re` - *
- `.manifest` - FileEntry, Manifest, ChunkEntry
- `.graph` - DependencyGraph
- `re` - *
- `.languages.base` - (
- `.config` - load_config
- `.manifest` - load_manifest, Manifest
- `.orchestrator` - Orchestrator, generate_context
- `.graph` - build_graph_from_edges
- `.graph` - DependencyGraph
- `.manifest` - FileEntry


### External
- `__future__` - annotations
- `dataclasses` - dataclass, field
- `typing` - TYPE_CHECKING, List, Dict, Optional, Set
- `__future__` - annotations
- `hashlib` - *
- `json` - *
- `time` - *
- `dataclasses` - dataclass, field, asdict
- `pathlib` - Path
- `typing` - Dict, Optional, Any, List, Tuple, TYPE_CHECKING
- `fnmatch` - *
- `__future__` - annotations
- `collections` - defaultdict
- `dataclasses` - dataclass, field
- `pathlib` - Path
- `typing` - TYPE_CHECKING, List, Dict, Optional, Tuple, Set
- `__future__` - annotations
- `dataclasses` - dataclass
- `typing` - TYPE_CHECKING
- `collections` - deque


---
*[← Back to parent](../AGENTS.md)*
