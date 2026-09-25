import pytest

from app.core.config import Settings
from app.llm.provider_factory import FallbackChatModel, _build_bedrock, _build_openai


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


class _Model:
    def __init__(self, reply=None, error=None):
        self.reply, self.error = reply, error

    async def ainvoke(self, input, config=None, **kwargs):
        if self.error:
            raise self.error
        return self.reply


async def test_failed_provider_falls_back_and_reports_the_switch():
    switches = []
    model = FallbackChatModel(
        [("openai", _Model(error=ConnectionError("down"))), ("bedrock", _Model(reply="ok"))],
        on_fallback=lambda failed, used, err: switches.append((failed, used, type(err))),
    )

    assert await model.ainvoke("hi") == "ok"
    assert switches == [("openai", "bedrock", ConnectionError)]


async def test_error_is_raised_when_every_provider_fails():
    model = FallbackChatModel(
        [("openai", _Model(error=ConnectionError("a"))), ("bedrock", _Model(error=TimeoutError("b")))]
    )

    with pytest.raises(TimeoutError):
        await model.ainvoke("hi")
