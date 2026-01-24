"""Tests for coupling metrics calculator."""

import pytest
from dataclasses import dataclass, field
from typing import List, Dict, Any

# Mock the required types for testing
@dataclass
class MockChunk:
    id: str
    type: str
    name: str
    metadata: Dict[str, Any] = field(default_factory=dict)
    signature: str = ""
    start_line: int = 1
    end_line: int = 10


@dataclass
class MockFileEntry:
    path: str
    chunks: List[MockChunk] = field(default_factory=list)
    imports: List[Any] = field(default_factory=list)
    exports: List[Any] = field(default_factory=list)
    language: str = "python"
    size_bytes: int = 0
    hash: str = ""


class MockGraph:
    """Mock dependency graph for testing."""
    
    def __init__(self, edges: Dict[str, set] = None):
        self.edges = edges or {}
        self._reverse = {}
        self.nodes = set()
        
        # Build nodes and reverse edges
        for source, targets in self.edges.items():
            self.nodes.add(source)
            for target in targets:
                self.nodes.add(target)
                if target not in self._reverse:
                    self._reverse[target] = set()
                self._reverse[target].add(source)
    
    def in_degree(self, node: str) -> int:
        return len(self._reverse.get(node, set()))
    
    def out_degree(self, node: str) -> int:
        return len(self.edges.get(node, set()))
    
    def get_dependencies(self, node: str):
        return self.edges.get(node, set())
    
    def get_dependents(self, node: str):
        return self._reverse.get(node, set())


# Import the module under test
from src.better_context.coupling import (
    CouplingMetrics,
    ZoneReport,
    is_abstract_chunk,
    count_abstract_definitions,
    count_concrete_definitions,
    classify_zone,
    calculate_coupling_metrics,
    calculate_all_coupling_metrics,
    calculate_directory_metrics,
    generate_zone_report,
    identify_critical_modules,
    get_coupling_summary,
    format_coupling_table,
)


class TestIsAbstractChunk:
    """Tests for is_abstract_chunk function."""
    
    def test_interface_is_abstract(self):
        assert is_abstract_chunk('interface', {}) is True
    
    def test_type_is_abstract(self):
        assert is_abstract_chunk('type', {}) is True
    
    def test_protocol_is_abstract(self):
        assert is_abstract_chunk('protocol', {}) is True
    
    def test_function_is_not_abstract(self):
        assert is_abstract_chunk('function', {}) is False
    
    def test_class_is_not_abstract(self):
        assert is_abstract_chunk('class', {}) is False
    
    def test_metadata_is_abstract_flag(self):
        assert is_abstract_chunk('class', {'is_abstract': True}) is True
    
    def test_metadata_is_protocol_flag(self):
        assert is_abstract_chunk('class', {'is_protocol': True}) is True


class TestCountDefinitions:
    """Tests for counting abstract and concrete definitions."""
    
    def test_count_abstract_definitions(self):
        file = MockFileEntry(
            path="test.py",
            chunks=[
                MockChunk(id="1", type="interface", name="IUser"),
                MockChunk(id="2", type="type", name="UserType"),
                MockChunk(id="3", type="function", name="create_user"),
            ]
        )
        assert count_abstract_definitions(file) == 2
    
    def test_count_concrete_definitions(self):
        file = MockFileEntry(
            path="test.py",
            chunks=[
                MockChunk(id="1", type="interface", name="IUser"),
                MockChunk(id="2", type="function", name="create_user"),
                MockChunk(id="3", type="class", name="User"),
            ]
        )
        assert count_concrete_definitions(file) == 2
    
    def test_empty_chunks(self):
        file = MockFileEntry(path="test.py", chunks=[])
        assert count_abstract_definitions(file) == 0
        assert count_concrete_definitions(file) == 0


class TestClassifyZone:
    """Tests for zone classification."""
    
    def test_main_sequence(self):
        # On main sequence: A + I ≈ 1
        assert classify_zone(i=0.5, a=0.5) == 'main'  # D = 0
        assert classify_zone(i=0.3, a=0.8) == 'main'  # D = 0.1
    
    def test_zone_of_pain(self):
        # Stable but concrete: low I, low A
        assert classify_zone(i=0.1, a=0.1) == 'pain'
        assert classify_zone(i=0.2, a=0.2) == 'pain'
    
    def test_zone_of_uselessness(self):
        # Unstable and abstract: high I, high A
        assert classify_zone(i=0.9, a=0.8) == 'uselessness'
        assert classify_zone(i=0.8, a=0.9) == 'uselessness'
    
    def test_neutral_zone(self):
        # Neither main sequence nor problematic zones
        assert classify_zone(i=0.5, a=0.1) == 'neutral'  # D = 0.4


