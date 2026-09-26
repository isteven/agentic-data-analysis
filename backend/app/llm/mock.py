"""A mock chat model for load testing: no API, deterministic, optional simulated latency.

Enabled only by LLM_DEFAULT_PROVIDER=mock (infra/docker-compose.loadtest.yml). Each
reply is shaped like the calling agent's expected output and built from the prompt it
receives, so everything else - the SQL gate, Postgres, validator, persistence, the
queue - runs for real. A load test on the real providers would mostly measure their
rate limits.
"""

import asyncio
import re
import uuid
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage


def _text(input: Any) -> str:
    if isinstance(input, str):
        return input
    return "\n".join(m.content for m in input if isinstance(m, BaseMessage) and isinstance(m.content, str))


def _last(pattern: str, text: str) -> str | None:
    matches = re.findall(pattern, text, flags=re.MULTILINE)
    return matches[-1].strip() if matches else None


def _structured(schema: type, prompt: str) -> Any:
    """An instance of the agent's output schema, filled from its prompt."""
    name = schema.__name__
    if name == "Intent":
        return schema(rewritten=_last(r"^Question: (.+)$", prompt) or prompt[-200:], answerable=True)
    if name == "CoordinatorPlan":
        first = re.search(r"^- id: (\S+)", prompt, flags=re.MULTILINE)
        steps = [{"dataset_id": first.group(1), "reason": "Mock choice."}] if first else []
        return schema(steps=steps)
    if name == "Review":
        return schema(verdict="pass", reason="Mock review.")
    raise ValueError(f"MockChatModel has no reply for schema {name}")


class MockChatModel:
    """Mirrors the chat-model API the agents use: bind_tools, with_structured_output,
    ainvoke."""

    model_name = "mock"

    def __init__(self, latency_ms: int = 0, schema: type | None = None, tools: bool = False):
        self._latency = latency_ms / 1000
        self._schema = schema
        self._tools = tools

    def bind_tools(self, tools: Any, **kwargs: Any) -> "MockChatModel":
        return MockChatModel(round(self._latency * 1000), tools=True)

    def with_structured_output(self, schema: type, **kwargs: Any) -> "MockChatModel":
        return MockChatModel(round(self._latency * 1000), schema=schema)

    async def ainvoke(self, input: Any, config: Any = None, **kwargs: Any) -> Any:
        if self._latency:
            await asyncio.sleep(self._latency)
        prompt = _text(input)
        if self._schema is not None:
            return _structured(self._schema, prompt)
        if self._tools:
            # The planner: commit straight away to a count over the first view shown.
            view = re.search(r"^data\.(\w+):", prompt, flags=re.MULTILINE)
            sql = f"SELECT COUNT(*) AS row_count FROM data.{view.group(1) if view else 'unknown'}"
            call = {"name": "submit_answer", "args": {"sql": sql, "interpretation": "Mock: rows in the view."}}
            return AIMessage(content="", tool_calls=[{**call, "id": uuid.uuid4().hex}])
        return AIMessage(content="Mock report: the query result is shown in the chart and the Data tab.")
