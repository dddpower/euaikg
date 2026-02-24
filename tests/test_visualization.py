"""Tests for visualization.py.

Conceptual justification:
    The visualization module converts Neo4j query results to Cytoscape.js format.
    These tests verify:
    1. Node format: each node has data.id (whitespace-replaced) and data.label.
    2. Edge format: source, target, and label fields are populated.
    3. Deduplication: repeated nodes appear only once.
    Mocking the driver session ensures tests run without Neo4j.
"""

import importlib
from unittest.mock import patch, MagicMock


def _make_mock_record(sid, tid, rtype):
    """Create a mock Neo4j record with source, target, and relationship."""
    s = MagicMock()
    s.get.return_value = sid
    s.element_id = f"elem_{sid}"

    t = MagicMock()
    t.get.return_value = tid
    t.element_id = f"elem_{tid}"

    r = MagicMock()
    r.type = rtype

    return {"s": s, "t": t, "r": r}


def test_cy_elements_basic_conversion():
    """_cy_elements_from_neo4j should produce correct Cytoscape elements."""
    records = [
        _make_mock_record("European Commission", "AI Act", "AUTHORED"),
        _make_mock_record("AI Act", "High Risk", "DEFINES"),
    ]

    mock_session = MagicMock()
    mock_session.run.return_value = records

    mock_driver = MagicMock()
    mock_driver.session.return_value.__enter__ = MagicMock(return_value=mock_session)
    mock_driver.session.return_value.__exit__ = MagicMock(return_value=False)

    import visualization
    visualization = importlib.reload(visualization)

    with patch.object(visualization.db, "get_driver", return_value=mock_driver):
        nodes, edges = visualization._cy_elements_from_neo4j(limit=100)

    # 3 unique nodes: European Commission, AI Act, High Risk
    assert len(nodes) == 3
    assert len(edges) == 2

    node_ids = {n["data"]["id"] for n in nodes}
    assert "European_Commission" in node_ids
    assert "AI_Act" in node_ids
    assert "High_Risk" in node_ids

    edge_labels = {e["data"]["label"] for e in edges}
    assert "AUTHORED" in edge_labels
    assert "DEFINES" in edge_labels


def test_cy_elements_node_deduplication():
    """Nodes appearing in multiple edges should only appear once."""
    records = [
        _make_mock_record("NodeA", "NodeB", "REL1"),
        _make_mock_record("NodeA", "NodeC", "REL2"),
        _make_mock_record("NodeB", "NodeC", "REL3"),
    ]

    mock_session = MagicMock()
    mock_session.run.return_value = records

    mock_driver = MagicMock()
    mock_driver.session.return_value.__enter__ = MagicMock(return_value=mock_session)
    mock_driver.session.return_value.__exit__ = MagicMock(return_value=False)

    import visualization
    visualization = importlib.reload(visualization)

    with patch.object(visualization.db, "get_driver", return_value=mock_driver):
        nodes, edges = visualization._cy_elements_from_neo4j(limit=100)

    assert len(nodes) == 3
    assert len(edges) == 3
