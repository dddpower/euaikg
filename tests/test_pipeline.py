"""Tests for pipeline.py.

Conceptual justification:
    The pipeline module extracts phase orchestration out of main.py so it can
    be driven by both the CLI (blocking) and the web dashboard (threaded + SSE).
    These tests verify:
    1. QueueWriter: stdout capture goes into the queue AND the real stdout.
    2. PipelineStatus: stop event, to_dict serialisation, state transitions.
    3. run_pipeline: phases execute in declared order, stop between phases works,
       errors set FAILED state, stdout is captured via QueueWriter.
    4. run_pipeline_sync: blocking wrapper calls modules in order.
    All heavy modules (db, chunking, extraction, ingestion, community) are mocked.
"""

import io
import sys
import time
import threading
from queue import Queue, Empty
from unittest.mock import patch, MagicMock, call

import pipeline
from pipeline import (
    PipelineState,
    PipelineStatus,
    QueueWriter,
    run_pipeline,
    run_pipeline_sync,
)


# ── QueueWriter tests ──

class TestQueueWriter:
    """QueueWriter should copy lines into the queue while passing through to real stdout."""

    def test_write_pushes_to_queue(self):
        # Lines written to QueueWriter should appear in the queue.
        q = Queue()
        real = io.StringIO()
        writer = QueueWriter(real, q)

        writer.write("[extract] Starting vLLM\n")

        assert q.get_nowait() == "[extract] Starting vLLM"
        assert "[extract] Starting vLLM\n" in real.getvalue()

    def test_write_passes_through_to_real(self):
        # Real stdout should receive the same text.
        q = Queue()
        real = io.StringIO()
        writer = QueueWriter(real, q)

        writer.write("hello world\n")

        assert real.getvalue() == "hello world\n"

    def test_blank_lines_are_skipped(self):
        # Empty or whitespace-only writes should not enqueue.
        q = Queue()
        real = io.StringIO()
        writer = QueueWriter(real, q)

        writer.write("")
        writer.write("   \n")

        assert q.empty()

    def test_flush_delegates(self):
        # flush() should call the real stdout's flush.
        real = MagicMock()
        writer = QueueWriter(real, Queue())
        writer.flush()
        real.flush.assert_called_once()


# ── PipelineStatus tests ──

class TestPipelineStatus:
    """PipelineStatus should track state and support stop signalling."""

    def test_initial_state_is_idle(self):
        status = PipelineStatus()
        assert status.state == PipelineState.IDLE

    def test_stop_event(self):
        # request_stop sets the event; should_stop returns True.
        status = PipelineStatus()
        assert not status.should_stop()
        status.request_stop()
        assert status.should_stop()

    def test_to_dict_serialisation(self):
        # to_dict should return a plain dict with expected keys.
        status = PipelineStatus()
        status.state = PipelineState.RUNNING
        status.current_phase = "extract"
        status.completed_phases.append("ingest")
        status.started_at = time.time() - 10

        d = status.to_dict()
        assert d["state"] == "running"
        assert d["current_phase"] == "extract"
        assert "ingest" in d["completed_phases"]
        assert d["elapsed"] >= 9  # at least ~10 seconds

    def test_to_dict_zero_elapsed_when_not_started(self):
        status = PipelineStatus()
        d = status.to_dict()
        assert d["elapsed"] == 0.0


# ── run_pipeline tests ──

