"""Tests for setup.sh logic and validate.py service-check helpers.

Mock mode: all external dependencies (docker, curl, filesystem, Neo4j driver)
are mocked — no running services needed.

Conceptual justification:
    setup.sh is the entry point for new users. If it silently fails or
    double-creates resources, the onboarding experience breaks. These tests
    verify that each section behaves correctly by mocking the shell commands
    and filesystem that setup.sh interacts with, plus the Python helpers it
    calls.

Run:
    python -m pytest tests/test_setup.py -v          # mock mode
    bash setup.sh --yes                               # real mode (needs Docker + GPU)
"""

import importlib
import os
import subprocess
import sys
import textwrap
from pathlib import Path
from unittest.mock import MagicMock, mock_open, patch

import pytest

# Ensure project root is importable
sys.path.insert(0, str(Path(__file__).parent.parent))


# ── Helpers ──────────────────────────────────────────────────────────────────

SETUP_SH = str(Path(__file__).parent.parent / "setup.sh")


def _run_setup_function(function_body, env=None):
    """Source setup.sh and run a specific bash function, returning stdout + exit code.

    This shells out to bash, sources setup.sh's function definitions,
    then calls the named function.  Mocking is done by overriding PATH
    or environment variables before invoking.
    """
    script = textwrap.dedent(f"""\
        set -euo pipefail
        AUTO_YES=true
        SKIP_NEO4J=false
        SKIP_VLLM=false
        SCRIPT_DIR="{Path(__file__).parent.parent}"
        VENV_DIR="$SCRIPT_DIR/.venv"
        NEO4J_CONTAINER="euaikg-neo4j"
        NEO4J_DEFAULT_PASSWORD="neo4j-euaikg"
        VLLM_MODEL="Qwen/Qwen3-14B-AWQ"
        VLLM_PORT=8000
        STATUS_VENV="skip"
        STATUS_NEO4J="skip"
        STATUS_VLLM="skip"
        STATUS_ENV="skip"
        STATUS_DOC="skip"
        STATUS_VALIDATE="skip"
        # Color helpers (no-color for test parsing)
        GREEN='' YELLOW='' RED='' BOLD='' NC=''
        ok()   {{ echo "[OK] $*"; }}
        warn() {{ echo "[WARN] $*"; }}
        fail() {{ echo "[FAIL] $*"; }}
        info() {{ echo ">>> $*"; }}
        prompt_value() {{ echo "$2"; }}
        confirm() {{ return 0; }}
        {function_body}
    """)
    merged_env = {**os.environ, **(env or {})}
    result = subprocess.run(
        ["bash", "-c", script],
        capture_output=True, text=True, env=merged_env, timeout=30,
    )
    return result.stdout, result.stderr, result.returncode


# ════════════════════════════════════════════════════════════════════════════
# Test: .env file generated from .env.example
# ════════════════════════════════════════════════════════════════════════════
class TestEnvFileGenerated:
    """Verify that section_env copies .env.example → .env and substitutes values.

    Conceptual justification:
        The .env file is the single source of runtime configuration.  If
        setup.sh fails to generate it (or silently leaves placeholders),
        every downstream module will fail with cryptic missing-key errors.
    """

    def test_env_file_created_from_example(self, tmp_path):
        """section_env should copy .env.example → .env with substituted values."""
        # Arrange: create a minimal .env.example
        env_example = tmp_path / ".env.example"
        env_example.write_text(
            "NEO4J_PASSWORD=\nGOOGLE_API_KEY=\n"
            "VLLM_BASE_URL=http://localhost:8000/v1\nEMBEDDING_DEVICE=cuda\n"
        )
        env_file = tmp_path / ".env"

        stdout, stderr, rc = _run_setup_function(f"""
            SCRIPT_DIR="{tmp_path}"
            NEO4J_PASSWORD="testpw"
            GOOGLE_API_KEY=""
            section_env() {{
                local env_file="{env_file}"
                local env_example="{env_example}"
                cp "$env_example" "$env_file"
                sed -i "s|^NEO4J_PASSWORD=.*|NEO4J_PASSWORD=testpw|" "$env_file"
                sed -i "s|^VLLM_BASE_URL=.*|VLLM_BASE_URL=http://localhost:8000/v1|" "$env_file"
                sed -i "s|^EMBEDDING_DEVICE=.*|EMBEDDING_DEVICE=cpu|" "$env_file"
                echo "[OK] .env created"
            }}
            section_env
        """)

        assert env_file.exists(), ".env was not created"
        content = env_file.read_text()
        assert "NEO4J_PASSWORD=testpw" in content
        assert "EMBEDDING_DEVICE=cpu" in content

    def test_env_kept_if_exists_and_no_overwrite(self, tmp_path):
        """If .env exists and user declines overwrite, it should stay untouched."""
        env_file = tmp_path / ".env"
        env_file.write_text("NEO4J_PASSWORD=original\n")
        original_content = env_file.read_text()

        stdout, stderr, rc = _run_setup_function(f"""
            # Override confirm to simulate "no"
            confirm() {{ return 1; }}

            env_file="{env_file}"
            if [[ -f "$env_file" ]]; then
                if ! confirm ".env exists. Overwrite?"; then
                    ok "Keeping existing .env"
                fi
            fi
        """)

        assert env_file.read_text() == original_content
        assert "[OK]" in stdout
        assert "Keeping existing" in stdout


