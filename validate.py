"""Validation script for the refactored EU AI KG pipeline.

Usage:
    python validate.py --mock     # Run with mocked dependencies (should be green)
    python validate.py --real     # Run against real Neo4j + vLLM (requires services)
"""

import argparse
import subprocess
import sys
import urllib.request
import urllib.error


def run_mock_tests():
    """Run pytest with all mocked tests — no external services needed."""
    print("=" * 60)
    print("MOCK MODE: Running tests with mocked dependencies")
    print("=" * 60)
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/", "-v", "--tb=short"],
        cwd=str(__import__("pathlib").Path(__file__).parent),
    )
    return result.returncode


def run_real_tests():
    """Run a basic pipeline smoke test against real services."""
    print("=" * 60)
    print("REAL MODE: Testing against live Neo4j + vLLM")
    print("=" * 60)

    try:
        import config
        config.configure_logging()
        config.validate()
        print("[OK] config: loaded and validated")
    except Exception as e:
        print(f"[FAIL] config: {e}")
        return 1

    try:
        import db
        db.test_connection()
        print("[OK] db: Neo4j connection successful")
    except Exception as e:
        print(f"[FAIL] db: {e}")
        return 1

    try:
        from pathlib import Path
        assert config.DOCUMENT_PATH.exists(), f"{config.DOCUMENT_PATH} not found"
        print(f"[OK] document: {config.DOCUMENT_PATH} exists")
    except Exception as e:
        print(f"[FAIL] document: {e}")
        return 1

    try:
        import chunking
        docs = chunking.load_and_chunk()
        assert len(docs) > 0, "No documents produced"
        print(f"[OK] chunking: {len(docs)} documents")
    except Exception as e:
        print(f"[FAIL] chunking: {e}")
        return 1

    try:
        db.close()
        print("[OK] db: closed cleanly")
    except Exception as e:
        print(f"[FAIL] db close: {e}")
        return 1

    print("\n" + "=" * 60)
    print("REAL MODE: All basic checks passed")
    print("=" * 60)
    return 0


def check_neo4j(uri="neo4j://127.0.0.1:7687", user="neo4j", password=""):
    """Check if Neo4j is reachable. Returns True on success, False on failure.

    Callable from setup.sh via:
        python -c "from validate import check_neo4j; check_neo4j()"
    """
    try:
        from neo4j import GraphDatabase
        driver = GraphDatabase.driver(uri, auth=(user, password))
        with driver.session() as session:
            result = session.run("RETURN 1 AS num").single()["num"]
            assert result == 1
        driver.close()
        print(f"[check_neo4j] OK — connected to {uri}")
        return True
    except Exception as e:
        print(f"[check_neo4j] FAIL — {e}")
        return False


def check_vllm(base_url="http://localhost:8000/v1"):
    """Check if vLLM server is responding. Returns True on success, False on failure.

    Callable from setup.sh via:
        python -c "from validate import check_vllm; check_vllm()"
    """
    url = f"{base_url}/models"
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=5) as resp:
            if resp.status == 200:
                print(f"[check_vllm] OK — {url} responding")
                return True
            print(f"[check_vllm] FAIL — status {resp.status}")
            return False
    except (urllib.error.URLError, OSError) as e:
        print(f"[check_vllm] FAIL — {e}")
        return False


def main():
    parser = argparse.ArgumentParser(description="Validate the EU AI KG pipeline")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--mock", action="store_true", help="Run mocked tests (no services needed)")
    group.add_argument("--real", action="store_true", help="Run against real services")
    args = parser.parse_args()

    if args.mock:
        sys.exit(run_mock_tests())
    else:
        sys.exit(run_real_tests())


if __name__ == "__main__":
    main()
