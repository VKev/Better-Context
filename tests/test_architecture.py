"""Tests for architecture layer detection."""

import pytest
from dataclasses import dataclass, field
from typing import List, Any, Set

# Mock types for testing
@dataclass
class MockExport:
    name: str
    type: str
    line: int = 0
    is_default: bool = False


@dataclass
class MockImport:
    module: str
    symbols: List[str] = field(default_factory=list)


@dataclass
class MockFileEntry:
    path: str
    exports: List[MockExport] = field(default_factory=list)
    imports: List[MockImport] = field(default_factory=list)
    chunks: List[Any] = field(default_factory=list)
    language: str = "python"
    size_bytes: int = 0
    hash: str = ""


class MockGraph:
    """Mock dependency graph for testing."""
    
    def __init__(self, edges=None):
        self.edges = edges or {}
        self._reverse = {}
        
        for source, targets in self.edges.items():
            for target in targets:
                if target not in self._reverse:
                    self._reverse[target] = set()
                self._reverse[target].add(source)
    
    def get_dependencies(self, node: str) -> Set[str]:
        return self.edges.get(node, set())
    
    def get_dependents(self, node: str) -> Set[str]:
        return self._reverse.get(node, set())


# Import module under test
from src.better_context.architecture import (
    LAYER_ORDER,
    LAYER_INDEX,
    LAYER_PATTERNS,
    LayerClassification,
    LayerViolation,
    ArchitectureReport,
    detect_layer_from_path,
    detect_layer_from_exports,
    detect_layer_from_imports,
    classify_file_layer,
    classify_all_files,
    get_layer_map,
    detect_layer_violations,
    analyze_architecture,
    format_layer_summary,
    format_layer_violations,
)


class TestLayerOrder:
    """Tests for layer ordering."""
    
    def test_layer_order_correct(self):
        assert LAYER_ORDER == ['infrastructure', 'shared', 'domain', 'application', 'presentation']
    
    def test_layer_index_matches_order(self):
        for i, layer in enumerate(LAYER_ORDER):
            assert LAYER_INDEX[layer] == i


class TestDetectLayerFromPath:
    """Tests for path-based layer detection."""
    
    def test_components_is_presentation(self):
        assert detect_layer_from_path("src/components/Button.tsx") == 'presentation'
    
    def test_pages_is_presentation(self):
        assert detect_layer_from_path("pages/index.tsx") == 'presentation'
    
    def test_views_is_presentation(self):
        assert detect_layer_from_path("app/views/UserView.py") == 'presentation'
    
    def test_controllers_is_application(self):
        assert detect_layer_from_path("src/controllers/UserController.ts") == 'application'
    
    def test_handlers_is_application(self):
        assert detect_layer_from_path("handlers/auth_handler.py") == 'application'
    
    def test_api_is_application(self):
        assert detect_layer_from_path("src/api/users.ts") == 'application'
    
    def test_models_is_domain(self):
        assert detect_layer_from_path("src/models/User.py") == 'domain'
    
    def test_entities_is_domain(self):
        assert detect_layer_from_path("domain/entities/Order.ts") == 'domain'
    
    def test_services_is_domain(self):
        assert detect_layer_from_path("src/services/UserService.ts") == 'domain'
    
    def test_db_is_infrastructure(self):
        assert detect_layer_from_path("src/db/connection.py") == 'infrastructure'
    
    def test_database_is_infrastructure(self):
        assert detect_layer_from_path("infrastructure/database/client.ts") == 'infrastructure'
    
    def test_adapters_is_infrastructure(self):
        assert detect_layer_from_path("src/adapters/redis_adapter.py") == 'infrastructure'
    
    def test_utils_is_shared(self):
        assert detect_layer_from_path("src/utils/helpers.ts") == 'shared'
    
    def test_types_is_shared(self):
        assert detect_layer_from_path("src/types/index.ts") == 'shared'
    
    def test_lib_is_shared(self):
        assert detect_layer_from_path("lib/common.py") == 'shared'
    
    def test_unrecognized_returns_none(self):
        assert detect_layer_from_path("src/foo/bar.py") is None


class TestDetectLayerFromExports:
    """Tests for export-based layer detection."""
    
    def test_mostly_types_is_shared(self):
        file = MockFileEntry(
            path="types.ts",
            exports=[
                MockExport(name="User", type="type"),
                MockExport(name="Order", type="type"),
                MockExport(name="ID", type="type"),
                MockExport(name="parse", type="function"),
            ]
        )
        assert detect_layer_from_exports(file) == 'shared'
    
    def test_mostly_implementations_returns_none(self):
        file = MockFileEntry(
            path="service.ts",
            exports=[
                MockExport(name="UserService", type="class"),
                MockExport(name="createUser", type="function"),
                MockExport(name="User", type="type"),
            ]
        )
        assert detect_layer_from_exports(file) is None
    
    def test_no_exports_returns_none(self):
        file = MockFileEntry(path="main.ts", exports=[])
        assert detect_layer_from_exports(file) is None


