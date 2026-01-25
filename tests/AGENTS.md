# tests

> Auto-generated context for `tests`

## 📋 Purpose

Test files

## 📂 Contents

- `AGENTS.md` - tests
- `__init__.py` - barrel export - tests
- `test_architecture.py` - 52 exports - tests
- `test_betweenness.py` - 24 exports - tests
- `test_cache.py` - 34 exports - tests
- `test_callgraph.py` - 45 exports - tests
- `test_cli.py` - 5 exports - tests
- `test_config.py` - 4 exports - tests - configuration
- `test_coupling.py` - 39 exports - tests
- `test_errors.py` - 33 exports - tests
- `test_focus.py` - 15 exports - tests
- `test_go_adapter.py` - 15 exports - tests
- `test_ignore.py` - 5 exports - tests
- `test_languages.py` - 37 exports - tests
- `test_manifest.py` - 24 exports - tests
- `test_optimizer.py` - 49 exports - tests
- `test_python_adapter.py` - 2 exports - tests
- `test_scanner.py` - 3 exports - tests
- `test_semantic_anchor.py` - 52 exports - tests
- `test_staleness.py` - 37 exports - tests
- `test_template.py` - 38 exports - tests
- `test_tree.py` - 7 exports - tests
- `test_visualize_architecture.py` - 26 exports - tests




## 🔑 Key Exports

- `MockExport` (class) - 
- `MockImport` (class) - 
- `MockFileEntry` (class) - 
- `MockGraph` (class) - 
- `get_dependencies` (function) - 
- `get_dependents` (function) - 
- `TestLayerOrder` (class) - 
- `test_layer_order_correct` (function) - 
- `test_layer_index_matches_order` (function) - 
- `TestDetectLayerFromPath` (class) - 
- `test_components_is_presentation` (function) - 
- `test_pages_is_presentation` (function) - 
- `test_views_is_presentation` (function) - 
- `test_controllers_is_application` (function) - 
- `test_handlers_is_application` (function) - 
- `test_api_is_application` (function) - 
- `test_models_is_domain` (function) - 
- `test_entities_is_domain` (function) - 
- `test_services_is_domain` (function) - 
- `test_db_is_infrastructure` (function) - 


## 📥 Dependencies

### Internal
- `src.better_context.architecture` - (
- `better_context.graph` - DependencyGraph, build_graph_from_edges
- `better_context.centrality` - (
- `src.better_context.cache` - (
- `src.better_context.callgraph` - (
- `better_context.cli` - create_parser, main
- `better_context.config` - Config, load_config, merge_configs, validate_config
- `src.better_context.coupling` - (
- `better_context.errors` - (
- `better_context.graph` - build_graph_from_edges, DependencyGraph
- `better_context.focus` - (
- `better_context.languages.go` - GoAdapter
- `_` - *
- `better_context.ignore` - (
- `better_context.manifest` - (
- `better_context.optimizer` - (
- `better_context.manifest` - (
- `better_context.languages.python` - PythonAdapter
- `better_context.scanner` - (
- `better_context.semantic_anchor` - (


### External
- `pytest` - *
- `dataclasses` - dataclass, field
- `typing` - List, Any, Set
- `__future__` - annotations
- `sys` - *
- `pathlib` - Path
- `pytest` - *
- `pytest` - *
- `tempfile` - *
- `time` - *
- `pathlib` - Path
- `json` - *
- `pytest` - *
- `dataclasses` - dataclass, field
- `typing` - List, Dict, Any
- `pathlib` - Path
- `tempfile` - *
- `os` - *
- `pathlib` - Path
- `pytest` - *


---
*[← Back to parent](../AGENTS.md)*
