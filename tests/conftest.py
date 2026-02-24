"""Shared fixtures and mocks for all test modules.

Mocks heavy third-party dependencies at sys.modules level so tests run
without installing langchain, neo4j, flask, transformers, etc.
"""

import os
import sys
import types
import pytest
from unittest.mock import MagicMock
from pathlib import Path

# Ensure project root is importable
sys.path.insert(0, str(Path(__file__).parent.parent))

# ── Stub out heavy third-party modules before any production code imports ──
_STUB_MODULES = [
    # langchain ecosystem
    "langchain", "langchain.schema", "langchain.text_splitter",
    "langchain.embeddings",
    "langchain_core", "langchain_core.runnables",
    "langchain_core.prompts", "langchain_core.output_parsers",
    "langchain_core.load", "langchain_core.documents",
    "langchain_core.pydantic_v1",
    "langchain_community", "langchain_community.vectorstores",
    "langchain_community.vectorstores.neo4j_vector",
    "langchain_community.document_loaders",
    "langchain_community.graphs", "langchain_community.graphs.graph_document",
    "langchain_neo4j",
    "langchain_openai",
    "langchain_experimental", "langchain_experimental.graph_transformers",
    "langchain_google_genai",
    # neo4j
    "neo4j",
    # ML / embeddings
    "transformers",
    "torch",
    "sentence_transformers",
    # graph data science
    "graphdatascience",
    # web
    "flask",
    # utilities
    "retry",
    "tqdm",
    "pandas",
    "pydantic",
    # dotenv — we do NOT mock this; it's lightweight and installed
]


def _create_stub_module(name):
    """Create a stub module with MagicMock attributes."""
    mod = types.ModuleType(name)
    mod.__dict__["__path__"] = []  # allow sub-imports
    # Common classes/functions return MagicMock when accessed
    mod.__dict__["__getattr__"] = lambda attr: MagicMock()
    return mod


for _mod_name in _STUB_MODULES:
    if _mod_name not in sys.modules:
        sys.modules[_mod_name] = _create_stub_module(_mod_name)

# ── Provide a real-ish Document class for sample_documents fixture ──
class _FakeDocument:
    def __init__(self, page_content="", metadata=None):
        self.page_content = page_content
        self.metadata = metadata or {}

# Patch it into the langchain stubs
sys.modules["langchain.schema"].Document = _FakeDocument
sys.modules["langchain_core.documents"].Document = _FakeDocument

# Provide real BaseModel/Field stubs for pydantic_v1
class _FakeBaseModel:
    pass

def _fake_field(**kwargs):
    return None

sys.modules["langchain_core.pydantic_v1"].BaseModel = _FakeBaseModel
sys.modules["langchain_core.pydantic_v1"].Field = _fake_field

# Provide a real GraphDocument class stub
class _FakeGraphDocument:
    pass

sys.modules["langchain_community.graphs.graph_document"].GraphDocument = _FakeGraphDocument

# Provide retry decorator stub that just calls the function
def _fake_retry(**kwargs):
    def decorator(fn):
        return fn
    return decorator

sys.modules["retry"].retry = _fake_retry

# Provide tqdm passthrough
sys.modules["tqdm"].tqdm = lambda iterable, **kw: iterable

# Provide dumps stub
sys.modules["langchain_core.load"].dumps = lambda obj: '{"stub": true}'


# ── Now we can safely import config (it only needs dotenv) ──
# Force-reload config so it picks up test env vars
import importlib


@pytest.fixture(autouse=True)
def mock_env(monkeypatch):
    """Set minimal environment variables for all tests."""
    monkeypatch.setenv("NEO4J_URI", "neo4j://localhost:7687")
    monkeypatch.setenv("NEO4J_USER", "neo4j")
    monkeypatch.setenv("NEO4J_PASSWORD", "testpassword")
    monkeypatch.setenv("GOOGLE_API_KEY", "test-api-key")
    monkeypatch.setenv("VLLM_BASE_URL", "http://localhost:8000/v1")
    monkeypatch.setenv("VLLM_MODEL_ID", "test-model")
    monkeypatch.setenv("DOCUMENT_PATH", "EU_ai.txt")
    monkeypatch.setenv("GRAPH_CACHE_DIR", "/tmp/test_graph_cache")
    monkeypatch.setenv("EMBEDDING_DEVICE", "cpu")


@pytest.fixture
def mock_driver():
    """Mock Neo4j driver with session support."""
    driver = MagicMock()
    session = MagicMock()
    driver.session.return_value.__enter__ = MagicMock(return_value=session)
    driver.session.return_value.__exit__ = MagicMock(return_value=False)
    return driver, session


@pytest.fixture
def mock_graph():
    """Mock LangChain Neo4jGraph."""
    graph = MagicMock()
    graph.query.return_value = []
    return graph


@pytest.fixture
def sample_documents():
    """Sample Document objects for testing."""
    return [
        _FakeDocument(page_content="Article 1: This regulation establishes rules.", metadata={"source": "test.txt", "page": 1}),
        _FakeDocument(page_content="Article 2: High-risk AI systems shall comply.", metadata={"source": "test.txt", "page": 2}),
        _FakeDocument(page_content="Article 3: Definitions for this regulation.", metadata={"source": "test.txt", "page": 3}),
    ]
