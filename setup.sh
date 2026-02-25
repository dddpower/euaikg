#!/usr/bin/env bash
# setup.sh — Full-stack environment setup for euAIKG
#
# Usage:
#   bash setup.sh              # interactive setup
#   bash setup.sh --yes        # non-interactive (accept all defaults)
#   bash setup.sh --skip-neo4j # skip Neo4j Docker step
#   bash setup.sh --skip-vllm  # skip vLLM server step
#   bash setup.sh --help       # show this help
#
# Idempotent: safe to run multiple times.

set -euo pipefail

# ── Globals ──────────────────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="${SCRIPT_DIR}/.venv"
NEO4J_CONTAINER="euaikg-neo4j"
NEO4J_DEFAULT_PASSWORD="neo4j-euaikg"
VLLM_MODEL="Qwen/Qwen3-14B-AWQ"
VLLM_PORT=8000

# Flags
AUTO_YES=false
SKIP_NEO4J=false
SKIP_VLLM=false

# Track status for summary
STATUS_VENV="skip"
STATUS_NEO4J="skip"
STATUS_VLLM="skip"
STATUS_ENV="skip"
STATUS_DOC="skip"
STATUS_VALIDATE="skip"

# ── Color helpers ────────────────────────────────────────────────────────────
if [[ -t 1 ]]; then
    GREEN='\033[0;32m'
    YELLOW='\033[1;33m'
    RED='\033[0;31m'
    BOLD='\033[1m'
    NC='\033[0m'
else
    GREEN='' YELLOW='' RED='' BOLD='' NC=''
fi

ok()   { echo -e "${GREEN}[OK]${NC} $*"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $*"; }
fail() { echo -e "${RED}[FAIL]${NC} $*"; }
info() { echo -e "${BOLD}>>>${NC} $*"; }

# ── Cleanup trap ─────────────────────────────────────────────────────────────
cleanup() {
    local exit_code=$?
    if [[ $exit_code -ne 0 ]]; then
        echo ""
        fail "Setup did not complete successfully (exit code $exit_code)."
        echo "  Fix the issue above and re-run: bash setup.sh"
    fi
}
trap cleanup EXIT

# ── Argument parsing ─────────────────────────────────────────────────────────
usage() {
    cat <<'EOF'
Usage: bash setup.sh [OPTIONS]

Options:
  --yes          Non-interactive mode (accept all defaults)
  --skip-neo4j   Skip Neo4j Docker setup
  --skip-vllm    Skip vLLM server setup
  --help         Show this help message

Examples:
  bash setup.sh                        # interactive
  bash setup.sh --yes                  # CI / automated
  bash setup.sh --skip-vllm --yes      # no GPU available
EOF
    exit 0
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --yes)       AUTO_YES=true; shift ;;
        --skip-neo4j) SKIP_NEO4J=true; shift ;;
        --skip-vllm)  SKIP_VLLM=true; shift ;;
        --help|-h)    usage ;;
        *) fail "Unknown option: $1"; usage ;;
    esac
done

# ── Helper: prompt with default ──────────────────────────────────────────────
prompt_value() {
    local prompt="$1"
    local default="$2"
    if $AUTO_YES; then
        echo "$default"
        return
    fi
    local value
    read -rp "${prompt} [${default}]: " value
    echo "${value:-$default}"
}

# ── Helper: confirm yes/no ───────────────────────────────────────────────────
confirm() {
    local prompt="$1"
    if $AUTO_YES; then
        return 0
    fi
    local answer
    read -rp "${prompt} [Y/n]: " answer
    [[ -z "$answer" || "$answer" =~ ^[Yy] ]]
}

