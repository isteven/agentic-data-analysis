from fastapi import APIRouter

from app.core.config import get_settings

router = APIRouter()


@router.get("/api/health")
async def health():
    return {"status": "ok"}


@router.get("/api/health/providers")
async def health_providers():
    settings = get_settings()
    return {
        "openai": {"enabled": settings.openai_enabled},
        "bedrock": {"enabled": settings.bedrock_enabled},
    }
