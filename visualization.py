"""Flask visualization server with Cytoscape.js frontend."""

import re
from pathlib import Path
from flask import Flask, jsonify
import db

_TEMPLATE_DIR = Path(__file__).parent / "templates"


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


def run_server(limit: int = 500, host: str = "127.0.0.1", port: int = 5000):
    """Start Flask visualization server."""
    app = Flask(__name__)
    nodes_cache, edges_cache = _cy_elements_from_neo4j(limit=limit)

    @app.get("/data")
    def data():
        return jsonify({"nodes": nodes_cache, "edges": edges_cache})

    @app.get("/")
    def index():
        template_path = _TEMPLATE_DIR / "graph_viewer.html"
        return template_path.read_text(encoding="utf-8")

    print(
        f"[viz] Server: http://{host}:{port}  "
        f"(SSH tunnel: ssh -L {port}:127.0.0.1:{port} <user>@<server>)"
    )
    app.run(host=host, port=port, debug=False)
