"""Neo4j driver lifecycle, connection helpers, and graph utilities."""

from neo4j import GraphDatabase
from langchain_neo4j import Neo4jGraph
import config

_driver = None
_graph = None


def get_driver():
    """Return a singleton Neo4j driver, creating it on first call."""
    global _driver
    if _driver is None:
        _driver = GraphDatabase.driver(
            config.NEO4J_URI, auth=(config.NEO4J_USER, config.NEO4J_PASSWORD)
        )
    return _driver


def get_graph():
    """Return a singleton LangChain Neo4jGraph wrapper."""
    global _graph
    if _graph is None:
        _graph = Neo4jGraph(config.NEO4J_URI, config.NEO4J_USER, config.NEO4J_PASSWORD)
    return _graph


def test_connection():
    """Verify Neo4j is reachable."""
    driver = get_driver()
    with driver.session() as session:
        result = session.execute_read(
            lambda tx: tx.run("RETURN 1 AS num").single()["num"]
        )
        print(f"[db] Neo4j connection OK: {result}")


def wipe_database():
    """Delete all nodes and relationships."""
    driver = get_driver()
    with driver.session() as session:
        session.run("MATCH (n) DETACH DELETE n")
    print("[db] Database wiped.")


def refresh_schema():
    """Refresh the LangChain Neo4jGraph schema cache."""
    try:
        get_graph().refresh_schema()
    except Exception:
        pass
    driver = get_driver()
    with driver.session() as s:
        s.run("RETURN 1")


def count_connected_nodes():
    """Print the number of connected __Entity__ nodes (excluding MENTIONS)."""
    graph = get_graph()
    res = graph.query("""
        MATCH (n:`__Entity__`)
        WHERE EXISTS { MATCH (n)-[r]-() WHERE type(r) <> 'MENTIONS' }
        RETURN count(n) AS nodes
    """)
    print(f"[db] Connected nodes (excl. MENTIONS): {res[0]['nodes']:,}")


def close():
    """Close the Neo4j driver and reset singletons."""
    global _driver, _graph
    if _driver:
        _driver.close()
        _driver = None
    _graph = None
