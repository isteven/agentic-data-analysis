import logging

from app.agents.state import AgentState, LlmCall
from app.agents.trace import emit_trace
from app.llm.config import ProviderName
from app.llm.provider_factory import FallbackChatModel, Tier, get_chat_model
from app.llm.usage import CallUsage

logger = logging.getLogger(__name__)


def node_model(state: AgentState, node_name: str, model_tier: Tier) -> FallbackChatModel:
    """The run's chat model for one node; a provider switch is traced under that node,
    and every call's token usage is recorded in state["llm_calls"]."""

    def on_fallback(failed: str, used: str, error: Exception) -> None:
        state["fallbacks"].append(f"{failed}->{used}")
        emit_trace(
            state,
            node_name,
            "observation",
            f"LLM provider {failed} failed ({type(error).__name__}); retried on {used}.",
        )

    def on_usage(usage: CallUsage) -> None:
        call: LlmCall = {"node_name": node_name, "tier": model_tier, **usage}
        state["llm_calls"].append(call)
        # Tokens, model, latency and outcome per call, as fields a log tool can sum.
        logger.info("llm call", extra=dict(call))

    provider = ProviderName(state["provider"]) if state.get("provider") else None
    return get_chat_model(provider, model_tier, on_fallback=on_fallback, on_usage=on_usage)
