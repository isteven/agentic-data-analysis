"""GET /api/queries/{run_id} response: token usage is the run's per-model totals plus
each call in order; absent while a run is in progress or for runs from before usage
was recorded."""

import uuid

from app.api.routes.queries import _to_response
from app.llm.usage import summarize_usage
from app.models.analysis_run import AnalysisRun


def call(node, provider="bedrock", model="claude-haiku-4-5", inp=900, out=60, outcome="ok"):
    return {
        "node_name": node,
        "tier": "fast",
        "provider": provider,
        "model": model,
        "input_tokens": inp,
        "output_tokens": out,
        "cached_input_tokens": 0,
        "latency_ms": 1500,
        "outcome": outcome,
    }


def run(status="completed", token_usage=None):
    return AnalysisRun(id=uuid.uuid4(), query_text="q", status=status, token_usage=token_usage)


def test_finished_run_returns_totals_per_model_and_each_call():
    calls = [call("intent"), call("analytics", inp=2000, out=150), call("analytics", provider="openai", model="gpt-4o-mini", inp=0, out=0, outcome="failed")]

    response = _to_response(run(token_usage=summarize_usage(calls)), [], calls)

    usage = response.token_usage
    assert usage.calls == 3
    assert usage.failed_calls == 1
    assert [(m.provider, m.input_tokens, m.output_tokens) for m in usage.by_model] == [
        ("bedrock", 2900, 210),
        ("openai", 0, 0),
    ]
    assert [(c.node_name, c.outcome) for c in usage.per_call] == [
        ("intent", "ok"),
        ("analytics", "ok"),
        ("analytics", "failed"),
    ]


def test_run_in_progress_has_no_token_usage_yet():
    assert _to_response(run(status="running"), [], []).token_usage is None


def test_run_recorded_before_token_tracking_has_no_token_usage():
    assert _to_response(run(token_usage=None), [], []).token_usage is None
