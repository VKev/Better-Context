"""Tests for architecture diagram generation."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from better_context.graph import DependencyGraph, build_graph_from_edges
from better_context.visualize import (
    detect_layer_from_path,
    classify_files_by_layer,
    classify_files_by_directory,
    generate_architecture_diagram,
    generate_layer_diagram,
    generate_cycle_diagram,
    export_architecture_diagram,
)


class TestLayerDetection:
    """Tests for architectural layer detection from paths."""

    def test_presentation_layer(self):
        """Test detection of presentation layer files."""
        assert detect_layer_from_path("src/components/Button.tsx") == "presentation"
        assert detect_layer_from_path("pages/index.tsx") == "presentation"
        assert detect_layer_from_path("views/Home.vue") == "presentation"
        assert detect_layer_from_path("ui/widgets/card.py") == "presentation"

    def test_application_layer(self):
        """Test detection of application layer files."""
        assert detect_layer_from_path("src/handlers/auth.py") == "application"
        assert detect_layer_from_path("api/routes/users.ts") == "application"
        assert detect_layer_from_path("controllers/user_controller.py") == "application"

    def test_domain_layer(self):
        """Test detection of domain layer files."""
        assert detect_layer_from_path("models/user.py") == "domain"
        assert detect_layer_from_path("src/services/auth.ts") == "domain"
        assert detect_layer_from_path("domain/entities/order.py") == "domain"

    def test_infrastructure_layer(self):
        """Test detection of infrastructure layer files."""
        assert detect_layer_from_path("db/connection.py") == "infrastructure"
        assert detect_layer_from_path("storage/s3_client.py") == "infrastructure"
        assert detect_layer_from_path("adapters/http_client.ts") == "infrastructure"

    def test_shared_layer(self):
        """Test detection of shared/utils layer files."""
        assert detect_layer_from_path("utils/helpers.py") == "shared"
        assert detect_layer_from_path("common/types.ts") == "shared"
        assert detect_layer_from_path("lib/crypto.py") == "shared"
        assert detect_layer_from_path("config/settings.py") == "shared"

    def test_unclassified(self):
        """Test files that don't match any layer pattern."""
        assert detect_layer_from_path("main.py") is None
        assert detect_layer_from_path("app.ts") is None
        assert detect_layer_from_path("random/file.py") is None


class TestFileClassification:
    """Tests for file classification functions."""

    def test_classify_by_layer(self):
        """Test classifying files by architectural layer."""
        files = [
            "components/Button.tsx",
            "handlers/auth.py",
            "models/user.py",
            "utils/helpers.py",
            "main.py",
        ]
        
        result = classify_files_by_layer(files)
        
        assert "presentation" in result
        assert "components/Button.tsx" in result["presentation"]
        
        assert "application" in result
        assert "handlers/auth.py" in result["application"]
        
        assert "domain" in result
        assert "models/user.py" in result["domain"]
        
        assert "shared" in result
        assert "utils/helpers.py" in result["shared"]
        
        assert "other" in result
        assert "main.py" in result["other"]

    def test_classify_by_directory(self):
        """Test classifying files by directory."""
        files = [
            "src/api/routes.py",
            "src/api/handlers.py",
            "src/models/user.py",
            "tests/test_api.py",
            "main.py",
        ]
        
        result = classify_files_by_directory(files, max_depth=2)
        
        assert "src/api" in result
        assert len(result["src/api"]) == 2
        
        assert "src/models" in result
        assert len(result["src/models"]) == 1
        
        assert "root" in result
        assert "main.py" in result["root"]


