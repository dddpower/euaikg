"""Tests for extraction.py.

Conceptual justification:
    Extraction is the heaviest phase (vLLM + Gemini fallback). These tests verify:
    1. Resumability: extract_graphs() returns early when graph_all.pkl exists.
    2. Save logic: pkl and jsonl files are created correctly.
    Mocking LLM transformers ensures tests run without a vLLM or Gemini server.
"""

import pickle
import importlib
from pathlib import Path
from unittest.mock import patch, MagicMock


def test_extract_graphs_skips_when_cache_exists(tmp_path, sample_documents):
    """extract_graphs() should return immediately if graph_all.pkl exists."""
    cache_dir = tmp_path / "graph_cache"
    cache_dir.mkdir()
    all_pkl = cache_dir / "graph_all.pkl"
    with all_pkl.open("wb") as f:
        pickle.dump([], f)

    import extraction
    extraction = importlib.reload(extraction)
    extraction.config.GRAPH_CACHE_DIR = cache_dir

    result = extraction.extract_graphs(sample_documents)
    assert result == all_pkl


def test_extract_graphs_creates_cache_dir(tmp_path, sample_documents):
    """extract_graphs() should create the cache dir if missing."""
    cache_dir = tmp_path / "new_cache"

    mock_transformer = MagicMock()
    mock_transformer.convert_to_graph_documents.return_value = []

    import extraction
    extraction = importlib.reload(extraction)
    extraction.config.GRAPH_CACHE_DIR = cache_dir
    extraction.config.MAX_WORKERS = 1
    extraction.config.EXTRACTION_TIMEOUT = 10

    with patch.object(extraction, "_make_vllm_transformer", return_value=mock_transformer):
        extraction.extract_graphs(sample_documents)

    assert cache_dir.exists()


def test_save_graphs_creates_files(tmp_path):
    """_save_graphs should create both pkl and jsonl files."""
    import extraction
    extraction = importlib.reload(extraction)

    # Use a simple serializable object instead of MagicMock
    fake_graph = {"nodes": ["a", "b"], "edges": [("a", "b")]}
    extraction._save_graphs(tmp_path, 1, [fake_graph])

    assert (tmp_path / "graph_page_001.pkl").exists()
    assert (tmp_path / "graph_page_001.jsonl").exists()


def test_save_graphs_gemini_suffix(tmp_path):
    """_save_graphs with suffix='gemini' should add _gemini to filenames."""
    import extraction
    extraction = importlib.reload(extraction)

    fake_graph = {"nodes": ["x"], "edges": []}
    extraction._save_graphs(tmp_path, 5, [fake_graph], suffix="gemini")

    assert (tmp_path / "graph_page_005_gemini.pkl").exists()
    assert (tmp_path / "graph_page_005_gemini.jsonl").exists()
