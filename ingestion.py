"""Load extracted graph documents from pickle into Neo4j."""

import pickle
from pathlib import Path
from langchain_community.graphs.graph_document import GraphDocument
import config
import db


def ingest_graphs(pkl_path: Path = None):
    """
    Load graph_all.pkl and push graph documents into Neo4j.

    Resumability: checks if __Entity__ nodes already exist in the DB.
    If nodes exist, skip ingestion.
    """
    if pkl_path is None:
        pkl_path = config.GRAPH_CACHE_DIR / "graph_all.pkl"

    if not pkl_path.exists():
        raise FileNotFoundError(f"Pickle not found: {pkl_path}")

    # ── Resumability checkpoint ──
    graph = db.get_graph()
    existing = graph.query("MATCH (n:`__Entity__`) RETURN count(n) AS c")
    if existing and existing[0]["c"] > 0:
        print(f"[ingestion] {existing[0]['c']} __Entity__ nodes already in DB, skipping.")
        return

    # ── Load pickle ──
    with pkl_path.open("rb") as f:
        graph_documents = pickle.load(f)

    if isinstance(graph_documents, GraphDocument):
        graph_documents = [graph_documents]

    print(f"[ingestion] Loaded {len(graph_documents)} graph documents from {pkl_path}")

    # ── Push to Neo4j ──
    graph.add_graph_documents(
        graph_documents,
        baseEntityLabel=True,
        include_source=True,
    )

    # ── Summary query ──
    summary = graph.query("""
        MATCH (n:`__Entity__`)
        RETURN "node" AS type,
               count(*) AS total_count,
               count(n.description) AS non_null_descriptions
        UNION ALL
        MATCH (n)-[r]->()
        WHERE type(r) <> 'MENTIONS'
        RETURN "relationship" AS type,
               count(*) AS total_count,
               count(r.description) AS non_null_descriptions
    """)
    for row in summary:
        print(
            f"  {row['type']}: {row['total_count']} total, "
            f"{row['non_null_descriptions']} with descriptions"
        )
