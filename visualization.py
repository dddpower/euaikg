"""Flask visualization server with Cytoscape.js frontend and dashboard API."""

import json
import re
import threading
import time
from pathlib import Path
from queue import Empty

from flask import Flask, Response, jsonify, request, send_from_directory
import db

_TEMPLATE_DIR = Path(__file__).parent / "templates"
_STATIC_DIR = Path(__file__).parent / "static"

# Module-level Flask app so routes are registered at import time
app = Flask(__name__, static_folder=str(_STATIC_DIR))

# Module-level state
_pipeline_status = None  # set when pipeline starts
_pipeline_thread = None
_graph_limit = 500


def _cy_elements_from_neo4j(limit: int = 500):
    """Query Neo4j for merged graph and convert to Cytoscape elements format."""
    driver = db.get_driver()
    nodes = {}
    edges = []
    cypher = f"""
        MATCH (s:__Entity__)-[r]->(t:__Entity__)
        WHERE type(r) <> 'MENTIONS'
        RETURN s, r, t
        LIMIT {int(limit)}
    """
    with driver.session() as session:
        for rec in session.run(cypher):
            s = rec["s"]
            t = rec["t"]
            r = rec["r"]
            sid = str(s.get("id", s.element_id))
            tid = str(t.get("id", t.element_id))
            if sid not in nodes:
                nodes[sid] = {"data": {"id": re.sub(r"\s+", "_", sid), "label": sid}}
            if tid not in nodes:
                nodes[tid] = {"data": {"id": re.sub(r"\s+", "_", tid), "label": tid}}
            edges.append({
                "data": {
                    "source": nodes[sid]["data"]["id"],
                    "target": nodes[tid]["data"]["id"],
                    "label": r.type,
                }
            })
    return list(nodes.values()), edges


# ── Existing routes ──

@app.get("/")
def index():
    """Serve the integrated dashboard (EU AI KG + AIDE Networks)."""
    template_path = _TEMPLATE_DIR / "integrated_dashboard.html"
    return template_path.read_text(encoding="utf-8")


@app.get("/graph")
def graph_viewer():
    """Serve the standalone graph viewer (backwards compat)."""
    template_path = _TEMPLATE_DIR / "graph_viewer.html"
    return template_path.read_text(encoding="utf-8")


@app.get("/network_ui/<path:filename>")
def serve_network_ui(filename):
    """Serve static files for AIDE Networks."""
    return send_from_directory(_STATIC_DIR / "network_ui", filename)


@app.get("/data")
def data():
    """Return cached graph data as Cytoscape JSON."""
    try:
        nodes, edges = _cy_elements_from_neo4j(limit=_graph_limit)
        return jsonify({"nodes": nodes, "edges": edges})
    except Exception:
        return jsonify({"nodes": [], "edges": []})


# ── Dashboard API routes ──

@app.get("/api/status")
def api_status():
    """Return current pipeline status as JSON."""
    if _pipeline_status is None:
        return jsonify({"state": "idle", "current_phase": "",
                        "completed_phases": [], "error": "", "elapsed": 0})
    return jsonify(_pipeline_status.to_dict())


@app.post("/api/pipeline/start")
def api_pipeline_start():
    """Start the pipeline in a background thread."""
    global _pipeline_status, _pipeline_thread
    from pipeline import PipelineStatus, PipelineState, run_pipeline

    # Reject if already running
    if (_pipeline_status is not None
            and _pipeline_status.state == PipelineState.RUNNING):
        return jsonify({"error": "Pipeline is already running"}), 409

    body = request.get_json(silent=True) or {}
    phases = body.get("phases", ["extract", "ingest", "community"])
    wipe_db = body.get("wipe_db", True)

    _pipeline_status = PipelineStatus()
    _pipeline_thread = threading.Thread(
        target=run_pipeline,
        args=(_pipeline_status, phases, wipe_db),
        daemon=True,
    )
    _pipeline_thread.start()

    return jsonify({"status": "started", "phases": phases})


@app.post("/api/pipeline/stop")
def api_pipeline_stop():
    """Request graceful pipeline stop (current phase finishes)."""
    from pipeline import PipelineState

    if (_pipeline_status is None
            or _pipeline_status.state != PipelineState.RUNNING):
        return jsonify({"error": "Pipeline is not running"}), 409

    _pipeline_status.request_stop()
    _pipeline_status.state = PipelineState.STOPPING
    return jsonify({"status": "stop_requested"})


@app.get("/api/pipeline/events")
def api_pipeline_events():
    """SSE stream of log lines and status updates."""
    from pipeline import PipelineState

    def generate():
        if _pipeline_status is None:
            yield "event: status\ndata: {\"state\": \"idle\"}\n\n"
            return

        last_status = None
        while True:
            # Drain log queue
            try:
                line = _pipeline_status.log_queue.get(timeout=0.5)
                if line is None:
                    # End-of-stream sentinel
                    status_json = json.dumps(_pipeline_status.to_dict())
                    yield f"event: status\ndata: {status_json}\n\n"
                    yield "event: done\ndata: {}\n\n"
                    return
                yield f"event: log\ndata: {json.dumps(line)}\n\n"
            except Empty:
                pass

            # Periodic status update
            current = _pipeline_status.to_dict()
            if current != last_status:
                last_status = current
                yield f"event: status\ndata: {json.dumps(current)}\n\n"

            # Stop if pipeline ended and queue is empty
            if (_pipeline_status.state in (PipelineState.FINISHED, PipelineState.FAILED)
                    and _pipeline_status.log_queue.empty()):
                yield f"event: status\ndata: {json.dumps(_pipeline_status.to_dict())}\n\n"
                yield "event: done\ndata: {}\n\n"
                return

    return Response(generate(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache",
                             "X-Accel-Buffering": "no"})


@app.get("/api/data/refresh")
def api_data_refresh():
    """Re-query Neo4j and return fresh graph data."""
    try:
        nodes, edges = _cy_elements_from_neo4j(limit=_graph_limit)
        return jsonify({"nodes": nodes, "edges": edges})
    except Exception as e:
        return jsonify({"nodes": [], "edges": [], "error": str(e)})


def run_server(limit: int = 500, host: str = "127.0.0.1", port: int = 5000):
    """Start Flask visualization server."""
    global _graph_limit
    _graph_limit = limit

    print(
        f"[viz] Server: http://{host}:{port}  "
        f"(SSH tunnel: ssh -L {port}:127.0.0.1:{port} <user>@<server>)"
    )
    app.run(host=host, port=port, debug=False)
