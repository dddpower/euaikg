# euAIKG — EU AI Act Knowledge Graph

## Project Overview

**euAIKG** is an automated knowledge graph construction pipeline that transforms the EU AI Act legal text into a queryable Neo4j graph database with an interactive visualization dashboard.

The dashboard integrates two visualization modes:
1. **EU AI KG** — Interactive Cytoscape.js graph viewer for the EU AI Act knowledge graph
2. **AIDE Networks** — AIDE relationship networks (GDP variables, global industry, case-law references, trade-CO2, Pacific trade)

### Architecture

```
EU_ai.txt (input document)
    │
    ▼
┌─────────────┐
│  Chunking   │  Token-aware splitting using Qwen3 tokenizer
└──────┬──────┘
       │
       ▼
┌─────────────┐
│  Extraction │  vLLM (Qwen3-14B-AWQ) primary + Gemini fallback
└──────┬──────┘
       │
       ▼
┌─────────────┐
│  Ingestion  │  Pickle → Neo4j graph documents via LangChain
└──────┬──────┘
       │
       ▼
┌─────────────┐
│  Community  │  Embedding → KNN + WCC → Entity resolution → APOC merge
└──────┬──────┘
       │
       ▼
┌─────────────┐
│Visualization│  Flask + Cytoscape.js dashboard
└─────────────┘
```

### Key Design Decisions

- **Dual-LLM extraction**: Local vLLM for throughput, Gemini API as fallback for robustness
- **Resumability**: Each phase checks for prior completion and skips if already done (`--no-wipe` to resume)
- **Token-aware chunking**: Uses the actual Qwen3 tokenizer for accurate chunk boundaries
- **Threaded pipeline execution**: Background execution with SSE log streaming for web dashboard

## Building and Running

### Prerequisites

- Python 3.9+
- Docker (for Neo4j)
- NVIDIA GPU (for vLLM; CPU fallback available for embeddings)
- Google Gemini API key

### Quick Start

```bash
# Automated setup (Neo4j, vLLM, venv, .env)
bash setup.sh

# Or manual setup:
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # Fill in NEO4J_PASSWORD and GOOGLE_API_KEY
```

### Start Infrastructure

```bash
# Neo4j (with APOC plugin)
docker run -d --name euaikg-neo4j \
  -p 7474:7474 -p 7687:7687 \
  -e NEO4J_AUTH=neo4j/your-password \
  -e 'NEO4J_PLUGINS=["apoc"]' \
  neo4j:5-community

# vLLM (requires GPU)
vllm serve Qwen/Qwen3-14B-AWQ \
  --quantization awq_marlin \
  --max-model-len 4096 \
  --port 8000 \
  --enable-auto-tool-choice \
  --tool-call-parser hermes
```

### Run the Pipeline

```bash
# Full pipeline (extract → ingest → community → serve)
python main.py

# Resume without wiping DB
python main.py --no-wipe

# Run specific phase
python main.py --phase extract
python main.py --phase ingest
python main.py --phase community

# Dashboard only
python main.py --phase serve --port 8080

# Skip visualization
python main.py --no-serve
```

### CLI Options

| Option | Default | Description |
|--------|---------|-------------|
| `--phase` | `all` | Run a specific phase: `extract`, `ingest`, `community`, `serve` |
| `--no-wipe` | off | Skip DB wipe (resume from previous run) |
| `--no-serve` | off | Skip visualization server |
| `--port` | `5000` | Visualization server port |
| `--host` | `127.0.0.1` | Visualization server host |
| `--limit` | `500` | Cytoscape graph query LIMIT |

## Project Structure

```
euAIKG/
├── main.py              # CLI entrypoint
├── pipeline.py          # Pipeline orchestration (sync + threaded with SSE)
├── config.py            # Environment config loading and validation
├── db.py                # Neo4j driver lifecycle and helpers
├── chunking.py          # Token-aware text splitting (Qwen3 tokenizer)
├── extraction.py        # vLLM + Gemini graph extraction
├── ingestion.py         # Pickle → Neo4j ingestion
├── community.py         # Embedding, KNN+WCC, entity resolution
├── visualization.py     # Flask server + dashboard API (integrated)
├── validate.py          # Mock/real validation script
├── setup.sh             # Automated environment setup
├── templates/
│   ├── dashboard.html          # Original dashboard
│   ├── graph_viewer.html       # Standalone graph viewer
│   └── integrated_dashboard.html  # NEW: Integrated EU AI KG + AIDE Networks
├── static/
│   ├── lib/vis-9.1.2/          # vis-network library
│   └── network_ui/             # AIDE Networks static assets
│       ├── aide_data.js        # AIDE Networks configuration
│       ├── graph_ui.html       # Interactive case law network
│       ├── outputs_nsga/       # NSGA visualization outputs
│       └── *.png               # Network visualization images
├── network_ui/          # Original offline AIDE network visualization
├── tests/               # pytest test suite
├── requirements.txt     # Python dependencies
├── .env.example         # Environment template
└── EU_ai.txt            # Input document (not tracked in git)
```

## Configuration

All settings are configured via `.env` (see `.env.example`):

