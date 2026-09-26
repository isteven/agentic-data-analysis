"""A run must always end: saved with a final status, and its live stream told "done" -
whatever fails along the way. A failed step must not throw away work already done."""

import asyncio
import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import worker
from app.agents.graph import guarded
from app.agents.state import new_state
from app.api.routes import queries
from app.db.session import get_session

# --- Error boundary around each graph step -----------------------------------


async def test_a_failing_step_records_the_error_and_keeps_the_state():
    async def reviewer(state):
        state["report_markdown"] = "Finished report."
        raise ConnectionError("both providers down")

    state = new_state("q", "run-1")
    out = await guarded("reviewer", reviewer)(state)

    assert out["report_markdown"] == "Finished report."  # work done before the failure is kept
    assert out["errors"] == [{"node_name": "reviewer", "message": "ConnectionError: both providers down"}]
    assert out["trace_events"][-1]["node_name"] == "reviewer"
    assert "failed" in out["trace_events"][-1]["content"]


async def test_a_step_that_succeeds_is_untouched():
    async def coordinator(state):
        state["plan"] = [{"dataset_id": "d", "reason": "r"}]
        return state

    out = await guarded("coordinator", coordinator)(new_state("q", "run-1"))

    assert out["plan"] == [{"dataset_id": "d", "reason": "r"}]
    assert out["errors"] == []


async def test_a_job_timeout_is_not_swallowed_by_the_boundary():
    async def analytics(state):
        raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        await guarded("analytics", analytics)(new_state("q", "run-1"))


# --- Worker: the run is always saved and the stream always closed ------------


class FakeRedis:
    def __init__(self):
        self.added: list[dict] = []

    async def xadd(self, stream, fields):
        self.added.append(fields)

    async def expire(self, stream, seconds):
        pass


class Run:
    def __init__(self, status):
        self.status = status


@pytest.fixture
def fake_worker(monkeypatch):
    """The worker with its graph, persistence and database swapped for recorders."""
    calls = {"marked_failed": []}

    class NoSession:
        async def __aenter__(self):
            return object()

        async def __aexit__(self, *exc):
            return False

    monkeypatch.setattr(worker, "AsyncSessionLocal", lambda: NoSession())

    async def mark_run_failed(session, run_id, message):
        calls["marked_failed"].append(message)

    monkeypatch.setattr(worker, "mark_run_failed", mark_run_failed)
    return calls


async def test_a_finished_run_is_saved_and_the_stream_told_its_status(monkeypatch, fake_worker):
    async def run_graph(factory, state):
        return {**state, "status": "completed"}

    async def persist_run(session, run_id, query_text, final_state):
        return Run(final_state["status"]), []

    monkeypatch.setattr(worker, "run_graph", run_graph)
    monkeypatch.setattr(worker, "persist_run", persist_run)
    redis = FakeRedis()

    await worker.run_query_task({"redis": redis}, run_id=str(uuid.uuid4()), query_text="q")

    assert redis.added[-1] == {"done": "completed"}
    assert fake_worker["marked_failed"] == []


async def test_when_saving_fails_the_run_is_marked_failed_and_the_stream_still_closes(monkeypatch, fake_worker):
    async def run_graph(factory, state):
        return {**state, "status": "completed"}

    async def persist_run(session, run_id, query_text, final_state):
        raise RuntimeError("database went away")

    monkeypatch.setattr(worker, "run_graph", run_graph)
    monkeypatch.setattr(worker, "persist_run", persist_run)
    redis = FakeRedis()

    await worker.run_query_task({"redis": redis}, run_id=str(uuid.uuid4()), query_text="q")

    assert redis.added[-1] == {"done": "failed"}  # no subscriber waits forever
    assert len(fake_worker["marked_failed"]) == 1


async def test_a_timed_out_run_is_saved_as_failed(monkeypatch, fake_worker):
    saved = {}

    async def run_graph(factory, state):
        raise asyncio.CancelledError

    async def persist_run(session, run_id, query_text, final_state):
        saved.update(final_state)
        return Run(final_state["status"]), []

    monkeypatch.setattr(worker, "run_graph", run_graph)
    monkeypatch.setattr(worker, "persist_run", persist_run)
    redis = FakeRedis()

    await worker.run_query_task({"redis": redis}, run_id=str(uuid.uuid4()), query_text="q")

    assert saved["status"] == "failed"
    assert redis.added[-1] == {"done": "failed"}


# --- Submitting when the queue is down ---------------------------------------


def test_submit_answers_503_and_marks_the_run_failed_when_the_queue_is_down(monkeypatch):
    marked = []

    async def create_run(session, run_id, query_text, provider):
        return Run("running")

    async def mark_run_failed(session, run_id, message):
        marked.append(run_id)

    async def enqueue(*args, **kwargs):
        raise ConnectionError("redis unreachable")

    async def no_session():
        yield object()

    monkeypatch.setattr(queries, "create_run", create_run)
    monkeypatch.setattr(queries, "mark_run_failed", mark_run_failed)
    monkeypatch.setattr(queries.queue, "enqueue", enqueue)
    app = FastAPI()
    app.include_router(queries.router)
    app.dependency_overrides[get_session] = no_session

    response = TestClient(app).post("/api/queries", json={"query": "How many?"})

    assert response.status_code == 503
    assert len(marked) == 1
