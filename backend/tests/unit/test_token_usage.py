"""Token usage per LLM call: read from what the provider reports, recorded per attempt
(including failed ones), and summarised per model so different tokenizers never mix."""

import pytest
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.runnables import RunnableLambda

from app.agents import llm
from app.agents.state import new_state
from app.llm.provider_factory import FallbackChatModel
from app.llm.usage import summarize_usage


class ReportingModel(BaseChatModel):
    """A chat model that answers the way a real provider does: usage in usage_metadata,
    the exact model version in response_metadata. Runs through LangChain's own callback
    machinery, so the recording path is the production one."""

    model_name: str = "gpt-4o-mini"
    answered_by: str = "gpt-4o-mini-2024-07-18"
    input_tokens: int = 1200
    output_tokens: int = 80
    cached_tokens: int = 1024
    error: str | None = None

    @property
    def _llm_type(self) -> str:
        return "reporting-fake"

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        if self.error:
            raise ConnectionError(self.error)
        message = AIMessage(
            content="ok",
            usage_metadata={
                "input_tokens": self.input_tokens,
                "output_tokens": self.output_tokens,
                "total_tokens": self.input_tokens + self.output_tokens,
                "input_token_details": {"cache_read": self.cached_tokens},
            },
            response_metadata={"model_name": self.answered_by},
        )
        return ChatResult(generations=[ChatGeneration(message=message)])


def recorder():
    calls = []
    return calls, calls.append


async def test_records_provider_reported_tokens_and_model():
    calls, on_usage = recorder()
    model = FallbackChatModel([("openai", ReportingModel())], on_usage=on_usage)

    await model.ainvoke("hi")

    assert len(calls) == 1
    call = calls[0]
    assert call["provider"] == "openai"
    assert call["model"] == "gpt-4o-mini-2024-07-18"  # the version that answered
    assert (call["input_tokens"], call["output_tokens"], call["cached_input_tokens"]) == (1200, 80, 1024)
    assert call["outcome"] == "ok"
    assert call["latency_ms"] >= 0


async def test_usage_survives_bind_tools_and_structured_output_wrappers():
    calls, on_usage = recorder()
    model = FallbackChatModel([("openai", ReportingModel())], on_usage=on_usage)
    # What with_structured_output builds: the chat model piped into a parser.
    wrapped = model._derive(lambda m: m | RunnableLambda(lambda msg: msg.content.upper()))

    assert await wrapped.ainvoke("hi") == "OK"
    assert calls[0]["input_tokens"] == 1200


async def test_attempt_that_fails_before_answering_is_recorded_with_zero_tokens():
    calls, on_usage = recorder()
    model = FallbackChatModel(
        [
            ("openai", ReportingModel(error="rate limited")),
            ("bedrock", ReportingModel(answered_by="claude-haiku-4-5", input_tokens=900, output_tokens=60, cached_tokens=0)),
        ],
        on_usage=on_usage,
    )

    await model.ainvoke("hi")

    assert [(c["provider"], c["outcome"], c["input_tokens"]) for c in calls] == [
        ("openai", "failed", 0),
        ("bedrock", "ok", 900),
    ]
    assert calls[0]["model"] == "gpt-4o-mini"  # nothing answered: the configured model


async def test_answer_that_fails_parsing_keeps_its_billed_tokens():
    calls, on_usage = recorder()

    def bad_parse(_):
        raise ValueError("malformed structured output")

    model = FallbackChatModel(
        [("openai", ReportingModel() | RunnableLambda(bad_parse))], on_usage=on_usage
    )

    with pytest.raises(ValueError):
        await model.ainvoke("hi")
    assert [(c["outcome"], c["input_tokens"], c["output_tokens"]) for c in calls] == [("failed", 1200, 80)]


async def test_node_model_tags_each_call_with_node_and_tier(monkeypatch):
    monkeypatch.setattr(
        llm,
        "get_chat_model",
        lambda provider=None, tier=None, on_fallback=None, on_usage=None, before_call=None: (
            FallbackChatModel([("openai", ReportingModel())], on_fallback, on_usage)
        ),
    )
    state = new_state("q", "run-1")

    await llm.node_model(state, "coordinator", "fast").ainvoke("hi")

    assert state["llm_calls"][0]["node_name"] == "coordinator"
    assert state["llm_calls"][0]["tier"] == "fast"
    assert state["llm_calls"][0]["input_tokens"] == 1200


def _call(provider, model, inp, out, cached=0, outcome="ok", node="analytics"):
    return {
        "node_name": node,
        "provider": provider,
        "model": model,
        "tier": "fast",
        "input_tokens": inp,
        "output_tokens": out,
        "cached_input_tokens": cached,
        "latency_ms": 10,
        "outcome": outcome,
    }


def test_summary_totals_per_model_never_across_tokenizers():
    summary = summarize_usage(
        [
            _call("openai", "gpt-4o-mini", 1000, 50, cached=600),
            _call("openai", "gpt-4o-mini", 800, 40),
            _call("openai", "gpt-4o-mini", 0, 0, outcome="failed"),
            _call("bedrock", "claude-haiku-4-5", 900, 60),
        ]
    )

    assert summary["calls"] == 4
    assert summary["failed_calls"] == 1
    assert summary["by_model"] == [
        {"provider": "openai", "model": "gpt-4o-mini", "calls": 3, "input_tokens": 1800, "output_tokens": 90, "cached_input_tokens": 600},
        {"provider": "bedrock", "model": "claude-haiku-4-5", "calls": 1, "input_tokens": 900, "output_tokens": 60, "cached_input_tokens": 0},
    ]


def test_summary_of_a_run_without_llm_calls_is_empty():
    assert summarize_usage([]) == {"calls": 0, "failed_calls": 0, "by_model": []}
