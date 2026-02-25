"""Configuration: environment loading, constants, logging setup."""

import os
import sys
import logging
from pathlib import Path
from dotenv import load_dotenv, find_dotenv

load_dotenv(find_dotenv())

# ── Neo4j ──
NEO4J_URI = os.getenv("NEO4J_URI", "neo4j://127.0.0.1:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "")

# ── Google Gemini ──
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", "")

# ── vLLM ──
VLLM_BASE_URL = os.getenv("VLLM_BASE_URL", "http://localhost:8000/v1")
VLLM_MODEL_ID = os.getenv("VLLM_MODEL_ID", "Qwen/Qwen3-14B-AWQ")

# ── Document ──
DOCUMENT_PATH = Path(os.getenv("DOCUMENT_PATH", "EU_ai.txt"))

# ── Chunking ──
CHUNK_SIZE = int(os.getenv("CHUNK_SIZE", "350"))
CHUNK_OVERLAP = int(os.getenv("CHUNK_OVERLAP", "75"))

# ── Processing ──
MAX_WORKERS = int(os.getenv("MAX_WORKERS", "4"))
EXTRACTION_TIMEOUT = int(os.getenv("EXTRACTION_TIMEOUT", "300"))

# ── Cache ──
GRAPH_CACHE_DIR = Path(os.getenv("GRAPH_CACHE_DIR", "./graph_cache_hybrid"))

# ── Embedding ──
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "intfloat/multilingual-e5-large")
EMBEDDING_DEVICE = os.getenv("EMBEDDING_DEVICE", "cuda")
EMBEDDING_CACHE_DIR = Path(os.getenv("EMBEDDING_CACHE_DIR", "./local_transformers")).resolve()

# ── Community detection ──
SIMILARITY_THRESHOLD = float(os.getenv("SIMILARITY_THRESHOLD", "0.95"))
WORD_EDIT_DISTANCE = int(os.getenv("WORD_EDIT_DISTANCE", "3"))

# ── Gemini models ──
GEMINI_EXTRACTION_MODEL = os.getenv("GEMINI_EXTRACTION_MODEL", "gemini-2.5-pro")
GEMINI_RESOLUTION_MODEL = os.getenv("GEMINI_RESOLUTION_MODEL", "gemini-2.5-pro")


def configure_logging():
    """Suppress noisy third-party loggers; only WARNING+ and user prints visible."""
    logging.basicConfig(
        level=logging.WARNING,
        handlers=[logging.StreamHandler(sys.stderr)],
        force=True,
    )
    for name in [
        "neo4j", "neo4j.pool", "neo4j.io",
        "langchain", "langsmith",
        "openai", "httpx", "urllib3",
        "graphdatascience",
    ]:
        logging.getLogger(name).setLevel(logging.ERROR)


def validate():
    """Raise EnvironmentError if required credentials are missing."""
    missing = []
    if not NEO4J_PASSWORD:
        missing.append("NEO4J_PASSWORD")
    if not GOOGLE_API_KEY:
        missing.append("GOOGLE_API_KEY")
    if missing:
        raise EnvironmentError(
            f"Missing required environment variables: {', '.join(missing)}. "
            "Copy .env.example to .env and fill in values."
        )