class TestCalculateCouplingMetrics:
    """Tests for calculate_coupling_metrics function."""
    
    def test_basic_metrics(self):
        # Simple graph: a.py imports b.py
        graph = MockGraph(edges={
            "a.py": {"b.py"},
            "b.py": set(),
        })
        
        files = [
            MockFileEntry(path="a.py", chunks=[
                MockChunk(id="1", type="function", name="func_a"),
            ]),
            MockFileEntry(path="b.py", chunks=[
                MockChunk(id="2", type="interface", name="IService"),
                MockChunk(id="3", type="function", name="func_b"),
            ]),
        ]
        
        # a.py: Ca=0 (no one imports it), Ce=1 (imports b.py)
        metrics_a = calculate_coupling_metrics("a.py", graph, files)
        assert metrics_a.ca == 0
        assert metrics_a.ce == 1
        assert metrics_a.i == 1.0  # Ce/(Ca+Ce) = 1/1 = 1.0
        
        # b.py: Ca=1 (a.py imports it), Ce=0 (imports nothing)
        metrics_b = calculate_coupling_metrics("b.py", graph, files)
        assert metrics_b.ca == 1
        assert metrics_b.ce == 0
        assert metrics_b.i == 0.0  # Ce/(Ca+Ce) = 0/1 = 0.0
    
    def test_abstractness_calculation(self):
        graph = MockGraph(edges={"test.py": set()})
        
        files = [
            MockFileEntry(path="test.py", chunks=[
                MockChunk(id="1", type="interface", name="IUser"),
                MockChunk(id="2", type="type", name="UserType"),
                MockChunk(id="3", type="function", name="create"),
                MockChunk(id="4", type="class", name="User"),
            ]),
        ]
        
        metrics = calculate_coupling_metrics("test.py", graph, files)
        # 2 abstract, 2 concrete -> A = 0.5
        assert metrics.abstract_count == 2
        assert metrics.concrete_count == 2
        assert metrics.a == 0.5
    
    def test_isolated_node(self):
        graph = MockGraph(edges={"isolated.py": set()})
        files = [MockFileEntry(path="isolated.py")]
        
        metrics = calculate_coupling_metrics("isolated.py", graph, files)
        assert metrics.ca == 0
        assert metrics.ce == 0
        assert metrics.i == 0.5  # Default for isolated nodes


class TestCalculateAllCouplingMetrics:
    """Tests for calculate_all_coupling_metrics function."""
    
    def test_calculates_for_all_nodes(self):
        graph = MockGraph(edges={
            "a.py": {"b.py"},
            "b.py": {"c.py"},
            "c.py": set(),
        })
        files = [
            MockFileEntry(path="a.py"),
            MockFileEntry(path="b.py"),
            MockFileEntry(path="c.py"),
        ]
        
        metrics = calculate_all_coupling_metrics(graph, files)
        
        assert "a.py" in metrics
        assert "b.py" in metrics
        assert "c.py" in metrics


class TestGenerateZoneReport:
    """Tests for generate_zone_report function."""
    
    def test_generates_report(self):
        metrics = {
            "main.py": CouplingMetrics(
                path="main.py", ca=2, ce=2, i=0.5, a=0.5, d=0.0, zone='main'
            ),
            "concrete.py": CouplingMetrics(
                path="concrete.py", ca=5, ce=0, i=0.0, a=0.0, d=1.0, zone='pain'
            ),
            "abstract.py": CouplingMetrics(
                path="abstract.py", ca=0, ce=5, i=1.0, a=0.9, d=0.9, zone='uselessness'
            ),
        }
        
        report = generate_zone_report(metrics)
        
        assert "main.py" in report.on_main_sequence
        assert "concrete.py" in report.zone_of_pain
        assert "abstract.py" in report.zone_of_uselessness
        assert len(report.recommendations) == 2


class TestIdentifyCriticalModules:
    """Tests for identify_critical_modules function."""
    
    def test_identifies_high_impact(self):
        metrics = {
            "core.py": CouplingMetrics(
                path="core.py", ca=10, ce=1, i=0.09, a=0.5, d=0.41, zone='neutral'
            ),
            "util.py": CouplingMetrics(
                path="util.py", ca=2, ce=3, i=0.6, a=0.3, d=0.1, zone='main'
            ),
        }
        
        critical = identify_critical_modules(metrics, ca_threshold=5)
        
        assert len(critical) == 1
        assert critical[0]['path'] == "core.py"


class TestGetCouplingSummary:
    """Tests for get_coupling_summary function."""
    
    def test_summary_stats(self):
        metrics = {
            "a.py": CouplingMetrics(path="a.py", ca=2, ce=2, i=0.5, a=0.5, d=0.0, zone='main'),
            "b.py": CouplingMetrics(path="b.py", ca=0, ce=4, i=1.0, a=0.0, d=0.0, zone='main'),
        }
        
        summary = get_coupling_summary(metrics)
        
        assert summary['total_modules'] == 2
        assert summary['zone_counts']['main'] == 2
        assert summary['avg_instability'] == 0.75
    
    def test_empty_metrics(self):
        summary = get_coupling_summary({})
        assert summary['total_modules'] == 0


class TestFormatCouplingTable:
    """Tests for format_coupling_table function."""
    
    def test_formats_table(self):
        metrics = {
            "test.py": CouplingMetrics(
                path="test.py", ca=2, ce=3, i=0.6, a=0.4, d=0.0, zone='main'
            ),
        }
        
        table = format_coupling_table(metrics)
        
        assert "| File | Ca | Ce | I | A | D | Zone |" in table
        assert "test.py" in table
        assert "✅" in table  # main sequence emoji
