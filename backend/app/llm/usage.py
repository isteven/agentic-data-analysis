"""Token usage per LLM call, as reported by the provider (never counted locally).

Counts come from each response's usage_metadata, which LangChain copies from the
provider's own usage block (OpenAI `usage`, Bedrock Converse `usage`). They are the
numbers the provider bills on. Tokens from different models aren't comparable (each
has its own tokenizer), so totals are only ever summed per model.
"""

from typing import Any, Literal, TypedDict

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.outputs import LLMResult

Outcome = Literal["ok", "failed"]


class CallUsage(TypedDict):
    """One attempt on one provider. A failed attempt that got no answer (auth, outage,
    rate limit) has zero tokens; one that answered but failed parsing keeps them."""

    provider: str
    model: str | None
    input_tokens: int  # includes cached input tokens, as both providers report it
    output_tokens: int
    cached_input_tokens: int
    latency_ms: int
    outcome: Outcome


class UsageCollector(BaseCallbackHandler):
    """Collects usage from every chat-model response inside one attempt. Attached as a
    callback, so it also sees calls wrapped by bind_tools / with_structured_output,
    whose parsed result no longer carries usage_metadata."""

    # Record synchronously, before ainvoke returns, rather than in an executor.
    run_inline = True

    def __init__(self) -> None:
        self.input_tokens = 0
        self.output_tokens = 0
        self.cached_input_tokens = 0
        self.model: str | None = None

    def on_llm_end(self, response: LLMResult, **kwargs: Any) -> None:
        for generations in response.generations:
            for generation in generations:
                message = getattr(generation, "message", None)
                if message is None:
                    continue
                usage = getattr(message, "usage_metadata", None) or {}
                self.input_tokens += usage.get("input_tokens", 0) or 0
                self.output_tokens += usage.get("output_tokens", 0) or 0
                details = usage.get("input_token_details") or {}
                self.cached_input_tokens += details.get("cache_read", 0) or 0
                self.model = message.response_metadata.get("model_name") or self.model


def summarize_usage(calls: list[dict]) -> dict:
    """Run totals, one entry per (provider, model) in first-use order. There is no
    grand total on purpose: a fallback run can mix tokenizers."""
    by_model: dict[tuple[str, str | None], dict] = {}
    for call in calls:
        key = (call["provider"], call["model"])
        entry = by_model.setdefault(
            key,
            {
                "provider": call["provider"],
                "model": call["model"],
                "calls": 0,
                "input_tokens": 0,
                "output_tokens": 0,
                "cached_input_tokens": 0,
            },
        )
        entry["calls"] += 1
        entry["input_tokens"] += call["input_tokens"]
        entry["output_tokens"] += call["output_tokens"]
        entry["cached_input_tokens"] += call["cached_input_tokens"]
    return {
        "calls": len(calls),
        "failed_calls": sum(1 for c in calls if c["outcome"] == "failed"),
        "by_model": list(by_model.values()),
    }
