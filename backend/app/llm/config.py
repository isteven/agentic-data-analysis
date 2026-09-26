from enum import StrEnum


class ProviderName(StrEnum):
    OPENAI = "openai"
    BEDROCK = "bedrock"
    AZURE_OPENAI = "azure_openai"
    VERTEX_AI = "vertex_ai"
    MOCK = "mock"  # load testing only (app/llm/mock.py); never listed in the UI