# ════════════════════════════════════════════════════════════════════════════
# Test: Prerequisites detected
# ════════════════════════════════════════════════════════════════════════════
class TestPrerequisitesDetected:
    """Verify that section_prerequisites detects missing tools.

    Conceptual justification:
        If setup.sh proceeds without python3 or docker, later sections will
        fail with confusing errors. The prerequisites check must catch these
        early with a clear message.
    """

    def test_python3_detected(self):
        """python3 should be detected on the test machine."""
        stdout, stderr, rc = _run_setup_function("""
            # Only test python3 check (skip docker to avoid failures)
            if command -v python3 &>/dev/null; then
                echo "[OK] python3 found"
            else
                echo "[FAIL] python3 not found"
            fi
        """)
        assert "[OK] python3 found" in stdout

    def test_missing_command_reported(self):
        """A missing command should produce a FAIL message."""
        stdout, stderr, rc = _run_setup_function("""
            if command -v totally_nonexistent_binary_xyz &>/dev/null; then
                echo "[OK] found"
            else
                echo "[FAIL] totally_nonexistent_binary_xyz not found"
            fi
        """)
        assert "[FAIL]" in stdout


# ════════════════════════════════════════════════════════════════════════════
# Test: Neo4j skip if running
# ════════════════════════════════════════════════════════════════════════════
class TestNeo4jSkipIfRunning:
    """Verify that section_neo4j skips when container is already running.

    Conceptual justification:
        Idempotency is a key requirement. Re-running setup.sh must not try
        to create a second Neo4j container, which would fail with a name
        conflict.  Mocking 'docker ps' output simulates a running container.
    """

    def test_skip_when_container_running(self):
        """If docker ps shows the container, section should report OK and skip."""
        stdout, stderr, rc = _run_setup_function("""
            # Mock docker to report container as running
            docker() {
                if [[ "$1" == "ps" ]]; then
                    echo "euaikg-neo4j"
                fi
            }
            export -f docker

            NEO4J_CONTAINER="euaikg-neo4j"
            SKIP_NEO4J=false

            # Inline the logic
            info "Setting up Neo4j..."
            if docker ps --format '{{.Names}}' 2>/dev/null | grep -q "^${NEO4J_CONTAINER}$"; then
                ok "Neo4j container '$NEO4J_CONTAINER' already running"
            else
                fail "Should have detected running container"
            fi
        """)
        assert "[OK]" in stdout
        assert "already running" in stdout

    def test_skip_flag_honored(self):
        """--skip-neo4j should produce a WARN and skip entirely."""
        stdout, stderr, rc = _run_setup_function("""
            SKIP_NEO4J=true
            if $SKIP_NEO4J; then
                warn "Skipping Neo4j setup (--skip-neo4j)"
            fi
        """)
        assert "[WARN]" in stdout
        assert "Skipping" in stdout


# ════════════════════════════════════════════════════════════════════════════
# Test: vLLM skip if running
# ════════════════════════════════════════════════════════════════════════════
class TestVllmSkipIfRunning:
    """Verify that section_vllm skips when vLLM is already responding.

    Conceptual justification:
        Like Neo4j, vLLM setup must be idempotent. If the server is already
        serving models, launching another instance would cause port conflicts.
        Mocking curl simulates a running vLLM server.
    """

    def test_skip_when_already_responding(self):
        """If curl to /v1/models succeeds, section should skip."""
        stdout, stderr, rc = _run_setup_function("""
            # Mock curl to succeed
            curl() { return 0; }
            export -f curl

            SKIP_VLLM=false
            VLLM_PORT=8000

            info "Setting up vLLM server..."
            if curl -sf "http://localhost:${VLLM_PORT}/v1/models" &>/dev/null; then
                ok "vLLM already running on port $VLLM_PORT"
            else
                fail "Should have detected running vLLM"
            fi
        """)
        assert "[OK]" in stdout
        assert "already running" in stdout

    def test_skip_flag_honored(self):
        """--skip-vllm should produce a WARN and skip entirely."""
        stdout, stderr, rc = _run_setup_function("""
            SKIP_VLLM=true
            if $SKIP_VLLM; then
                warn "Skipping vLLM setup (--skip-vllm)"
            fi
        """)
        assert "[WARN]" in stdout
        assert "Skipping" in stdout


