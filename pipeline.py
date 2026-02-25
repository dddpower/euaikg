"""Pipeline orchestration for euAIKG.

Provides threaded pipeline execution with stdout capture (QueueWriter)
and graceful stop support. Used by both CLI (run_pipeline_sync) and
web dashboard (run_pipeline + background thread).
"""

import io
import sys
import time
import threading
from enum import Enum
from dataclasses import dataclass, field
from queue import Queue

import db
import chunking
import extraction
import ingestion
import community


class PipelineState(Enum):
    IDLE = "idle"
    RUNNING = "running"
    STOPPING = "stopping"
    FINISHED = "finished"
    FAILED = "failed"


@dataclass
class PipelineStatus:
    """Mutable pipeline state shared between Flask thread and worker thread."""
    state: PipelineState = PipelineState.IDLE
    current_phase: str = ""
    completed_phases: list = field(default_factory=list)
    error: str = ""
    started_at: float = 0.0
    log_queue: Queue = field(default_factory=Queue)
    _stop_event: threading.Event = field(default_factory=threading.Event)

    def request_stop(self):
        self._stop_event.set()

    def should_stop(self) -> bool:
        return self._stop_event.is_set()

    def to_dict(self) -> dict:
        elapsed = 0.0
        if self.started_at > 0:
            elapsed = time.time() - self.started_at
        return {
            "state": self.state.value,
            "current_phase": self.current_phase,
            "completed_phases": list(self.completed_phases),
            "error": self.error,
            "elapsed": round(elapsed, 1),
        }


class QueueWriter(io.TextIOBase):
    """Wraps real stdout and copies every line into a Queue for SSE streaming."""

    def __init__(self, real_stdout, log_queue: Queue):
        super().__init__()
        self._real = real_stdout
        self._queue = log_queue

    def write(self, text: str) -> int:
        if text and text.strip():
            self._queue.put(text.rstrip("\n"))
        return self._real.write(text)

    def flush(self):
        return self._real.flush()

    def fileno(self):
        return self._real.fileno()


def _run_phase(phase_name: str, func, status: PipelineStatus, *args):
    """Execute a single phase, updating status before and after."""
    status.current_phase = phase_name
    func(*args)
    status.completed_phases.append(phase_name)
    status.current_phase = ""


def run_pipeline(status: PipelineStatus, phases: list[str], wipe_db: bool = True):
    """Run pipeline phases in a background thread with stdout capture.

    Args:
        status: Shared PipelineStatus instance for progress tracking.
        phases: List of phase names to run (from: extract, ingest, community).
        wipe_db: Whether to wipe Neo4j before starting.
    """
    real_stdout = sys.stdout
    writer = QueueWriter(real_stdout, status.log_queue)
    sys.stdout = writer

    try:
        status.state = PipelineState.RUNNING
        status.started_at = time.time()

        # DB setup
        db.test_connection()
        if wipe_db:
            db.wipe_database()

        # Extract
        if "extract" in phases:
            if status.should_stop():
                status.state = PipelineState.FINISHED
                return
            documents = chunking.load_and_chunk()
            _run_phase("extract", extraction.extract_graphs, status, documents)

        # Ingest
        if "ingest" in phases:
            if status.should_stop():
                status.state = PipelineState.FINISHED
                return
            _run_phase("ingest", ingestion.ingest_graphs, status)

        # Community
        if "community" in phases:
            if status.should_stop():
                status.state = PipelineState.FINISHED
                return
            _run_phase("community", community.resolve_and_merge, status)

        status.state = PipelineState.FINISHED

    except Exception as e:
        status.state = PipelineState.FAILED
        status.error = str(e)
        print(f"[pipeline] ERROR: {e}")
    finally:
        sys.stdout = real_stdout
        # Signal end-of-stream to SSE consumers
        status.log_queue.put(None)


def run_pipeline_sync(phases: list[str], wipe_db: bool = True):
    """Blocking pipeline run for CLI use (no threading, no queue capture).

    Args:
        phases: List of phase names to run (from: extract, ingest, community).
        wipe_db: Whether to wipe Neo4j before starting.
    """
    db.test_connection()
    if wipe_db:
        db.wipe_database()

    if "extract" in phases:
        documents = chunking.load_and_chunk()
        extraction.extract_graphs(documents)

    if "ingest" in phases:
        ingestion.ingest_graphs()

    if "community" in phases:
        community.resolve_and_merge()
