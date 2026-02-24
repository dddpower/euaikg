"""Tests for db.py.

Conceptual justification:
    db.py manages the Neo4j connection lifecycle. The singleton pattern must
    return the same driver on repeated calls, wipe_database must execute the
    correct Cypher, and close() must reset state so a new driver can be created.
    Mocking GraphDatabase.driver ensures tests run without a real Neo4j instance.
"""

import importlib
from unittest.mock import MagicMock, patch


def _fresh_db():
    """Reload db module to reset singletons."""
    import db
    db = importlib.reload(db)
    return db


def test_get_driver_returns_singleton():
    """get_driver() should return the same object on repeated calls."""
    db = _fresh_db()
    mock_driver = MagicMock()
    with patch.object(db, "GraphDatabase") as mock_gdb:
        mock_gdb.driver.return_value = mock_driver
        d1 = db.get_driver()
        d2 = db.get_driver()
        assert d1 is d2
        mock_gdb.driver.assert_called_once()
    db.close()


def test_close_resets_singleton():
    """After close(), get_driver() should create a new driver."""
    db = _fresh_db()
    mock_driver1 = MagicMock()
    mock_driver2 = MagicMock()
    with patch.object(db, "GraphDatabase") as mock_gdb:
        mock_gdb.driver.side_effect = [mock_driver1, mock_driver2]
        d1 = db.get_driver()
        db.close()
        d2 = db.get_driver()
        assert d1 is not d2
        mock_driver1.close.assert_called_once()
    db.close()


def test_wipe_database_runs_delete_cypher():
    """wipe_database() should execute MATCH (n) DETACH DELETE n."""
    db = _fresh_db()
    mock_session = MagicMock()
    mock_driver = MagicMock()
    mock_driver.session.return_value.__enter__ = MagicMock(return_value=mock_session)
    mock_driver.session.return_value.__exit__ = MagicMock(return_value=False)

    with patch.object(db, "GraphDatabase") as mock_gdb:
        mock_gdb.driver.return_value = mock_driver
        db.wipe_database()
        mock_session.run.assert_called_once_with("MATCH (n) DETACH DELETE n")
    db.close()


def test_test_connection_succeeds():
    """test_connection() should run without error when DB responds."""
    db = _fresh_db()
    mock_session = MagicMock()
    mock_result = MagicMock()
    mock_result.single.return_value = {"num": 1}
    mock_session.execute_read.side_effect = lambda fn: fn(mock_session)
    mock_session.run.return_value = mock_result

    mock_driver = MagicMock()
    mock_driver.session.return_value.__enter__ = MagicMock(return_value=mock_session)
    mock_driver.session.return_value.__exit__ = MagicMock(return_value=False)

    with patch.object(db, "GraphDatabase") as mock_gdb:
        mock_gdb.driver.return_value = mock_driver
        db.test_connection()
    db.close()
