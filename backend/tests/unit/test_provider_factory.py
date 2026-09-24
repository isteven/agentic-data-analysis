from app.core.config import Settings
from app.llm.provider_factory import _build_bedrock, _build_openai


def _settings(**overrides) -> Settings:
    # _env_file=None: tests must not depend on the developer's local .env
    return Settings(_env_file=None, **overrides)


def test_openai_defaults_to_temperature_zero():
    model = _build_openai(_settings(openai_api_key="sk-test"), "fast")

    assert model.temperature == 0.0


def test_openai_temperature_is_configurable():
    model = _build_openai(_settings(openai_api_key="sk-test", llm_temperature=0.3), "quality")

    assert model.temperature == 0.3


def test_bedrock_defaults_to_temperature_zero():
    settings = _settings(
        llm_enable_bedrock=True,
        aws_access_key_id="test-key",
        aws_secret_access_key="test-secret",
        bedrock_model_id_fast="anthropic.claude-3-haiku-20240307-v1:0",
    )

    model = _build_bedrock(settings, "fast")

    assert model.temperature == 0.0
