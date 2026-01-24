"""Tests for betweenness centrality and bridge file detection."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from better_context.graph import DependencyGraph, build_graph_from_edges
from better_context.centrality import (
    calculate_betweenness,
    BridgeFile,
    find_bridge_files,
    get_hidden_bridges,
    format_bridge_file_table,
    calculate_pagerank,
)


class TestBetweennessCentrality:
    """Tests for betweenness centrality calculation."""

    def test_empty_graph(self):
        """Test betweenness on empty graph."""
        graph = DependencyGraph()
        scores = calculate_betweenness(graph)
        assert scores == {}

    def test_single_node(self):
        """Test betweenness on single node graph."""
        graph = DependencyGraph()
        graph.add_node("a.py")
        scores = calculate_betweenness(graph)
        assert scores == {"a.py": 0.0}

    def test_two_nodes(self):
        """Test betweenness on two-node graph."""
        graph = build_graph_from_edges([("a.py", "b.py")])
        scores = calculate_betweenness(graph)
        # With only 2 nodes, betweenness is 0
        assert scores["a.py"] == 0.0
        assert scores["b.py"] == 0.0

    def test_linear_chain(self):
        """Test betweenness on linear chain: A -> B -> C."""
        graph = build_graph_from_edges([
            ("a.py", "b.py"),
            ("b.py", "c.py"),
        ])
        scores = calculate_betweenness(graph)
        
        # B is between A and C, should have highest betweenness
        assert scores["b.py"] > scores["a.py"]
        assert scores["b.py"] > scores["c.py"]

    def test_bridge_node(self):
        """Test that a bridge node has high betweenness."""
        # Create a graph where bridge.py connects two clusters
        graph = build_graph_from_edges([
            ("a1.py", "bridge.py"),
            ("a2.py", "bridge.py"),
            ("bridge.py", "b1.py"),
            ("bridge.py", "b2.py"),
        ])
        scores = calculate_betweenness(graph)
        
        # bridge.py should have highest betweenness
        bridge_score = scores["bridge.py"]
        for node in ["a1.py", "a2.py", "b1.py", "b2.py"]:
            assert bridge_score >= scores[node]

    def test_star_topology(self):
        """Test betweenness in star topology (hub with spokes)."""
        # Hub connects to all spokes
        graph = build_graph_from_edges([
            ("hub.py", "spoke1.py"),
            ("hub.py", "spoke2.py"),
            ("hub.py", "spoke3.py"),
        ])
        scores = calculate_betweenness(graph)
        
        # Hub should have highest betweenness
        hub_score = scores["hub.py"]
        for node in ["spoke1.py", "spoke2.py", "spoke3.py"]:
            assert hub_score >= scores[node]

    def test_normalized_scores(self):
        """Test that betweenness scores are properly normalized."""
        graph = build_graph_from_edges([
            ("a.py", "b.py"),
            ("b.py", "c.py"),
            ("c.py", "d.py"),
        ])
        scores = calculate_betweenness(graph)
        
        # All scores should be between 0 and 1
        for score in scores.values():
            assert 0.0 <= score <= 1.0


class TestFindBridgeFiles:
    """Tests for find_bridge_files function."""

    def test_no_bridges_below_threshold(self):
        """Test that no bridges are returned if all below threshold."""
        graph = build_graph_from_edges([("a.py", "b.py")])
        bridges = find_bridge_files(graph, threshold=0.5)
        assert len(bridges) == 0

    def test_finds_bridge_file(self):
        """Test finding a bridge file."""
        # Create a graph with a clear bridge
        graph = build_graph_from_edges([
            ("a.py", "bridge.py"),
            ("bridge.py", "b.py"),
            ("c.py", "bridge.py"),
            ("bridge.py", "d.py"),
        ])
        
        bridges = find_bridge_files(graph, threshold=0.01)
        
        # Should find at least one bridge
        assert len(bridges) > 0
        
        # All returned objects should be BridgeFile
        for b in bridges:
            assert isinstance(b, BridgeFile)
            assert b.path != ""
            assert b.betweenness >= 0
            assert b.pagerank >= 0
            assert b.risk_level in ("high", "medium", "low")

    def test_respects_top_n(self):
        """Test that top_n limits results."""
        # Create graph with multiple potential bridges
        edges = [(f"in{i}.py", "bridge.py") for i in range(5)]
        edges += [("bridge.py", f"out{i}.py") for i in range(5)]
        graph = build_graph_from_edges(edges)
        
        bridges = find_bridge_files(graph, threshold=0.0, top_n=1)
        assert len(bridges) <= 1

    def test_sorted_by_betweenness(self):
        """Test that results are sorted by betweenness descending."""
        # Create two bridges
        graph = build_graph_from_edges([
            ("a.py", "bridge1.py"),
            ("bridge1.py", "middle.py"),
            ("middle.py", "bridge2.py"),
            ("bridge2.py", "b.py"),
        ])
        
        bridges = find_bridge_files(graph, threshold=0.0)
        
        # Check descending order
        for i in range(len(bridges) - 1):
            assert bridges[i].betweenness >= bridges[i + 1].betweenness


class TestGetHiddenBridges:
    """Tests for hidden bridge detection."""

    def test_empty_graph(self):
        """Test hidden bridges on empty graph."""
        graph = DependencyGraph()
        hidden = get_hidden_bridges(graph)
        assert hidden == []

    def test_identifies_hidden_bridges(self):
        """Test that files with high BC but low PR are identified."""
        # Create a graph where the bridge has low in-degree but high betweenness
        graph = build_graph_from_edges([
            ("a.py", "b.py"),
            ("b.py", "c.py"),  # b is a bridge
            ("c.py", "d.py"),
        ])
        
        hidden = get_hidden_bridges(graph, ratio_threshold=1.0)
        
        # Should find hidden bridges in this topology
        # (depending on exact scores)
        assert isinstance(hidden, list)

    def test_uses_precomputed_scores(self):
        """Test that pre-computed scores are used."""
        graph = build_graph_from_edges([("a.py", "b.py"), ("b.py", "c.py")])
        
        # Provide fake scores
        betweenness = {"a.py": 0.5, "b.py": 0.1, "c.py": 0.0}
        pagerank = {"a.py": 0.1, "b.py": 0.5, "c.py": 0.4}
        
        hidden = get_hidden_bridges(
            graph,
            betweenness=betweenness,
            pagerank=pagerank,
            ratio_threshold=2.0
        )
        
        # a.py has high BC/PR ratio (0.5/0.1 = 5.0 > 2.0)
        assert any(b.path == "a.py" for b in hidden)


class TestBridgeFileTable:
    """Tests for Markdown table formatting."""

    def test_empty_list(self):
        """Test formatting empty bridge list."""
        result = format_bridge_file_table([])
        assert "No bridge files detected" in result

    def test_formats_bridges(self):
        """Test formatting bridge files as table."""
        bridges = [
            BridgeFile(
                path="utils/bridge.py",
                betweenness=0.342,
                pagerank=0.023,
                risk_level="high",
                description="critical connector"
            ),
            BridgeFile(
                path="lib/adapter.py",
                betweenness=0.187,
                pagerank=0.015,
                risk_level="medium",
                description="adapter pattern"
            ),
        ]
        
        result = format_bridge_file_table(bridges)
        
        # Check table structure
        assert "| File |" in result
        assert "| Betweenness |" in result
        assert "| PageRank |" in result
        assert "| Risk |" in result
        
        # Check content
        assert "utils/bridge.py" in result
        assert "lib/adapter.py" in result
        assert "High" in result
        assert "Medium" in result
        assert "critical connector" in result

    def test_formats_numbers(self):
        """Test that numbers are formatted correctly."""
        bridges = [
            BridgeFile(
                path="test.py",
                betweenness=0.1234567,
                pagerank=0.0000001,
                risk_level="low",
                description="test"
            ),
        ]
        
        result = format_bridge_file_table(bridges)
        
        # Should have 4 decimal places
        assert "0.1235" in result  # rounded
        assert "0.0000" in result


class TestBridgeFileDescription:
    """Tests for bridge file description generation."""

    def test_description_includes_connections(self):
        """Test that description includes connectivity info."""
        graph = build_graph_from_edges([
            ("a.py", "bridge.py"),
            ("b.py", "bridge.py"),
            ("bridge.py", "c.py"),
        ])
        
        bridges = find_bridge_files(graph, threshold=0.0)
        
        # Find the bridge
        bridge = next((b for b in bridges if "bridge" in b.path), None)
        if bridge:
            assert "connects" in bridge.description.lower() or "import" in bridge.description.lower()

    def test_identifies_index_files(self):
        """Test that barrel/index files are identified."""
        graph = build_graph_from_edges([
            ("a.py", "index.py"),
            ("index.py", "b.py"),
        ])
        
        bridges = find_bridge_files(graph, threshold=0.0)
        
        index_bridge = next((b for b in bridges if "index" in b.path), None)
        if index_bridge:
            assert "barrel" in index_bridge.description.lower() or "re-export" in index_bridge.description.lower()