# ════════════════════════════════════════════════════════════════════════════
# Section 1: Prerequisites
# ════════════════════════════════════════════════════════════════════════════
section_prerequisites() {
    info "Checking prerequisites..."
    local missing=0

    # Python 3.9+
    if command -v python3 &>/dev/null; then
        local pyver
        pyver=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
        local pymajor pyminor
        pymajor=$(echo "$pyver" | cut -d. -f1)
        pyminor=$(echo "$pyver" | cut -d. -f2)
        if [[ "$pymajor" -ge 3 && "$pyminor" -ge 9 ]]; then
            ok "python3 $pyver"
        else
            fail "python3 $pyver (need >= 3.9)"
            missing=1
        fi
    else
        fail "python3 not found"
        missing=1
    fi

    # pip
    if python3 -m pip --version &>/dev/null; then
        ok "pip $(python3 -m pip --version | awk '{print $2}')"
    else
        fail "pip not found (python3 -m pip)"
        missing=1
    fi

    # docker
    if command -v docker &>/dev/null; then
        ok "docker $(docker --version | awk '{print $3}' | tr -d ',')"
    else
        if ! $SKIP_NEO4J && ! $SKIP_VLLM; then
            fail "docker not found (needed for Neo4j / vLLM)"
            missing=1
        else
            warn "docker not found (skipped steps won't need it)"
        fi
    fi

    # docker compose
    if docker compose version &>/dev/null 2>&1; then
        ok "docker compose $(docker compose version --short 2>/dev/null || echo 'available')"
    elif command -v docker-compose &>/dev/null; then
        ok "docker-compose (legacy)"
    else
        if ! $SKIP_NEO4J && ! $SKIP_VLLM; then
            warn "docker compose not found (docker run will be used directly)"
        fi
    fi

    # nvidia-smi (optional)
    if command -v nvidia-smi &>/dev/null; then
        local gpu_name
        gpu_name=$(nvidia-smi --query-gpu=name --format=csv,noheader,nounits 2>/dev/null | head -1)
        ok "nvidia-smi: $gpu_name"
    else
        warn "nvidia-smi not found (GPU features will be unavailable)"
    fi

    if [[ $missing -ne 0 ]]; then
        fail "Missing prerequisites. Install them and re-run."
        exit 1
    fi
    echo ""
}

# ════════════════════════════════════════════════════════════════════════════
# Section 2: Python Virtual Environment
# ════════════════════════════════════════════════════════════════════════════
section_venv() {
    info "Setting up Python virtual environment..."

    if [[ -d "$VENV_DIR" && -f "$VENV_DIR/bin/activate" ]]; then
        ok "venv already exists at $VENV_DIR"
    else
        python3 -m venv "$VENV_DIR"
        ok "Created venv at $VENV_DIR"
    fi

    # shellcheck disable=SC1091
    source "$VENV_DIR/bin/activate"

    info "Installing dependencies from requirements.txt..."
    pip install --quiet --upgrade pip
    pip install --quiet -r "$SCRIPT_DIR/requirements.txt"
    ok "Dependencies installed"

    # Verify key imports
    local failed_imports=0
    for mod in torch flask neo4j dotenv; do
        if python3 -c "import $mod" 2>/dev/null; then
            ok "import $mod"
        else
            fail "import $mod failed"
            failed_imports=1
        fi
    done
    if [[ $failed_imports -ne 0 ]]; then
        fail "Some imports failed. Check requirements.txt and re-run."
        exit 1
    fi

    STATUS_VENV="ok"
    echo ""
}