class TestArchitectureDiagram:
    """Tests for architecture diagram generation."""

    def test_generates_mermaid(self):
        """Test that architecture diagram generates valid Mermaid."""
        graph = build_graph_from_edges([
            ("components/Button.tsx", "utils/helpers.ts"),
            ("handlers/auth.py", "models/user.py"),
        ])
        
        diagram = generate_architecture_diagram(graph)
        
        assert diagram.startswith("graph")
        assert "subgraph" in diagram
        assert "end" in diagram

    def test_highlights_cycles(self):
        """Test that cycle edges are highlighted."""
        graph = build_graph_from_edges([
            ("a.py", "b.py"),
            ("b.py", "c.py"),
            ("c.py", "a.py"),
        ])
        
        cycles = [["a.py", "b.py", "c.py"]]
        
        diagram = generate_architecture_diagram(graph, cycles=cycles)
        
        assert "cycle" in diagram.lower()
        assert "cycleNode" in diagram

    def test_respects_max_files(self):
        """Test that max_files_per_group is respected."""
        # Create graph with many files
        files = [f"components/file{i}.tsx" for i in range(20)]
        edges = [(f, "utils/common.ts") for f in files]
        graph = build_graph_from_edges(edges)
        
        diagram = generate_architecture_diagram(graph, max_files_per_group=5)
        
        # Should indicate there are more files
        assert "more" in diagram.lower()


class TestLayerDiagram:
    """Tests for layer diagram generation."""

    def test_generates_layer_subgraphs(self):
        """Test that layer diagram creates subgraphs for each layer."""
        graph = build_graph_from_edges([
            ("app.py", "utils.py"),
            ("utils.py", "types.py"),
        ])
        
        layers = [
            ["types.py"],
            ["utils.py"],
            ["app.py"],
        ]
        
        diagram = generate_layer_diagram(graph, layers=layers)
        
        assert "Foundation" in diagram
        assert "Core Utilities" in diagram
        assert "Application Layer" in diagram

    def test_computes_layers_if_not_provided(self):
        """Test that layers are computed if not provided."""
        graph = build_graph_from_edges([
            ("a.py", "b.py"),
            ("b.py", "c.py"),
        ])
        
        diagram = generate_layer_diagram(graph)
        
        # Should still generate a valid diagram
        assert diagram.startswith("graph TB")
        assert "subgraph" in diagram


class TestCycleDiagram:
    """Tests for cycle-focused diagram generation."""

    def test_no_cycles(self):
        """Test diagram when no cycles exist."""
        graph = build_graph_from_edges([("a.py", "b.py")])
        
        diagram = generate_cycle_diagram(graph, cycles=[])
        
        assert "No circular dependencies" in diagram
        assert "✓" in diagram

    def test_shows_cycle_nodes(self):
        """Test that cycle nodes are shown."""
        graph = build_graph_from_edges([
            ("a.py", "b.py"),
            ("b.py", "a.py"),
        ])
        
        cycles = [["a.py", "b.py"]]
        
        diagram = generate_cycle_diagram(graph, cycles)
        
        assert "a_py" in diagram  # node_id converts . to _
        assert "b_py" in diagram
        assert "cycleNode" in diagram

    def test_limits_cycles(self):
        """Test that max_cycles limits output."""
        graph = DependencyGraph()
        # Create many cycles
        cycles = [[f"file{i}.py", f"file{i+100}.py"] for i in range(10)]
        for cycle in cycles:
            for f in cycle:
                graph.add_node(f)
            graph.add_edge(cycle[0], cycle[1])
            graph.add_edge(cycle[1], cycle[0])
        
        diagram = generate_cycle_diagram(graph, cycles, max_cycles=3)
        
        assert "more cycles" in diagram.lower()


class TestExportArchitectureDiagram:
    """Tests for the high-level export function."""

    def test_architecture_type(self):
        """Test architecture diagram type."""
        graph = build_graph_from_edges([("a.py", "b.py")])
        
        diagram = export_architecture_diagram(graph, "architecture")
        
        assert "graph" in diagram

    def test_layers_type(self):
        """Test layers diagram type."""
        graph = build_graph_from_edges([("a.py", "b.py")])
        
        diagram = export_architecture_diagram(graph, "layers")
        
        assert "graph TB" in diagram

    def test_cycles_type(self):
        """Test cycles diagram type."""
        graph = build_graph_from_edges([("a.py", "b.py")])
        
        diagram = export_architecture_diagram(graph, "cycles", cycles=[])
        
        assert "No circular dependencies" in diagram

    def test_invalid_type(self):
        """Test that invalid type raises ValueError."""
        graph = build_graph_from_edges([("a.py", "b.py")])
        
        with pytest.raises(ValueError) as exc_info:
            export_architecture_diagram(graph, "invalid")
        
        assert "Unsupported diagram type" in str(exc_info.value)
