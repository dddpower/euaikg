"""Tests for community.py.

Conceptual justification:
    The community module performs embedding, similarity detection, and entity
    deduplication. These tests verify:
    1. Resumability: skips embedding+WCC when wcc property already exists.
    2. Full pipeline: runs embed+WCC when no wcc property.
    3. Duplicate candidates query uses the correct distance parameter.
    Mocking GDS and Gemini ensures tests run without external services.
"""

import importlib
from unittest.mock import patch, MagicMock


def test_resolve_and_merge_skips_when_wcc_exists():
    """resolve_and_merge() should skip embed+WCC when wcc property found."""
    mock_graph = MagicMock()
    mock_graph.query.side_effect = [
        [{"c": 100}],  # wcc_check: wcc exists
        [],             # find_duplicate_candidates: no duplicates
    ]

    import community
    community = importlib.reload(community)

    with patch.object(community.db, "get_graph", return_value=mock_graph), \
         patch.object(community, "embed_entities") as mock_embed, \
         patch.object(community, "run_community_detection") as mock_detect:
        community.resolve_and_merge()
        mock_embed.assert_not_called()
        mock_detect.assert_not_called()


def test_resolve_and_merge_runs_full_pipeline_when_no_wcc():
    """resolve_and_merge() should run embed+WCC when no wcc property found."""
    mock_graph = MagicMock()
    mock_graph.query.side_effect = [
        [{"c": 0}],  # wcc_check: no wcc
        [],           # find_duplicate_candidates: no duplicates
    ]

    mock_G = MagicMock()

    import community
    community = importlib.reload(community)

    with patch.object(community.db, "get_graph", return_value=mock_graph), \
         patch.object(community, "embed_entities") as mock_embed, \
         patch.object(community, "run_community_detection", return_value=mock_G) as mock_detect:
        community.resolve_and_merge()
        mock_embed.assert_called_once()
        mock_detect.assert_called_once()
        mock_G.drop.assert_called_once()


def test_find_duplicate_candidates_calls_correct_cypher():
    """find_duplicate_candidates() should query with WORD_EDIT_DISTANCE param."""
    mock_graph = MagicMock()
    mock_graph.query.return_value = [{"combinedResult": ["Entity A", "Entity a"]}]

    import community
    community = importlib.reload(community)
    community.config.WORD_EDIT_DISTANCE = 3

    with patch.object(community.db, "get_graph", return_value=mock_graph):
        result = community.find_duplicate_candidates()

    assert len(result) == 1
    call_kwargs = mock_graph.query.call_args.kwargs
    assert call_kwargs["params"]["distance"] == 3
