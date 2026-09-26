import logging
import time
from collections.abc import Callable
from typing import Any, Literal

from langchain_core.callbacks import BaseCallbackManager
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.runnables import Runnable

from app.core.config import get_settings
from app.llm.config import ProviderName
from app.llm.usage import CallUsage, Outcome, UsageCollector

logger = logging.getLogger(__name__)

Tier = Literal["fast", "quality"]
# (failed provider, provider retried on, the error) -> None
FallbackHook = Callable[[str, str, Exception], None]
# Called once per attempt, successful or not.
UsageHook = Callable[[CallUsage], None]


def get_chat_model(
    provider: ProviderName | None = None,
    model_tier: Tier = "quality",
    on_fallback: FallbackHook | None = None,
    on_usage: UsageHook | None = None,
) -> "FallbackChatModel":
    """The requested provider, backed by the fallback and then the default provider.

    Including the default matters when the request names the fallback provider
    itself (e.g. bedrock): the default is then what's left to fall back to.
    Providers that aren't configured are skipped, so either one alone still works.
    """
    settings = get_settings()
    default = ProviderName(settings.llm_default_provider)
    fallback = ProviderName(settings.llm_fallback_provider)
    order = list(dict.fromkeys([provider or default, fallback, default]))

    models: list[tuple[str, BaseChatModel]] = []
    skipped: list[str] = []
    for name in order:
        try:
            models.append((name.value, build_provider(name, model_tier)))
        except RuntimeError as e:
            skipped.append(f"{name.value}: {e}")
    if not models:
        raise RuntimeError("No LLM provider is configured. " + " ".join(skipped))
    if skipped:
        logger.info("LLM providers skipped (not configured): %s", "; ".join(skipped))
    return FallbackChatModel(models, on_fallback, on_usage)


def build_provider(provider: ProviderName, model_tier: Tier) -> BaseChatModel:
    settings = get_settings()
    if provider == ProviderName.OPENAI:
        return _build_openai(settings, model_tier)
    if provider == ProviderName.BEDROCK:
        return _build_bedrock(settings, model_tier)
    if provider == ProviderName.MOCK:
        from app.llm.mock import MockChatModel

        return MockChatModel(latency_ms=settings.llm_mock_latency_ms)
    if provider in (ProviderName.AZURE_OPENAI, ProviderName.VERTEX_AI):
        raise NotImplementedError(f"Provider '{provider}' not yet implemented")
    raise ValueError(f"Unknown provider: {provider}")