class TestRunPipeline:
    """run_pipeline should run phases in order and capture stdout."""

    @patch("pipeline.community")
    @patch("pipeline.ingestion")
    @patch("pipeline.extraction")
    @patch("pipeline.chunking")
    @patch("pipeline.db")
    def test_all_phases_run_in_order(self, mock_db, mock_chunk, mock_ext, mock_ing, mock_com):
        # All three phases should be called in extract -> ingest -> community order.
        mock_chunk.load_and_chunk.return_value = ["doc1"]
        status = PipelineStatus()

        run_pipeline(status, phases=["extract", "ingest", "community"], wipe_db=False)

        mock_db.test_connection.assert_called_once()
        mock_chunk.load_and_chunk.assert_called_once()
        mock_ext.extract_graphs.assert_called_once_with(["doc1"])
        mock_ing.ingest_graphs.assert_called_once()
        mock_com.resolve_and_merge.assert_called_once()
        assert status.state == PipelineState.FINISHED
        assert status.completed_phases == ["extract", "ingest", "community"]

    @patch("pipeline.community")
    @patch("pipeline.ingestion")
    @patch("pipeline.extraction")
    @patch("pipeline.chunking")
    @patch("pipeline.db")
    def test_single_phase(self, mock_db, mock_chunk, mock_ext, mock_ing, mock_com):
        # Running only 'ingest' should skip extract and community.
        status = PipelineStatus()

        run_pipeline(status, phases=["ingest"], wipe_db=False)

        mock_chunk.load_and_chunk.assert_not_called()
        mock_ext.extract_graphs.assert_not_called()
        mock_ing.ingest_graphs.assert_called_once()
        mock_com.resolve_and_merge.assert_not_called()
        assert status.completed_phases == ["ingest"]

    @patch("pipeline.community")
    @patch("pipeline.ingestion")
    @patch("pipeline.extraction")
    @patch("pipeline.chunking")
    @patch("pipeline.db")
    def test_stop_between_phases(self, mock_db, mock_chunk, mock_ext, mock_ing, mock_com):
        # If stop is requested before ingest, ingest and community should not run.
        mock_chunk.load_and_chunk.return_value = ["doc1"]
        status = PipelineStatus()

        # Stop after extract completes
        def stop_after_extract(docs):
            status.request_stop()
        mock_ext.extract_graphs.side_effect = stop_after_extract

        run_pipeline(status, phases=["extract", "ingest", "community"], wipe_db=False)

        mock_ext.extract_graphs.assert_called_once()
        mock_ing.ingest_graphs.assert_not_called()
        mock_com.resolve_and_merge.assert_not_called()
        assert status.state == PipelineState.FINISHED

    @patch("pipeline.community")
    @patch("pipeline.ingestion")
    @patch("pipeline.extraction")
    @patch("pipeline.chunking")
    @patch("pipeline.db")
    def test_error_sets_failed(self, mock_db, mock_chunk, mock_ext, mock_ing, mock_com):
        # An exception in a phase should set state to FAILED with error message.
        mock_chunk.load_and_chunk.return_value = ["doc1"]
        mock_ext.extract_graphs.side_effect = RuntimeError("vLLM crashed")
        status = PipelineStatus()

        run_pipeline(status, phases=["extract"], wipe_db=False)

        assert status.state == PipelineState.FAILED
        assert "vLLM crashed" in status.error

    @patch("pipeline.community")
    @patch("pipeline.ingestion")
    @patch("pipeline.extraction")
    @patch("pipeline.chunking")
    @patch("pipeline.db")
    def test_wipe_db_called(self, mock_db, mock_chunk, mock_ext, mock_ing, mock_com):
        # wipe_db=True should call db.wipe_database().
        status = PipelineStatus()
        run_pipeline(status, phases=[], wipe_db=True)
        mock_db.wipe_database.assert_called_once()

    @patch("pipeline.community")
    @patch("pipeline.ingestion")
    @patch("pipeline.extraction")
    @patch("pipeline.chunking")
    @patch("pipeline.db")
    def test_wipe_db_skipped(self, mock_db, mock_chunk, mock_ext, mock_ing, mock_com):
        # wipe_db=False should NOT call db.wipe_database().
        status = PipelineStatus()
        run_pipeline(status, phases=[], wipe_db=False)
        mock_db.wipe_database.assert_not_called()

    @patch("pipeline.community")
    @patch("pipeline.ingestion")
    @patch("pipeline.extraction")
    @patch("pipeline.chunking")
    @patch("pipeline.db")
    def test_stdout_captured_to_queue(self, mock_db, mock_chunk, mock_ext, mock_ing, mock_com):
        # print() calls during pipeline run should appear in the log_queue.
        def fake_ingest():
            print("[ingestion] Loaded 42 graphs")
        mock_ing.ingest_graphs.side_effect = fake_ingest
        status = PipelineStatus()

        run_pipeline(status, phases=["ingest"], wipe_db=False)

        # Drain queue
        lines = []
        while not status.log_queue.empty():
            line = status.log_queue.get_nowait()
            if line is not None:
                lines.append(line)

        assert any("[ingestion] Loaded 42 graphs" in l for l in lines)

    @patch("pipeline.community")
    @patch("pipeline.ingestion")
    @patch("pipeline.extraction")
    @patch("pipeline.chunking")
    @patch("pipeline.db")
    def test_sentinel_pushed_on_completion(self, mock_db, mock_chunk, mock_ext, mock_ing, mock_com):
        # A None sentinel should be pushed to the queue when pipeline finishes.
        status = PipelineStatus()
        run_pipeline(status, phases=[], wipe_db=False)

        # The last item in the queue should be None
        items = []
        while not status.log_queue.empty():
            items.append(status.log_queue.get_nowait())
        assert None in items


# ── run_pipeline_sync tests ──

class TestRunPipelineSync:
    """run_pipeline_sync should be a simple blocking wrapper for CLI use."""

    @patch("pipeline.community")
    @patch("pipeline.ingestion")
    @patch("pipeline.extraction")
    @patch("pipeline.chunking")
    @patch("pipeline.db")
    def test_sync_runs_all_phases(self, mock_db, mock_chunk, mock_ext, mock_ing, mock_com):
        mock_chunk.load_and_chunk.return_value = ["doc1"]

        run_pipeline_sync(phases=["extract", "ingest", "community"], wipe_db=True)

        mock_db.test_connection.assert_called_once()
        mock_db.wipe_database.assert_called_once()
        mock_chunk.load_and_chunk.assert_called_once()
        mock_ext.extract_graphs.assert_called_once_with(["doc1"])
        mock_ing.ingest_graphs.assert_called_once()
        mock_com.resolve_and_merge.assert_called_once()

    @patch("pipeline.community")
    @patch("pipeline.ingestion")
    @patch("pipeline.extraction")
    @patch("pipeline.chunking")
    @patch("pipeline.db")
    def test_sync_subset(self, mock_db, mock_chunk, mock_ext, mock_ing, mock_com):
        run_pipeline_sync(phases=["community"], wipe_db=False)

        mock_db.wipe_database.assert_not_called()
        mock_chunk.load_and_chunk.assert_not_called()
        mock_com.resolve_and_merge.assert_called_once()
