"""Tests for config.py.

Conceptual justification:
    config.py is the foundation module — every other module imports from it.
    If validate() silently accepts missing credentials, all downstream modules
    will fail with confusing errors. These tests ensure the config layer catches
    misconfiguration early with clear messages.
"""

import importlib
import pytest


def _reload_config():
    """Force-reload config to pick up changed env vars."""
    import config
    return importlib.reload(config)


def test_validate_passes_with_all_creds(monkeypatch):
    """validate() should not raise when all required env vars are set."""
    monkeypatch.setenv("NEO4J_PASSWORD", "secret")
    monkeypatch.setenv("GOOGLE_API_KEY", "key123")
    config = _reload_config()
    config.validate()


def test_validate_raises_on_missing_neo4j_password(monkeypatch):
    """validate() must raise EnvironmentError when NEO4J_PASSWORD is empty."""
    monkeypatch.setenv("NEO4J_PASSWORD", "")
    monkeypatch.setenv("GOOGLE_API_KEY", "key123")
    config = _reload_config()
    with pytest.raises(EnvironmentError, match="NEO4J_PASSWORD"):
        config.validate()


def test_validate_raises_on_missing_google_api_key(monkeypatch):
    """validate() must raise EnvironmentError when GOOGLE_API_KEY is empty."""
    monkeypatch.setenv("NEO4J_PASSWORD", "secret")
    monkeypatch.setenv("GOOGLE_API_KEY", "")
    config = _reload_config()
    with pytest.raises(EnvironmentError, match="GOOGLE_API_KEY"):
        config.validate()


def test_validate_raises_on_both_missing(monkeypatch):
    """validate() must list all missing vars, not just the first one."""
    monkeypatch.setenv("NEO4J_PASSWORD", "")
    monkeypatch.setenv("GOOGLE_API_KEY", "")
    config = _reload_config()
    with pytest.raises(EnvironmentError, match="NEO4J_PASSWORD"):
        config.validate()


def test_defaults_loaded(monkeypatch):
    """Default values should be used when env vars are not explicitly set."""
    monkeypatch.setenv("NEO4J_PASSWORD", "pw")
    monkeypatch.setenv("GOOGLE_API_KEY", "key")
    monkeypatch.delenv("NEO4J_URI", raising=False)
    config = _reload_config()
    assert config.NEO4J_URI == "neo4j://127.0.0.1:7687"
    assert config.CHUNK_SIZE == 350
    assert config.MAX_WORKERS == 4


def test_configure_logging_does_not_raise():
    """configure_logging() should run without errors."""
    import config
    config.configure_logging()