class TestDetectLayerFromImports:
    """Tests for import-based layer detection."""
    
    def test_no_imports_returns_shared(self):
        file = MockFileEntry(path="util.py")
        graph = MockGraph()
        assert detect_layer_from_imports(file, graph, {}) == 'shared'
    
    def test_imports_from_domain_returns_application(self):
        file = MockFileEntry(path="handler.py")
        graph = MockGraph(edges={"handler.py": {"model.py"}})
        layers = {"model.py": "domain"}
        
        result = detect_layer_from_imports(file, graph, layers)
        # Should be one layer above domain
        assert LAYER_INDEX[result] >= LAYER_INDEX['domain']
    
    def test_unknown_imports_returns_domain(self):
        file = MockFileEntry(path="unknown.py")
        graph = MockGraph(edges={"unknown.py": {"other.py"}})
        assert detect_layer_from_imports(file, graph, {}) == 'domain'


class TestClassifyFileLayer:
    """Tests for classify_file_layer function."""
    
    def test_path_takes_precedence(self):
        file = MockFileEntry(path="src/components/Button.tsx")
        graph = MockGraph()
        
        classification = classify_file_layer(file, graph, {})
        
        assert classification.layer == 'presentation'
        assert classification.method == 'path'
        assert classification.confidence >= 0.8
    
    def test_exports_secondary(self):
        # Path contains no layer patterns, so exports analysis is used
        file = MockFileEntry(
            path="src/generic/stuff.ts",
            exports=[
                MockExport(name="A", type="type"),
                MockExport(name="B", type="type"),
                MockExport(name="C", type="type"),
            ]
        )
        graph = MockGraph()
        
        classification = classify_file_layer(file, graph, {})
        
        assert classification.layer == 'shared'
        assert classification.method == 'exports'


class TestClassifyAllFiles:
    """Tests for classify_all_files function."""
    
    def test_classifies_all(self):
        files = [
            MockFileEntry(path="src/components/Button.tsx"),
            MockFileEntry(path="src/models/User.py"),
            MockFileEntry(path="src/db/connection.py"),
        ]
        graph = MockGraph()
        
        classifications = classify_all_files(files, graph)
        
        assert len(classifications) == 3
        assert classifications["src/components/Button.tsx"].layer == 'presentation'
        assert classifications["src/models/User.py"].layer == 'domain'
        assert classifications["src/db/connection.py"].layer == 'infrastructure'


class TestGetLayerMap:
    """Tests for get_layer_map function."""
    
    def test_extracts_simple_map(self):
        classifications = {
            "a.py": LayerClassification(path="a.py", layer="domain", confidence=0.9, method="path"),
            "b.py": LayerClassification(path="b.py", layer="shared", confidence=0.7, method="exports"),
        }
        
        layer_map = get_layer_map(classifications)
        
        assert layer_map == {"a.py": "domain", "b.py": "shared"}


class TestDetectLayerViolations:
    """Tests for layer violation detection."""
    
    def test_no_violations_in_valid_imports(self):
        # presentation importing from domain is valid
        files = [MockFileEntry(path="view.py"), MockFileEntry(path="model.py")]
        layers = {"view.py": "presentation", "model.py": "domain"}
        graph = MockGraph(edges={"view.py": {"model.py"}})
        
        violations = detect_layer_violations(files, layers, graph)
        
        assert len(violations) == 0
    
    def test_detects_upward_violation(self):
        # infrastructure importing from presentation is a violation
        files = [MockFileEntry(path="db.py"), MockFileEntry(path="component.py")]
        layers = {"db.py": "infrastructure", "component.py": "presentation"}
        graph = MockGraph(edges={"db.py": {"component.py"}})
        
        violations = detect_layer_violations(files, layers, graph)
        
        assert len(violations) == 1
        assert violations[0].source_layer == "infrastructure"
        assert violations[0].target_layer == "presentation"
    
    def test_domain_importing_application_is_violation(self):
        files = [MockFileEntry(path="model.py"), MockFileEntry(path="handler.py")]
        layers = {"model.py": "domain", "handler.py": "application"}
        graph = MockGraph(edges={"model.py": {"handler.py"}})
        
        violations = detect_layer_violations(files, layers, graph)
        
        assert len(violations) == 1


class TestAnalyzeArchitecture:
    """Tests for analyze_architecture function."""
    
    def test_complete_analysis(self):
        files = [
            MockFileEntry(path="src/components/Button.tsx"),
            MockFileEntry(path="src/models/User.py"),
            MockFileEntry(path="src/utils/helpers.py"),
        ]
        graph = MockGraph()
        
        report = analyze_architecture(files, graph)
        
        assert 'presentation' in report.layers
        assert 'domain' in report.layers
        assert 'shared' in report.layers
        assert report.stats['total_files'] == 3


class TestFormatLayerSummary:
    """Tests for format_layer_summary function."""
    
    def test_formats_markdown(self):
        report = ArchitectureReport(
            layers={
                'presentation': ['a.tsx'],
                'domain': ['b.py', 'c.py'],
                'infrastructure': [],
                'application': [],
                'shared': ['d.py'],
            },
            violations=[],
            stats={'total_files': 4},
        )
        
        summary = format_layer_summary(report)
        
        assert "Architecture Layers" in summary
        assert "Presentation" in summary


class TestFormatLayerViolations:
    """Tests for format_layer_violations function."""
    
    def test_no_violations_message(self):
        result = format_layer_violations([])
        assert "No layer violations" in result
    
    def test_formats_violations_table(self):
        violations = [
            LayerViolation(
                source_path="db.py",
                source_layer="infrastructure",
                target_path="view.py",
                target_layer="presentation",
                message="test"
            )
        ]
        
        result = format_layer_violations(violations)
        
        assert "db.py" in result
        assert "infrastructure" in result
        assert "presentation" in result
