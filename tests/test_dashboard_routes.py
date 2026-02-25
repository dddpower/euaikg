"""Tests for dashboard API routes in visualization.py.

Conceptual justification:
    The dashboard adds 5 API routes to Flask. These tests verify the HTTP
    contracts that the frontend depends on:
    1. /api/status returns idle when no pipeline has been started.
    2. /api/pipeline/start creates a background thread and returns 200.
    3. Double-start is rejected with 409.
    4. /api/pipeline/stop sets the stop event and returns 200.
    5. /api/pipeline/events streams SSE log and status events.
    6. /api/data/refresh returns graph JSON.
    All pipeline execution and Neo4j access is mocked.
"""

import json
import sys
import importlib
from unittest.mock import patch, MagicMock

import pytest

# Restore real flask before importing visualization so routes are real.
# conftest.py stubs it with a MagicMock module, but we need the real Flask
# test client for HTTP route testing.
for _key in list(sys.modules):
    if _key == "flask" or _key.startswith("flask."):
        del sys.modules[_key]
import flask  # noqa: E402 — real import after stub removal

# Also need to reload visualization so it picks up real Flask
for _key in list(sys.modules):
    if _key == "visualization":
        del sys.modules[_key]


@pytest.fixture
def client():
    """Create a Flask test client with mocked pipeline and db."""
    import visualization
    visualization = importlib.reload(visualization)

    # Reset module state
    visualization._pipeline_status = None
    visualization._pipeline_thread = None

    visualization.app.config["TESTING"] = True
    with visualization.app.test_client() as c:
        yield c


class TestApiStatus:
    """GET /api/status should return pipeline state."""

    def test_idle_when_no_pipeline(self, client):
        # Before any pipeline start, status should be idle.
        resp = client.get("/api/status")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["state"] == "idle"
        assert data["completed_phases"] == []
        assert data["elapsed"] == 0


class TestApiPipelineStart:
    """POST /api/pipeline/start should launch a background thread."""

    @patch("pipeline.run_pipeline")
    def test_start_returns_200(self, mock_run, client):
        # Starting the pipeline should return success with selected phases.
        resp = client.post(
            "/api/pipeline/start",
            json={"phases": ["extract", "ingest"], "wipe_db": False},
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "started"
        assert data["phases"] == ["extract", "ingest"]

    @patch("pipeline.run_pipeline")
    def test_double_start_rejected(self, mock_run, client):
        # Starting while already running should return 409.
        resp1 = client.post(
            "/api/pipeline/start",
            json={"phases": ["extract"]},
        )
        assert resp1.status_code == 200

        # Force state to RUNNING (the mock thread won't actually set it)
        import visualization
        from pipeline import PipelineState
        visualization._pipeline_status.state = PipelineState.RUNNING

        resp2 = client.post(
            "/api/pipeline/start",
            json={"phases": ["extract"]},
        )
        assert resp2.status_code == 409
        assert "already running" in resp2.get_json()["error"]

    @patch("pipeline.run_pipeline")
    def test_default_phases(self, mock_run, client):
        # Without specifying phases, all three should be used.
        resp = client.post("/api/pipeline/start", json={})
        data = resp.get_json()
        assert data["phases"] == ["extract", "ingest", "community"]


class TestApiPipelineStop:
    """POST /api/pipeline/stop should set the stop event."""

    @patch("pipeline.run_pipeline")
    def test_stop_when_running(self, mock_run, client):
        # Stop should succeed when pipeline is running.
        client.post("/api/pipeline/start", json={"phases": ["extract"]})

        import visualization
        from pipeline import PipelineState
        visualization._pipeline_status.state = PipelineState.RUNNING

        resp = client.post("/api/pipeline/stop")
        assert resp.status_code == 200
        assert resp.get_json()["status"] == "stop_requested"
        assert visualization._pipeline_status.should_stop()

    def test_stop_when_idle(self, client):
        # Stop when not running should return 409.
        resp = client.post("/api/pipeline/stop")
        assert resp.status_code == 409


class TestApiPipelineEvents:
    """GET /api/pipeline/events should stream SSE."""

    def test_sse_idle(self, client):
        # When idle, SSE should return a status event and close.
        resp = client.get("/api/pipeline/events")
        assert resp.status_code == 200
        assert resp.content_type.startswith("text/event-stream")

        text = resp.get_data(as_text=True)
        assert "event: status" in text
        assert '"idle"' in text

    @patch("pipeline.run_pipeline")
    def test_sse_streams_log_and_done(self, mock_run, client):
        # SSE should emit log events from the queue, then done.
        from pipeline import PipelineState

        client.post("/api/pipeline/start", json={"phases": ["extract"]})

        import visualization
        status = visualization._pipeline_status
        # Simulate pipeline producing output
        status.state = PipelineState.RUNNING
        status.log_queue.put("[extract] Processing chunk 1")
        status.log_queue.put("[extract] Done")
        status.log_queue.put(None)  # end sentinel

        resp = client.get("/api/pipeline/events")
        text = resp.get_data(as_text=True)

        assert "event: log" in text
        assert "Processing chunk 1" in text
        assert "event: done" in text


class TestApiDataRefresh:
    """GET /api/data/refresh should return graph data."""

    @patch("visualization._cy_elements_from_neo4j")
    def test_refresh_returns_data(self, mock_cy, client):
        # Should return nodes and edges from Neo4j.
        mock_cy.return_value = (
            [{"data": {"id": "n1", "label": "Test"}}],
            [{"data": {"source": "n1", "target": "n1", "label": "SELF"}}],
        )
        resp = client.get("/api/data/refresh")
        assert resp.status_code == 200
        data = resp.get_json()
        assert len(data["nodes"]) == 1
        assert len(data["edges"]) == 1

    @patch("visualization._cy_elements_from_neo4j", side_effect=Exception("Neo4j down"))
    def test_refresh_handles_error(self, mock_cy, client):
        # On error, should return empty arrays with error message.
        resp = client.get("/api/data/refresh")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["nodes"] == []
        assert "error" in data


class TestExistingRoutes:
    """Existing routes should still work."""

    def test_dashboard_serves_html(self, client):
        resp = client.get("/")
        assert resp.status_code == 200
        assert b"euAIKG Dashboard" in resp.data

    def test_graph_viewer_backwards_compat(self, client):
        resp = client.get("/graph")
        assert resp.status_code == 200
        assert b"Graph Viewer" in resp.data

    @patch("visualization._cy_elements_from_neo4j")
    def test_data_endpoint(self, mock_cy, client):
        mock_cy.return_value = ([], [])
        resp = client.get("/data")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "nodes" in data
        assert "edges" in data
