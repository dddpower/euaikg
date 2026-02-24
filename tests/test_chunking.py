"""Tests for chunking.py.

Conceptual justification:
    The chunking module splits the EU AI Act into token-aware chunks.
    These tests verify that:
    1. Documents are produced with correct 1-based page numbering.
    2. Source metadata is preserved for traceability.
    3. The tokenizer-based length function is used correctly.
    Mocking the tokenizer and file read ensures tests run without
    downloading the actual model or requiring the source file.
"""

import importlib
from unittest.mock import MagicMock, patch


def test_load_and_chunk_produces_documents(tmp_path):
    """load_and_chunk() should produce documents with correct metadata."""
    test_file = tmp_path / "test.txt"
    test_file.write_text(
        "First paragraph about AI regulation.\n\n"
        "Second paragraph about high-risk systems.\n\n"
        "Third paragraph about definitions and scope."
    )

    mock_tokenizer = MagicMock()
    mock_tokenizer.encode.side_effect = lambda text: text.split()

    # Create a real-ish splitter that actually splits text
    class FakeSplitter:
        def __init__(self, **kwargs):
            pass
        def split_text(self, text):
            return [p.strip() for p in text.split("\n\n") if p.strip()]

    import chunking
    chunking = importlib.reload(chunking)
    chunking._tokenizer = mock_tokenizer

    with patch.object(chunking, "RecursiveCharacterTextSplitter", FakeSplitter):
        docs = chunking.load_and_chunk(source_file=test_file)

    assert len(docs) == 3
    assert docs[0].metadata["page"] == 1
    assert docs[2].metadata["page"] == 3
    assert str(test_file) in docs[0].metadata["source"]
    pages = [d.metadata["page"] for d in docs]
    assert pages == [1, 2, 3]


def test_num_tokens_from_string():
    """num_tokens_from_string should use the tokenizer to count."""
    mock_tokenizer = MagicMock()
    mock_tokenizer.encode.return_value = [1, 2, 3, 4, 5]

    import chunking
    chunking = importlib.reload(chunking)
    chunking._tokenizer = mock_tokenizer

    count = chunking.num_tokens_from_string("hello world test")
    assert count == 5
    mock_tokenizer.encode.assert_called_once_with("hello world test")
