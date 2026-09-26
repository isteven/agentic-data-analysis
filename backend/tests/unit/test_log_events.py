"""The events an operator needs are logged with fields, not just prose: every HTTP
request, LLM call, agent step and finished run. A tool can then chart tokens per model,
latency and error rates straight from the logs."""

import io
import json
import logging

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.agents import llm
from app.agents.state import new_state
from app.agents.trace import emit_trace
from app.api.middleware import log_requests
from app.core.logging import configure_logging
from app.llm.provider_factory import FallbackChatModel
from tests.unit.test_token_usage import ReportingModel


@pytest.fixture
def logs():
    root = logging.getLogger()
    handlers, level = list(root.handlers), root.level
    out = io.StringIO()
    configure_logging("INFO", fmt="json", stream=out)
    yield lambda message: [
        e for e in (json.loads(line) for line in out.getvalue().splitlines()) if e["message"] == message
    ]
    root.handlers[:] = handlers
    root.setLevel(level)


def test_every_http_request_is_logged_with_status_and_duration(logs):
    app = FastAPI()
    app.middleware("http")(log_requests)

    @app.get("/api/ping")
    async def ping():
        return {"ok": True}

    TestClient(app).get("/api/ping")

    [event] = logs("http request")
    assert (event["method"], event["path"], event["status"]) == ("GET", "/api/ping", 200)
    assert event["duration_ms"] >= 0


async def test_every_llm_call_is_logged_with_tokens_model_and_latency(logs, monkeypatch):
    monkeypatch.setattr(
        llm,
        "get_chat_model",
        lambda provider=None, tier=None, on_fallback=None, on_usage=None: FallbackChatModel(
            [("openai", ReportingModel())], on_fallback, on_usage
        ),
    )

    await llm.node_model(new_state("q", "run-1"), "coordinator", "fast").ainvoke("hi")

    [event] = logs("llm call")
    assert event["node_name"] == "coordinator"
    assert (event["provider"], event["model"]) == ("openai", "gpt-4o-mini-2024-07-18")
    assert (event["input_tokens"], event["output_tokens"], event["cached_input_tokens"]) == (1200, 80, 1024)
    assert event["outcome"] == "ok" and event["latency_ms"] >= 0


def test_every_agent_step_is_logged(logs):
    emit_trace(new_state("q", "run-1"), "analytics", "action", "run_sql: SELECT 1")

    [event] = logs("agent step")
    assert (event["node_name"], event["step_type"], event["content"]) == ("analytics", "action", "run_sql: SELECT 1")


async def test_a_finished_run_is_logged_and_every_line_of_it_carries_its_id(logs, monkeypatch):
    from app import worker

    class NoSession:
        async def __aenter__(self):
            return object()

        async def __aexit__(self, *exc):
            return False

    class Run:
        status = "completed"

    class Redis:
        async def xadd(self, *a):
            pass

        async def expire(self, *a):
            pass

    async def run_graph(factory, state):
        emit_trace(state, "intent", "action", "Interpreted as: q")
        return {**state, "status": "completed", "llm_calls": [{"node_name": "intent"}] * 3}

    async def persist_run(session, run_id, query_text, final_state):
        return Run(), []

    monkeypatch.setattr(worker, "AsyncSessionLocal", lambda: NoSession())
    monkeypatch.setattr(worker, "run_graph", run_graph)
    monkeypatch.setattr(worker, "persist_run", persist_run)
    run_id = "5b0e7a1c-0000-4000-8000-000000000001"

    await worker.run_query_task({"redis": Redis()}, run_id=run_id, query_text="q")

    [step] = logs("agent step")
    [done] = logs("run finished")
    assert step["run_id"] == run_id and done["run_id"] == run_id
    assert (done["status"], done["llm_calls"]) == ("completed", 3)
    assert done["duration_ms"] >= 0
