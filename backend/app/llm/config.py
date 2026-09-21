from enum import StrEnum


class ProviderName(StrEnum):
    OPENAI = "openai"
    BEDROCK = "bedrock"
    AZURE_OPENAI = "azure_openai"
    VERTEX_AI = "vertex_ai"
