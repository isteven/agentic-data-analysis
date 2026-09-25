from app.agents.state import AgentState
from app.agents.trace import emit_trace
from app.llm.config import ProviderName
from app.llm.provider_factory import FallbackChatModel, Tier, get_chat_model


def node_model(state: AgentState, node_name: str, model_tier: Tier) -> FallbackChatModel:
    """The run's chat model for one node; a provider switch is traced under that node."""

    def on_fallback(failed: str, used: str, error: Exception) -> None:
        state["fallbacks"].append(f"{failed}->{used}")
        emit_trace(
            state,
            node_name,
            "observation",
            f"LLM provider {failed} failed ({type(error).__name__}); retried on {used}.",
        )

    provider = ProviderName(state["provider"]) if state.get("provider") else None
    return get_chat_model(provider, model_tier, on_fallback=on_fallback)
