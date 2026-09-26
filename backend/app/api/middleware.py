import logging
import time
from collections.abc import Awaitable, Callable

from fastapi import Request, Response

logger = logging.getLogger("app.http")


async def log_requests(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
    """One log line per request with its outcome and duration, so request rates, error
    rates and latency can be read straight from the logs. For the SSE trace stream the
    duration is until the stream starts, not its whole length."""
    started = time.perf_counter()
    status = 500
    try:
        response = await call_next(request)
        status = response.status_code
        return response
    finally:
        logger.info(
            "http request",
            extra={
                "method": request.method,
                "path": request.url.path,
                "status": status,
                "duration_ms": round((time.perf_counter() - started) * 1000, 1),
                "client": request.client.host if request.client else None,
            },
        )
