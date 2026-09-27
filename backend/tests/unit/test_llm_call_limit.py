"""A per-question limit on LLM calls (MAX_LLM_CALLS_PER_RUN): one number a person can
set from the calls per run shown in the Token usage tab. It covers every node, the
reviewer's re-route and fallback retries. When it's reached, the run stops calling LLMs
and keeps what it has, with a visible note."""

import pytest

from app.agents import llm
from app.agents.graph import guarded
from app.agents.llm import LlmCallLimitReached
from app.agents.state import new_state
from app.core.config import Settings
from app.llm.provider_factory import FallbackChatModel


class _Model:
    def __init__(self, reply="ok", error=None):
        self.reply, self.error, self.calls = reply, error, 0

    async def ainvoke(self, input, config=None, **kwargs):
        self.calls += 1
        if self.error:
            raise self.error
        return self.reply


def _call(outcome="ok"):
    return {
        "node_name": "analytics",
        "tier": "quality",
        "provider": "openai",
        "model": "gpt-4o",
        "input_tokens": 1000,
        "output_tokens": 50,
        "cached_input_tokens": 0,
        "latency_ms": 10,
        "outcome": outcome,
    }


@pytest.fixture
def one_provider(monkeypatch):
    """node_model on a fake provider, with the limit set per test."""
    model = _Model()

    def use_limit(limit: int):
        monkeypatch.setattr(
            llm, "get_settings", lambda: Settings(_env_file=None, max_llm_calls_per_run=limit)
        )

    monkeypatch.setattr(
        llm,
        "get_chat_model",
        lambda provider=None, tier=None, on_fallback=None, on_usage=None, before_call=None: (
            FallbackChatModel([("openai", model)], on_fallback, on_usage, before_call=before_call)
        ),
    )
    return model, use_limit


def test_default_limit_leaves_room_above_typical_runs():
    # Measured runs make 6-11 calls (11 with a reviewer re-route).
    assert Settings(_env_file=None).max_llm_calls_per_run == 20


# --- The check before each attempt -----------------------------------------------


async def test_a_blocked_call_never_reaches_the_provider_and_is_not_a_fallback():
    def block():
        raise LlmCallLimitReached(3)

    first, second = _Model(), _Model()
    switches = []
    model = FallbackChatModel(
        [("openai", first), ("bedrock", second)],
        on_fallback=lambda *a: switches.append(a),
        before_call=block,
    )

    with pytest.raises(LlmCallLimitReached):
        await model.ainvoke("hi")
    assert (first.calls, second.calls, switches) == (0, 0, [])


async def test_a_fallback_retry_is_checked_as_its_own_call():
    checks = []
    model = FallbackChatModel(
        [("openai", _Model(error=ConnectionError("down"))), ("bedrock", _Model())],
        before_call=lambda: checks.append(1),
    )

    assert await model.ainvoke("hi") == "ok"
    assert len(checks) == 2


async def test_the_check_survives_bind_tools_and_structured_output():
    checks = []

    class Wrappable(_Model):
        def bind_tools(self, tools, **kwargs):
            return self

        def with_structured_output(self, schema, **kwargs):
            return self

    model = FallbackChatModel([("openai", Wrappable())], before_call=lambda: checks.append(1))

    await model.bind_tools([]).ainvoke("hi")
    await model.with_structured_output(dict).ainvoke("hi")
    assert len(checks) == 2


# --- node_model: the run's count against the setting ----------------------------------


async def test_calls_below_the_limit_go_ahead(one_provider):
    provider, use_limit = one_provider
    use_limit(3)
    state = new_state("q", "run-1")
    state["llm_calls"] = [_call(), _call()]

    await llm.node_model(state, "reviewer", "quality").ainvoke("hi")

    assert provider.calls == 1
    assert len(state["llm_calls"]) == 3


async def test_the_call_after_the_limit_is_refused(one_provider):
    provider, use_limit = one_provider
    use_limit(3)
    state = new_state("q", "run-1")
    state["llm_calls"] = [_call(), _call(outcome="failed"), _call()]  # failed attempts count too

    with pytest.raises(LlmCallLimitReached, match="3"):
        await llm.node_model(state, "reviewer", "quality").ainvoke("hi")
    assert provider.calls == 0
    assert len(state["llm_calls"]) == 3


async def test_zero_turns_the_limit_off(one_provider):
    provider, use_limit = one_provider
    use_limit(0)
    state = new_state("q", "run-1")
    state["llm_calls"] = [_call() for _ in range(50)]

    await llm.node_model(state, "reviewer", "quality").ainvoke("hi")

    assert provider.calls == 1


# --- The error boundary: stop calling LLMs, keep the work, say so ---------------------


async def test_reaching_the_limit_keeps_the_report_and_adds_a_visible_note():
    async def reviewer(state):
        raise LlmCallLimitReached(20)

    state = new_state("q", "run-1")
    state["report_markdown"] = "Retrenchments fell."

    out = await guarded("reviewer", reviewer)(state)

    assert out["report_markdown"].startswith("Retrenchments fell.")
    assert "limit" in out["report_markdown"].split("Retrenchments fell.")[1]
    assert out["errors"] == [{"node_name": "reviewer", "message": str(LlmCallLimitReached(20))}]
    assert "20" in out["trace_events"][-1]["content"]


async def test_the_note_has_no_digits_for_the_validator_to_flag():
    async def analytics(state):
        raise LlmCallLimitReached(20)

    out = await guarded("analytics", analytics)(new_state("q", "run-1"))

    assert out["report_markdown"]
    assert not any(ch.isdigit() for ch in out["report_markdown"])


async def test_the_note_is_added_once_when_several_steps_are_skipped():
    async def step(state):
        raise LlmCallLimitReached(20)

    state = new_state("q", "run-1")
    state = await guarded("analytics", step)(state)
    note = state["report_markdown"]
    state = await guarded("report_writer", step)(state)

    assert state["report_markdown"] == note
    assert [e["node_name"] for e in state["errors"]] == ["analytics", "report_writer"]
