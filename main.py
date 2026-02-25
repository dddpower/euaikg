"""CLI entrypoint for EU AI Knowledge Graph pipeline.

Prerequisites:
    1. Neo4j running (neo4j://127.0.0.1:7687)
    2. vLLM serving the model (http://localhost:8000/v1)
    3. .env file with credentials (copy from .env.example)

Usage:
    python main.py                         # Full pipeline
    python main.py --no-wipe               # Resume (skip DB wipe, skip completed phases)
    python main.py --phase extract         # Run only extraction
    python main.py --phase serve --port 8080  # Just the visualization server
"""

import argparse
import sys


def parse_args():
    parser = argparse.ArgumentParser(
        description="Build a Knowledge Graph from the EU AI Act"
    )
    parser.add_argument(
        "--phase",
        choices=["all", "extract", "ingest", "community", "serve"],
        default="all",
        help="Run a specific phase or 'all' (default: all)",
    )
    parser.add_argument(
        "--no-serve", action="store_true", help="Skip visualization server"
    )
    parser.add_argument(
        "--no-wipe", action="store_true", help="Skip DB wipe (for resuming)"
    )
    parser.add_argument(
        "--port", type=int, default=5000, help="Visualization server port"
    )
    parser.add_argument(
        "--limit", type=int, default=500, help="Cytoscape query LIMIT"
    )
    parser.add_argument(
        "--host", default="127.0.0.1", help="Visualization server host"
    )
    return parser.parse_args()


def main():
    args = parse_args()

    # Lazy imports so --help is fast
    import config
    config.configure_logging()
    config.validate()

    import db
    import visualization
    from pipeline import run_pipeline_sync

    try:
        # ── Pipeline phases (extract / ingest / community) ──
        if args.phase != "serve":
            phases = []
            if args.phase in ("all", "extract"):
                phases.append("extract")
            if args.phase in ("all", "ingest"):
                phases.append("ingest")
            if args.phase in ("all", "community"):
                phases.append("community")
            if phases:
                run_pipeline_sync(phases=phases, wipe_db=not args.no_wipe)

        # ── Phase: Visualization ──
        if args.phase in ("all", "serve") and not args.no_serve:
            visualization.run_server(
                limit=args.limit, host=args.host, port=args.port
            )

    except KeyboardInterrupt:
        print("\nInterrupted.")
        sys.exit(1)
    finally:
        db.close()


if __name__ == "__main__":
    main()
