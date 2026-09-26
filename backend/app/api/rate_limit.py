import logging
import time
from collections.abc import Callable

from fastapi import Depends, HTTPException, Request

from app.core.config import get_settings
from app.worker import queue

logger = logging.getLogger(__name__)

WINDOW_SECONDS = 60


class RateLimiter:
    """Fixed one-minute window per client, counted in Redis so every API process shares
    it. Each question costs several LLM calls on an endpoint with no login, so without
    a limit anyone who can reach it can run up the bill."""

    def __init__(self, redis, per_minute: int, clock: Callable[[], float] = time.time):
        self._redis = redis
        self._per_minute = per_minute
        self._clock = clock

    async def retry_after(self, client: str) -> int | None:
        """Seconds until `client` may ask again, or None if this request is allowed."""
        if self._per_minute <= 0:  # 0 = off (the load test runs every user from one IP)
            return None
        now = self._clock()
        window = int(now // WINDOW_SECONDS)
        key = f"ratelimit:queries:{client}:{window}"
        try:
            count = await self._redis.incr(key)
            if count == 1:
                await self._redis.expire(key, WINDOW_SECONDS)
        except Exception:
            # Fail open: Redis being down must not become the reason nobody can ask
            # anything (submitting reports the queue outage itself).
            logger.exception("[DEBUG] rate limiter unavailable client=%s; allowing", client)
            return None
        if count <= self._per_minute:
            return None
        return max(1, WINDOW_SECONDS - int(now % WINDOW_SECONDS))


def get_rate_limiter() -> RateLimiter:
    return RateLimiter(queue.redis, get_settings().rate_limit_queries_per_minute)


async def limit_queries(request: Request, limiter: RateLimiter = Depends(get_rate_limiter)) -> None:
    client = request.client.host if request.client else "unknown"
    retry_after = await limiter.retry_after(client)
    if retry_after is not None:
        logger.warning("[DEBUG] rate limit hit client=%s retry_after=%ss", client, retry_after)
        raise HTTPException(
            status_code=429,
            detail=f"Too many questions. Please wait {retry_after} seconds and try again.",
            headers={"Retry-After": str(retry_after)},
        )