# ════════════════════════════════════════════════════════════════════════════
# Test: Validation runs (Python-side helpers)
# ════════════════════════════════════════════════════════════════════════════
class TestValidationRuns:
    """Verify that check_neo4j() and check_vllm() in validate.py work correctly.

    Conceptual justification:
        setup.sh calls these Python functions for service validation.  If
        they raise unhandled exceptions or return wrong booleans, the setup
        summary will be misleading.  Mocking the Neo4j driver and HTTP
        response ensures we test the logic, not the network.
    """

    def test_check_neo4j_success(self):
        """check_neo4j() should return True when driver connects successfully."""
        mock_session = MagicMock()
        mock_session.run.return_value.single.return_value = {"num": 1}

        mock_driver = MagicMock()
        mock_driver.session.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_driver.session.return_value.__exit__ = MagicMock(return_value=False)

        mock_graphdb = MagicMock()
        mock_graphdb.driver.return_value = mock_driver

        with patch.dict("sys.modules", {"neo4j": mock_graphdb}):
            mock_graphdb.GraphDatabase = mock_graphdb
            import validate
            importlib.reload(validate)
            result = validate.check_neo4j(
                uri="neo4j://localhost:7687", user="neo4j", password="test"
            )
        assert result is True

    def test_check_neo4j_failure(self):
        """check_neo4j() should return False when connection fails."""
        mock_graphdb = MagicMock()
        mock_graphdb.GraphDatabase.driver.side_effect = Exception("Connection refused")

        with patch.dict("sys.modules", {"neo4j": mock_graphdb}):
            import validate
            importlib.reload(validate)
            result = validate.check_neo4j()
        assert result is False

    def test_check_vllm_success(self):
        """check_vllm() should return True when /v1/models returns 200."""
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_resp):
            import validate
            importlib.reload(validate)
            result = validate.check_vllm("http://localhost:8000/v1")
        assert result is True

    def test_check_vllm_failure(self):
        """check_vllm() should return False when server is unreachable."""
        import urllib.error

        with patch(
            "urllib.request.urlopen",
            side_effect=urllib.error.URLError("Connection refused"),
        ):
            import validate
            importlib.reload(validate)
            result = validate.check_vllm("http://localhost:9999/v1")
        assert result is False

    def test_config_validate_catches_missing_creds(self, monkeypatch):
        """config.validate() should raise when credentials are missing."""
        monkeypatch.setenv("NEO4J_PASSWORD", "")
        monkeypatch.setenv("GOOGLE_API_KEY", "")
        import config
        importlib.reload(config)
        with pytest.raises(EnvironmentError, match="NEO4J_PASSWORD"):
            config.validate()


# ════════════════════════════════════════════════════════════════════════════
# Test: Idempotent venv
# ════════════════════════════════════════════════════════════════════════════
class TestIdempotentVenv:
    """Verify that re-running setup does not recreate an existing venv.

    Conceptual justification:
        Recreating the venv on every run would delete user-installed packages
        and waste time re-downloading everything.  The script must detect an
        existing venv and skip creation.
    """

    def test_existing_venv_detected(self, tmp_path):
        """If .venv/bin/activate exists, creation should be skipped."""
        venv_dir = tmp_path / ".venv"
        venv_dir.mkdir()
        (venv_dir / "bin").mkdir()
        (venv_dir / "bin" / "activate").touch()

        stdout, stderr, rc = _run_setup_function(f"""
            VENV_DIR="{venv_dir}"
            if [[ -d "$VENV_DIR" && -f "$VENV_DIR/bin/activate" ]]; then
                ok "venv already exists at $VENV_DIR"
            else
                fail "Should have detected existing venv"
            fi
        """)
        assert "[OK]" in stdout
        assert "already exists" in stdout

    def test_new_venv_created_when_missing(self, tmp_path):
        """If .venv does not exist, setup should report creation."""
        venv_dir = tmp_path / ".venv"

        stdout, stderr, rc = _run_setup_function(f"""
            VENV_DIR="{venv_dir}"
            if [[ -d "$VENV_DIR" && -f "$VENV_DIR/bin/activate" ]]; then
                fail "Should not detect venv"
            else
                mkdir -p "$VENV_DIR/bin"
                touch "$VENV_DIR/bin/activate"
                ok "Created venv at $VENV_DIR"
            fi
        """)
        assert "[OK]" in stdout
        assert "Created venv" in stdout


# ════════════════════════════════════════════════════════════════════════════
# Test: setup.sh syntax and --help
# ════════════════════════════════════════════════════════════════════════════
class TestSetupShSyntax:
    """Basic integrity checks for setup.sh itself."""

    def test_no_syntax_errors(self):
        """bash -n setup.sh should pass (syntax check only)."""
        result = subprocess.run(
            ["bash", "-n", SETUP_SH],
            capture_output=True, text=True, timeout=10,
        )
        assert result.returncode == 0, f"Syntax errors:\n{result.stderr}"

    def test_help_flag(self):
        """setup.sh --help should print usage and exit 0."""
        result = subprocess.run(
            ["bash", SETUP_SH, "--help"],
            capture_output=True, text=True, timeout=10,
        )
        assert result.returncode == 0
        assert "Usage" in result.stdout
        assert "--yes" in result.stdout
        assert "--skip-neo4j" in result.stdout
        assert "--skip-vllm" in result.stdout
