from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "development"
    log_level: str = "INFO"

    database_url: str = "postgresql+asyncpg://apda:apda@db:5432/apda"
    redis_url: str = "redis://redis:6379/0"

    llm_default_provider: Literal["openai", "bedrock"] = "openai"
    llm_fallback_provider: Literal["openai", "bedrock"] = "bedrock"
    # 0 = same question, same answer: needed for SQL generation and consistency tests.
    # Without it providers default to 1.0 (OpenAI), which varied answers run to run.
    llm_temperature: float = 0.0

    openai_api_key: str = ""
    openai_model_fast: str = "gpt-4o-mini"
    openai_model_quality: str = "gpt-4o"

    llm_enable_bedrock: bool = False
    aws_access_key_id: str = ""
    aws_secret_access_key: str = ""
    aws_session_token: str = ""
    aws_region: str = "ap-southeast-1"
    bedrock_model_id_fast: str = ""
    bedrock_model_id_quality: str = ""

    cors_origin: str = "http://localhost:3000"
    rate_limit_queries_per_minute: int = 10

    @property
    def openai_enabled(self) -> bool:
        return bool(self.openai_api_key)

    @property
    def bedrock_enabled(self) -> bool:
        return self.llm_enable_bedrock and bool(self.aws_access_key_id)


@lru_cache
def get_settings() -> Settings:
    return Settings()