| Variable | Default | Description |
|----------|---------|-------------|
| `NEO4J_URI` | `neo4j://127.0.0.1:7687` | Neo4j Bolt URI |
| `NEO4J_USER` | `neo4j` | Neo4j username |
| `NEO4J_PASSWORD` | (required) | Neo4j password |
| `GOOGLE_API_KEY` | (required) | Google Gemini API key |
| `VLLM_BASE_URL` | `http://localhost:8000/v1` | vLLM OpenAI-compatible endpoint |
| `VLLM_MODEL_ID` | `Qwen/Qwen3-14B-AWQ` | Model served by vLLM |
| `DOCUMENT_PATH` | `EU_ai.txt` | Input document path |
| `CHUNK_SIZE` | `350` | Tokens per chunk |
| `CHUNK_OVERLAP` | `75` | Token overlap between chunks |
| `MAX_WORKERS` | `4` | Concurrent extraction threads |
| `EXTRACTION_TIMEOUT` | `300` | Per-chunk timeout (seconds) |
| `EMBEDDING_MODEL` | `intfloat/multilingual-e5-large` | HuggingFace embedding model |
| `EMBEDDING_DEVICE` | `cuda` | Embedding compute device |
| `SIMILARITY_THRESHOLD` | `0.95` | KNN similarity cutoff for communities |
| `WORD_EDIT_DISTANCE` | `3` | Text distance threshold for duplicate candidates |
| `GEMINI_EXTRACTION_MODEL` | `gemini-2.5-pro` | Gemini model for extraction fallback |
| `GEMINI_RESOLUTION_MODEL` | `gemini-2.5-pro` | Gemini model for entity resolution |

## Testing

```bash
# Mock tests (no external services needed)
python validate.py --mock

# Real integration tests (requires Neo4j + vLLM running)
python validate.py --real

# pytest directly
pytest tests/ -v
```

### Test Structure

- `conftest.py` — Shared fixtures and mocks for third-party dependencies
- `test_chunking.py` — Token counting and document splitting
- `test_extraction.py` — vLLM/Gemini graph extraction
- `test_ingestion.py` — Neo4j graph document ingestion
- `test_community.py` — Embedding and community detection
- `test_visualization.py` — Flask routes and API endpoints
- `test_dashboard_routes.py` — Dashboard-specific API routes
- `test_pipeline.py` — Pipeline orchestration and state management
- `test_db.py` — Neo4j driver and connection helpers
- `test_config.py` — Environment variable loading and validation
- `test_setup.py` — Setup script validation

## Tech Stack

| Component | Technology |
|-----------|------------|
| **LLM Extraction** | vLLM + Qwen3-14B-AWQ |
| **Fallback/Resolution** | Google Gemini API |
| **Graph Database** | Neo4j Community + APOC + GDS |
| **Framework** | LangChain (graph transformers, embeddings, Neo4j) |
| **Embeddings** | intfloat/multilingual-e5-large |
| **Community Detection** | Neo4j GDS (KNN + WCC) |
| **Visualization** | Flask + Cytoscape.js |
| **Testing** | pytest |

## Development Conventions

- **Type hints**: Used throughout for function signatures
- **Docstrings**: Google-style docstrings for modules and public functions
- **Logging**: Suppressed third-party noise; only WARNING+ visible
- **Error handling**: Graceful fallbacks (vLLM → Gemini) with timeout handling
- **Resumability**: Pipeline phases check for prior completion before running

## Dashboard Features

The integrated web dashboard (default `http://localhost:5000`) provides:

### Tab 1: EU AI KG
- **Interactive graph viewer** — Cytoscape.js with pan/zoom and node labels
- **Layout controls** — cose, concentric, breadthfirst, grid, circle layouts
- **Pipeline controls** — Start/stop pipeline from the browser
- **SSE log stream** — Real-time pipeline output
- **Status panel** — Current phase, elapsed time, completed phases

### Tab 2: AIDE Networks
Five pre-built network visualizations:
1. **GDP Variables** — GDP 관련 변수 관계 네트워크 (image)
2. **Global Industry** — 2022 글로벌 산업 관계 네트워크 (image)
3. **Case Law** — 판례간 참조 관계 네트워크 (interactive vis-network)
4. **Trade-CO2** — GDP 상위 20 개국 글로벌 무역 - 탄소 네트워크 (image)
5. **Pacific Trade** — 태평양 연안 국가 중심 교역 네트워크 (image)

For remote servers, use SSH tunneling:
```bash
ssh -L 5000:127.0.0.1:5000 user@server
```

### Static Assets

AIDE Networks assets are served from `/static/network_ui/`:
- `lib/vis-9.1.2/` — vis-network library
- `outputs_nsga/` — NSGA visualization outputs
- `graph_ui.html` — Interactive case law network viewer
- `aide_data.js` — AIDE Networks configuration

### Legacy Offline UI

The standalone `network_ui/` folder still works independently:
```bash
xdg-open network_ui/network_ui.html
```

## Pipeline State Machine

```
IDLE → RUNNING → FINISHED
              ↘
               FAILED

STOPPING (graceful stop requested)
```

The `PipelineStatus` dataclass tracks:
- `state`: Current state (IDLE, RUNNING, STOPPING, FINISHED, FAILED)
- `current_phase`: Active phase name
- `completed_phases`: List of completed phase names
- `error`: Error message if FAILED
- `elapsed`: Elapsed time in seconds
- `log_queue`: Queue for SSE log streaming
