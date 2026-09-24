from typing import Literal

from langchain_core.language_models.chat_models import BaseChatModel

from app.core.config import get_settings
from app.llm.config import ProviderName


def get_chat_model(
    provider: ProviderName | None = None,
    model_tier: Literal["fast", "quality"] = "quality",
) -> BaseChatModel:
    settings = get_settings()
    resolved = provider or ProviderName(settings.llm_default_provider)

    if resolved == ProviderName.OPENAI:
        return _build_openai(settings, model_tier)

    if resolved == ProviderName.BEDROCK:
        return _build_bedrock(settings, model_tier)

    if resolved in (ProviderName.AZURE_OPENAI, ProviderName.VERTEX_AI):
        raise NotImplementedError(f"Provider '{resolved}' not yet implemented")

    raise ValueError(f"Unknown provider: {resolved}")


def _build_openai(settings, model_tier: Literal["fast", "quality"]) -> BaseChatModel:
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


def _build_bedrock(settings, model_tier: Literal["fast", "quality"]) -> BaseChatModel:
    if not settings.bedrock_enabled:
        raise RuntimeError(
            "Bedrock provider requested but LLM_ENABLE_BEDROCK is false or AWS credentials "
            "are not set. See ARCHITECTURE.md Section 4 for setup requirements."
        )
    from langchain_aws import ChatBedrockConverse

    model_id = (
        settings.bedrock_model_id_fast if model_tier == "fast" else settings.bedrock_model_id_quality
    )
    return ChatBedrockConverse(
        model=model_id, region_name=settings.aws_region, temperature=settings.llm_temperature
    )