# ════════════════════════════════════════════════════════════════════════════
# Section 3: Neo4j via Docker
# ════════════════════════════════════════════════════════════════════════════
section_neo4j() {
    if $SKIP_NEO4J; then
        warn "Skipping Neo4j setup (--skip-neo4j)"
        echo ""
        return
    fi

    info "Setting up Neo4j..."

    # Check if container already running
    if docker ps --format '{{.Names}}' 2>/dev/null | grep -q "^${NEO4J_CONTAINER}$"; then
        ok "Neo4j container '$NEO4J_CONTAINER' already running"
        STATUS_NEO4J="ok"
        echo ""
        return
    fi

    # Check if container exists but stopped
    if docker ps -a --format '{{.Names}}' 2>/dev/null | grep -q "^${NEO4J_CONTAINER}$"; then
        info "Starting existing Neo4j container..."
        docker start "$NEO4J_CONTAINER" >/dev/null
    else
        # Prompt for password
        NEO4J_PASSWORD=$(prompt_value "Neo4j password" "$NEO4J_DEFAULT_PASSWORD")

        # Create data directory
        mkdir -p "$SCRIPT_DIR/neo4j_data"

        info "Pulling and starting Neo4j container..."
        docker run -d \
            --name "$NEO4J_CONTAINER" \
            --restart unless-stopped \
            -p 7474:7474 \
            -p 7687:7687 \
            -v "$SCRIPT_DIR/neo4j_data:/data" \
            -e NEO4J_AUTH="neo4j/${NEO4J_PASSWORD}" \
            -e 'NEO4J_PLUGINS=["apoc"]' \
            neo4j:5-community >/dev/null
        ok "Neo4j container started"
    fi

    # Wait for Neo4j to be healthy (poll bolt port)
    info "Waiting for Neo4j to be ready..."
    local retries=30
    while [[ $retries -gt 0 ]]; do
        if docker exec "$NEO4J_CONTAINER" bash -c 'echo > /dev/tcp/localhost/7687' 2>/dev/null; then
            ok "Neo4j is ready (bolt://localhost:7687)"
            break
        fi
        retries=$((retries - 1))
        sleep 2
    done

    if [[ $retries -le 0 ]]; then
        fail "Neo4j did not become ready in time"
        STATUS_NEO4J="fail"
        echo ""
        return
    fi

    # Install Graph Data Science plugin (manual download — auto-download is unreliable)
    if docker exec "$NEO4J_CONTAINER" test -f /var/lib/neo4j/plugins/neo4j-graph-data-science-*.jar 2>/dev/null; then
        ok "GDS plugin already installed"
    else
        info "Installing Graph Data Science plugin..."
        local gds_version="2.13.7"
        local gds_url="https://graphdatascience.ninja/neo4j-graph-data-science-${gds_version}.jar"
        local gds_tmp="/tmp/neo4j-graph-data-science-${gds_version}.jar"
        if curl -fSL -o "$gds_tmp" "$gds_url" 2>/dev/null; then
            docker cp "$gds_tmp" "${NEO4J_CONTAINER}:/var/lib/neo4j/plugins/"
            rm -f "$gds_tmp"
            info "Restarting Neo4j to load GDS plugin..."
            docker restart "$NEO4J_CONTAINER" >/dev/null
            # Wait again after restart
            local gds_retries=30
            while [[ $gds_retries -gt 0 ]]; do
                if docker exec "$NEO4J_CONTAINER" bash -c 'echo > /dev/tcp/localhost/7687' 2>/dev/null; then
                    break
                fi
                gds_retries=$((gds_retries - 1))
                sleep 2
            done
            ok "GDS ${gds_version} installed"
        else
            warn "Could not download GDS plugin. Community detection will not work."
            warn "Manual install: download from $gds_url and docker cp into container plugins/"
        fi
    fi

    STATUS_NEO4J="ok"
    echo ""
}

