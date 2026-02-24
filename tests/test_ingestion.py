"""Tests for ingestion.py.

Conceptual justification:
    Ingestion loads pickled graph documents into Neo4j. These tests verify:
    1. Resumability: skips when __Entity__ nodes already exist.
    2. FileNotFoundError: raised when pickle is missing.
    3. Correct call: add_graph_documents is called with the right params.
    Mocking db.get_graph() ensures no real Neo4j connection is needed.
"""

import pickle
import importlib
import pytest
from unittest.mock import patch, MagicMock


def test_ingest_skips_when_entities_exist():
    """ingest_graphs() should skip when __Entity__ nodes already exist in DB."""
    mock_graph = MagicMock()
    mock_graph.query.return_value = [{"c": 500}]

    import ingestion
    ingestion = importlib.reload(ingestion)

    with patch.object(ingestion.db, "get_graph", return_value=mock_graph):
        ingestion.ingest_graphs()

    mock_graph.add_graph_documents.assert_not_called()


def test_ingest_raises_on_missing_pickle(tmp_path):
    """ingest_graphs() should raise FileNotFoundError for missing pkl."""
    fake_pkl = tmp_path / "nonexistent.pkl"

    import ingestion
    ingestion = importlib.reload(ingestion)

    with pytest.raises(FileNotFoundError):
        ingestion.ingest_graphs(pkl_path=fake_pkl)


def test_ingest_loads_and_pushes(tmp_path):
    """ingest_graphs() should load pickle and call add_graph_documents."""
    # Use a simple serializable list instead of MagicMock
    test_graphs = [{"type": "graph", "nodes": ["a"]}, {"type": "graph", "nodes": ["b"]}]
    pkl_path = tmp_path / "graph_all.pkl"
    with pkl_path.open("wb") as f:
        pickle.dump(test_graphs, f)

    mock_graph = MagicMock()
    mock_graph.query.side_effect = [
        [{"c": 0}],  # resumability check: no entities
        [],           # summary query
    ]

    import ingestion
    ingestion = importlib.reload(ingestion)

    with patch.object(ingestion.db, "get_graph", return_value=mock_graph):
        ingestion.ingest_graphs(pkl_path=pkl_path)

    mock_graph.add_graph_documents.assert_called_once()
    call_kwargs = mock_graph.add_graph_documents.call_args.kwargs
    assert call_kwargs["baseEntityLabel"] is True
    assert call_kwargs["include_source"] is True