class FallbackChatModel:
    """Chat model that retries a failed call on the next provider.

    Mirrors the parts of the chat-model API the agents use (`bind_tools`,
    `with_structured_output`, `ainvoke`), so node code is unchanged. Hand-rolled
    rather than LangChain's `.with_fallbacks()` because that doesn't say which
    provider answered, and the switch should be visible in the agent trace.
    """

    def __init__(
        self,
        models: list[tuple[str, Runnable]],
        on_fallback: FallbackHook | None = None,
        on_usage: UsageHook | None = None,
        configured_models: list[str | None] | None = None,
    ):
        self._models = models
        self._on_fallback = on_fallback
        self._on_usage = on_usage
        # Read before any wrapping (bind_tools etc.), which hides the model's attributes.
        # Reported for an attempt that failed before any response named the model.
        self._configured = configured_models or [_configured_model(m) for _, m in models]

    @property
    def providers(self) -> list[str]:
        return [name for name, _ in self._models]

    def _derive(self, fn: Callable[[Any], Runnable]) -> "FallbackChatModel":
        return FallbackChatModel(
            [(n, fn(m)) for n, m in self._models], self._on_fallback, self._on_usage, self._configured
        )

    def bind_tools(self, tools: Any, **kwargs: Any) -> "FallbackChatModel":
        return self._derive(lambda m: m.bind_tools(tools, **kwargs))

    def with_structured_output(self, schema: Any, **kwargs: Any) -> "FallbackChatModel":
        return self._derive(lambda m: m.with_structured_output(schema, **kwargs))

    async def ainvoke(self, input: Any, config: Any = None, **kwargs: Any) -> Any:
        last_error: Exception | None = None
        for i, (name, model) in enumerate(self._models):
            collector = UsageCollector()
            started = time.perf_counter()
            try:
                result = await model.ainvoke(input, _with_callback(config, collector), **kwargs)
                self._report(name, i, collector, started, "ok")
                return result
            # Any provider error counts (auth, rate limit after the SDK's own retries,
            # outage, malformed structured output): the other provider may still answer.
            except Exception as e:  # noqa: BLE001 - see comment above
                self._report(name, i, collector, started, "failed")
                last_error = e
                if i + 1 < len(self._models):
                    next_name = self._models[i + 1][0]
                    logger.warning(
                        "LLM provider %s failed (%s: %s); retrying on %s",
                        name,
                        type(e).__name__,
                        e,
                        next_name,
                    )
                    if self._on_fallback:
                        self._on_fallback(name, next_name, e)
        assert last_error is not None
        raise last_error

    def _report(
        self, provider: str, index: int, collector: UsageCollector, started: float, outcome: Outcome
    ) -> None:
        if self._on_usage is None:
            return
        usage: CallUsage = {
            "provider": provider,
            "model": collector.model or self._configured[index],
            "input_tokens": collector.input_tokens,
            "output_tokens": collector.output_tokens,
            "cached_input_tokens": collector.cached_input_tokens,
            "latency_ms": round((time.perf_counter() - started) * 1000),
            "outcome": outcome,
        }
        try:
            self._on_usage(usage)
        except Exception:  # recording usage must never fail the LLM call itself
            logger.exception("[DEBUG] token usage hook failed provider=%s", provider)


def _with_callback(config: Any, handler: UsageCollector) -> dict:
    """The caller's config with the collector added to (not replacing) its callbacks."""
    config = dict(config or {})
    existing = config.get("callbacks")
    if existing is None:
        config["callbacks"] = [handler]
    elif isinstance(existing, BaseCallbackManager):
        manager = existing.copy()
        manager.add_handler(handler, inherit=True)
        config["callbacks"] = manager
    else:
        config["callbacks"] = [*existing, handler]
    return config


def _configured_model(model: Any) -> str | None:
    """Model id a provider was built with (ChatOpenAI.model_name, ChatBedrockConverse.model_id)."""
    return getattr(model, "model_name", None) or getattr(model, "model_id", None)


def _build_openai(settings, model_tier: Tier) -> BaseChatModel:
    if not settings.openai_enabled:
        raise RuntimeError(
            "OpenAI provider requested but OPENAI_API_KEY is not set. "
            "Copy .env.example to .env and provide a key."
        )
    from langchain_openai import ChatOpenAI

    model = settings.openai_model_fast if model_tier == "fast" else settings.openai_model_quality
    return ChatOpenAI(
        model=model, api_key=settings.openai_api_key, temperature=settings.llm_temperature
    )


def _build_bedrock(settings, model_tier: Tier) -> BaseChatModel:
    if not settings.bedrock_enabled:
        raise RuntimeError(
            "Bedrock provider requested but LLM_ENABLE_BEDROCK is false or AWS credentials "
            "are not set. See ARCHITECTURE.md Section 4 for setup requirements."
        )
    from langchain_aws import ChatBedrockConverse

    model_id = (
        settings.bedrock_model_id_fast
        if model_tier == "fast"
        else settings.bedrock_model_id_quality
    )
    if not model_id:
        raise RuntimeError(
            f"Bedrock has no model id for the '{model_tier}' tier (BEDROCK_MODEL_ID_*)."
        )
    # Keys passed explicitly: pydantic-settings reads .env into settings, not os.environ,
    # so boto's own lookup only finds them under Docker (env_file), not a local uv run.
    return ChatBedrockConverse(
        model=model_id,
        region_name=settings.aws_region,
        temperature=settings.llm_temperature,
        aws_access_key_id=settings.aws_access_key_id,
        aws_secret_access_key=settings.aws_secret_access_key,
        aws_session_token=settings.aws_session_token or None,
    )