# ════════════════════════════════════════════════════════════════════════════
# Section 4: vLLM Server
# ════════════════════════════════════════════════════════════════════════════
section_vllm() {
    if $SKIP_VLLM; then
        warn "Skipping vLLM setup (--skip-vllm)"
        echo ""
        return
    fi

    info "Setting up vLLM server..."

    # Check if vLLM already running
    if curl -sf "http://localhost:${VLLM_PORT}/v1/models" &>/dev/null; then
        ok "vLLM already running on port $VLLM_PORT"
        STATUS_VLLM="ok"
        echo ""
        return
    fi

    # Check GPU availability
    if ! command -v nvidia-smi &>/dev/null; then
        warn "No GPU detected. vLLM requires a GPU."
        warn "The pipeline will run in Gemini-only mode."
        STATUS_VLLM="skip"
        echo ""
        return
    fi

    # Try pip-based vLLM (preferred — avoids Docker CUDA version mismatches)
    info "Launching vLLM via pip..."
    if pip install --quiet vllm 2>/dev/null; then
        PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True \
        nohup vllm serve "$VLLM_MODEL" \
            --quantization awq_marlin \
            --max-model-len 4096 \
            --max-num-seqs 4 \
            --gpu-memory-utilization 0.70 \
            --enforce-eager \
            --port "$VLLM_PORT" \
            --enable-auto-tool-choice \
            --tool-call-parser hermes \
            > "$SCRIPT_DIR/vllm.log" 2>&1 &
        ok "vLLM launched via pip (PID: $!, log: vllm.log)"
    else
        fail "Could not install vLLM via pip."
        STATUS_VLLM="fail"
        echo ""
        return
    fi

    # Wait for vLLM /v1/models endpoint
    info "Waiting for vLLM to load model (this may take minutes)..."
    local retries=90
    while [[ $retries -gt 0 ]]; do
        if curl -sf "http://localhost:${VLLM_PORT}/v1/models" &>/dev/null; then
            ok "vLLM is ready (http://localhost:${VLLM_PORT}/v1)"
            STATUS_VLLM="ok"
            echo ""
            return
        fi
        # Check if vLLM process died
        if ! jobs -r %% &>/dev/null 2>&1 && ! curl -sf "http://localhost:${VLLM_PORT}/v1/models" &>/dev/null; then
            if [[ -f "$SCRIPT_DIR/vllm.log" ]]; then
                fail "vLLM process exited. Last log lines:"
                tail -5 "$SCRIPT_DIR/vllm.log" | while read -r line; do echo "  $line"; done
            fi
            STATUS_VLLM="fail"
            echo ""
            return
        fi
        retries=$((retries - 1))
        sleep 5
    done
    warn "vLLM did not become ready within timeout. Check logs: tail -50 vllm.log"
    STATUS_VLLM="fail"
    echo ""
}

# ════════════════════════════════════════════════════════════════════════════
# Section 5: .env Generation
# ════════════════════════════════════════════════════════════════════════════
section_env() {
    info "Configuring .env file..."

    local env_file="$SCRIPT_DIR/.env"
    local env_example="$SCRIPT_DIR/.env.example"

    if [[ ! -f "$env_example" ]]; then
        fail ".env.example not found. Cannot generate .env."
        STATUS_ENV="fail"
        echo ""
        return
    fi

    if [[ -f "$env_file" ]]; then
        if ! confirm ".env already exists. Overwrite?"; then
            ok "Keeping existing .env"
            STATUS_ENV="ok"
            echo ""
            return
        fi
    fi

    # Gather values
    local neo4j_pw="${NEO4J_PASSWORD:-}"
    if [[ -z "$neo4j_pw" ]]; then
        neo4j_pw=$(prompt_value "NEO4J_PASSWORD" "$NEO4J_DEFAULT_PASSWORD")
    fi

    local google_key
    if $AUTO_YES; then
        google_key="${GOOGLE_API_KEY:-}"
        if [[ -z "$google_key" ]]; then
            warn "GOOGLE_API_KEY not set. You must edit .env manually."
            google_key=""
        fi
    else
        read -rp "GOOGLE_API_KEY (required): " google_key
    fi

    local vllm_url
    vllm_url=$(prompt_value "VLLM_BASE_URL" "http://localhost:${VLLM_PORT}/v1")

    # Auto-detect embedding device
    local embed_device="cpu"
    if command -v nvidia-smi &>/dev/null; then
        embed_device="cuda"
    fi
    embed_device=$(prompt_value "EMBEDDING_DEVICE" "$embed_device")

    # Copy template and substitute values
    cp "$env_example" "$env_file"
    sed -i "s|^NEO4J_PASSWORD=.*|NEO4J_PASSWORD=${neo4j_pw}|" "$env_file"
    sed -i "s|^GOOGLE_API_KEY=.*|GOOGLE_API_KEY=${google_key}|" "$env_file"
    sed -i "s|^VLLM_BASE_URL=.*|VLLM_BASE_URL=${vllm_url}|" "$env_file"
    sed -i "s|^EMBEDDING_DEVICE=.*|EMBEDDING_DEVICE=${embed_device}|" "$env_file"

    ok ".env created at $env_file"
    STATUS_ENV="ok"
    echo ""
}

