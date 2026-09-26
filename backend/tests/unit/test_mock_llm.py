"""The mock LLM (load testing): deterministic answers shaped like each agent's, built from
the prompt it's given, so the rest of the pipeline runs for real without an API."""

import time

from langchain_core.messages import HumanMessage

from app.agents.nodes.coordinator import CoordinatorPlan
from app.agents.nodes.intent import Intent
from app.agents.nodes.reviewer import Review
from app.llm.mock import MockChatModel

CATALOG_PROMPT = "Available datasets:\n- id: retrenchment\n  title: R\n- id: hours\n  title: H\n\nUser question: q"
PLANNER_PROMPT = "Question: layoffs?\n\nViews selected for this question:\ndata.retrenchment:\n- year (time)"


async def test_intent_passes_the_question_through_as_answerable():
    intent = await MockChatModel().with_structured_output(Intent).ainvoke("Rules...\n\nQuestion: How many?")

    assert (intent.rewritten, intent.answerable) == ("How many?", True)


async def test_coordinator_picks_the_first_catalogued_dataset():
    plan = await MockChatModel().with_structured_output(CoordinatorPlan).ainvoke(CATALOG_PROMPT)

    assert [s.dataset_id for s in plan.steps] == ["retrenchment"]


async def test_planner_submits_a_count_over_the_first_view_it_was_shown():
    reply = await MockChatModel().bind_tools([]).ainvoke([HumanMessage(PLANNER_PROMPT)])

    call = reply.tool_calls[0]
    assert call["name"] == "submit_answer"
    assert call["args"]["sql"] == "SELECT COUNT(*) AS row_count FROM data.retrenchment"


async def test_reviewer_passes_and_the_report_has_no_numbers():
    review = await MockChatModel().with_structured_output(Review).ainvoke("...")
    report = await MockChatModel().ainvoke("...")

    assert review.verdict == "pass"
    assert not any(ch.isdigit() for ch in report.content)


async def test_latency_simulates_llm_thinking_time():
    started = time.perf_counter()
    await MockChatModel(latency_ms=200).ainvoke("...")

    assert time.perf_counter() - started >= 0.2


def test_the_mock_can_be_chosen_through_settings():
    # The load test selects it by environment (LLM_DEFAULT_PROVIDER=mock); settings
    # validation once rejected that value and the backend didn't start.
    from app.core.config import Settings

    settings = Settings(_env_file=None, llm_default_provider="mock", llm_fallback_provider="mock")

    assert (settings.llm_default_provider, settings.llm_fallback_provider) == ("mock", "mock")
