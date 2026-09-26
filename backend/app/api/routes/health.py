import asyncio
import logging

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.config import get_settings
from app.db.session import engine
from app.worker import queue

logger = logging.getLogger(__name__)

router = APIRouter()

# Per check, so a hung dependency makes the probe answer "not ready" rather than hang.
CHECK_TIMEOUT_SECONDS = 2.0


@router.get("/api/health")
async def health():
    """Liveness: the API process is up. Deliberately checks nothing else - a probe that
    restarted the API because the worker was down would only make things worse."""
    return {"status": "ok"}


class ReadinessChecks:
    """What answering a question needs besides the API process. Each check raises if
    its part isn't usable."""

    def __init__(self, engine: AsyncEngine, redis, queue):
        self._engine = engine
        self._redis = redis
        self._queue = queue

    async def database(self) -> None:
        async with self._engine.connect() as conn:
            await conn.execute(text("SELECT 1"))

    async def redis(self) -> None:
        await self._redis.ping()

    async def worker(self) -> None:
        # SAQ workers register themselves in Redis every few seconds, with an expiry:
        # an empty registry means no worker has been alive recently.
        info = await self._queue.info()
        if not info["workers"]:
            raise RuntimeError("no worker running")


def get_readiness_checks() -> ReadinessChecks:
    return ReadinessChecks(engine, queue.redis, queue)


async def _outcome(name: str, check) -> str:
    try:
        await asyncio.wait_for(check(), timeout=CHECK_TIMEOUT_SECONDS)
        return "ok"
    except TimeoutError:
        logger.warning("[DEBUG] readiness check timed out", extra={"check": name})
        return f"timed out after {CHECK_TIMEOUT_SECONDS:g} s"
    except Exception as exc:  # any failure means "not ready"; logged with its stack
        logger.warning("[DEBUG] readiness check failed", extra={"check": name}, exc_info=True)
        return f"{type(exc).__name__}: {exc}"


@router.get("/api/health/ready")
async def ready(checks: ReadinessChecks = Depends(get_readiness_checks)) -> JSONResponse:
    """Readiness: can this deployment answer a question right now? 200 when Postgres,
    Redis and at least one worker all answer; otherwise 503 naming what's down."""
    names = ("database", "redis", "worker")
    outcomes = await asyncio.gather(*(_outcome(name, getattr(checks, name)) for name in names))
    results = dict(zip(names, outcomes, strict=True))
    is_ready = all(outcome == "ok" for outcome in outcomes)
    return JSONResponse(
        status_code=200 if is_ready else 503,
        content={"status": "ready" if is_ready else "not ready", "checks": results},
    )


@router.get("/api/health/providers")
async def health_providers():
    settings = get_settings()
    return {
        "default": settings.llm_default_provider,
        "providers": {
            "openai": {"enabled": settings.openai_enabled},
            "bedrock": {"enabled": settings.bedrock_enabled},
        },
    }