# ════════════════════════════════════════════════════════════════════════════
# Section 6: Input Document
# ════════════════════════════════════════════════════════════════════════════
section_document() {
    info "Checking input document..."

    if [[ -f "$SCRIPT_DIR/EU_ai.txt" ]]; then
        ok "EU_ai.txt found"
        STATUS_DOC="ok"
    else
        warn "EU_ai.txt not found in project root."
        warn "Place the EU AI Act text file at: $SCRIPT_DIR/EU_ai.txt"
        STATUS_DOC="missing"
    fi
    echo ""
}

# ════════════════════════════════════════════════════════════════════════════
# Section 7: Validation
# ════════════════════════════════════════════════════════════════════════════
section_validate() {
    info "Running validation checks..."

    # Ensure venv is active
    if [[ -f "$VENV_DIR/bin/activate" ]]; then
        # shellcheck disable=SC1091
        source "$VENV_DIR/bin/activate"
    fi

    # Config validation
    if python3 -c "
import sys; sys.path.insert(0, '$SCRIPT_DIR')
import config; config.configure_logging(); config.validate()
print('[validate] Config OK')
" 2>/dev/null; then
        ok "Config validation passed"
    else
        warn "Config validation failed (missing credentials in .env?)"
    fi

    # Neo4j check
    if ! $SKIP_NEO4J; then
        if python3 -c "
import sys; sys.path.insert(0, '$SCRIPT_DIR')
from validate import check_neo4j; check_neo4j()
" 2>/dev/null; then
            ok "Neo4j connection OK"
        else
            warn "Neo4j connection failed (is the container running?)"
        fi
    fi

    # vLLM check
    if ! $SKIP_VLLM; then
        if curl -sf "http://localhost:${VLLM_PORT}/v1/models" &>/dev/null; then
            ok "vLLM responding on port $VLLM_PORT"
        else
            warn "vLLM not responding (may still be loading, or was skipped)"
        fi
    fi

    STATUS_VALIDATE="ok"
    echo ""
}

# ════════════════════════════════════════════════════════════════════════════
# Section 8: Summary
# ════════════════════════════════════════════════════════════════════════════
section_summary() {
    echo ""
    echo -e "${BOLD}═══════════════════════════════════════════════════${NC}"
    echo -e "${BOLD}  euAIKG Setup Summary${NC}"
    echo -e "${BOLD}═══════════════════════════════════════════════════${NC}"

    _status_icon() {
        case "$1" in
            ok)      echo -e "${GREEN}OK${NC}" ;;
            fail)    echo -e "${RED}FAIL${NC}" ;;
            skip)    echo -e "${YELLOW}SKIP${NC}" ;;
            missing) echo -e "${YELLOW}MISSING${NC}" ;;
            *)       echo -e "${YELLOW}--${NC}" ;;
        esac
    }

    echo -e "  Python venv:   $(_status_icon "$STATUS_VENV")  $VENV_DIR"
    echo -e "  Neo4j:         $(_status_icon "$STATUS_NEO4J")  neo4j://127.0.0.1:7687"
    echo -e "  vLLM:          $(_status_icon "$STATUS_VLLM")  http://localhost:${VLLM_PORT}/v1"
    echo -e "  .env:          $(_status_icon "$STATUS_ENV")"
    echo -e "  EU_ai.txt:     $(_status_icon "$STATUS_DOC")"
    echo -e "  Validation:    $(_status_icon "$STATUS_VALIDATE")"

    echo ""
    echo -e "${BOLD}Next steps:${NC}"
    echo "  source .venv/bin/activate"
    echo "  python main.py                    # full pipeline"
    echo "  python main.py --phase serve      # dashboard only"
    echo ""
}

# ════════════════════════════════════════════════════════════════════════════
# Main
# ════════════════════════════════════════════════════════════════════════════
main() {
    echo ""
    echo -e "${BOLD}euAIKG Full-Stack Setup${NC}"
    echo "─────────────────────────────────────────"
    echo ""

    section_prerequisites
    section_venv
    section_neo4j
    section_vllm
    section_env
    section_document
    section_validate
    section_summary
}

main
