import json
import logging
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Literal, TextIO

LogFormat = Literal["text", "json"]

_HANDLER_NAME = "apda"
# Every line logged while a run is being worked on carries its id, so a log tool can
# follow one run end to end without each call site having to pass it.
_run_id: ContextVar[str | None] = ContextVar("log_run_id", default=None)

# Attributes every LogRecord has; anything else on a record came from `extra=` and is
# an event field worth keeping (tokens, model, duration_ms, ...).
# color_message: Uvicorn's terminal-coloured copy of the message, not a field.
_RECORD_ATTRS = set(vars(logging.makeLogRecord({}))) | {"message", "asctime", "run_id", "taskName", "color_message"}


@contextmanager
def bind_run(run_id: str) -> Iterator[None]:
    token = _run_id.set(run_id)
    try:
        yield
    finally:
        _run_id.reset(token)


def _fields(record: logging.LogRecord) -> dict:
    return {k: v for k, v in vars(record).items() if k not in _RECORD_ATTRS}


class _RunIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.run_id = _run_id.get()
        return True


class JsonFormatter(logging.Formatter):
    """One JSON object per line: what Loki/Grafana, Datadog, ELK and CloudWatch ingest
    as-is. Event fields keep their types, so tokens and durations can be summed."""

    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.run_id:
            entry["run_id"] = record.run_id
        entry.update(_fields(record))
        if record.exc_info:
            entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(entry, default=str)


class TextFormatter(logging.Formatter):
    """For reading in a terminal: timestamp, level, logger, run, message, then fields."""

    def __init__(self) -> None:
        super().__init__("%(asctime)s %(levelname)s %(name)s [run=%(run)s]: %(message)s", "%Y-%m-%d %H:%M:%S")

    def format(self, record: logging.LogRecord) -> str:
        record.run = record.run_id or "-"
        line = super().format(record)
        del record.run
        fields = " ".join(f"{k}={v}" for k, v in _fields(record).items() if k != "run")
        return f"{line} {fields}" if fields else line


def configure_logging(level: str, fmt: LogFormat = "text", stream: TextIO | None = None) -> None:
    """Send log records at `level` and above to stderr (or `stream`), as text or JSON.

    Called once by each process at startup (API lifespan, worker startup, seed script).
    Without it the root logger stays at WARNING with no format, so every
    logger.info("[DEBUG] ...") in the app was silently dropped.

    Takes over console output: our previous handler and any plain console handler
    already on the root (the SAQ worker's CLI installs Python's default one, which
    printed every line a second time) are replaced. Subclasses such as pytest's log
    capture are left alone.
    """
    root = logging.getLogger()
    for handler in [
        h for h in root.handlers if h.get_name() == _HANDLER_NAME or type(h) is logging.StreamHandler
    ]:
        root.removeHandler(handler)
    handler = logging.StreamHandler(stream or sys.stderr)
    handler.set_name(_HANDLER_NAME)
    handler.addFilter(_RunIdFilter())
    handler.setFormatter(JsonFormatter() if fmt == "json" else TextFormatter())
    root.addHandler(handler)
    root.setLevel(level.upper())

    # Uvicorn gives its loggers their own handlers and stops propagation, so its lines
    # skipped this format (plain text in an otherwise-JSON stream). Route them through
    # ours; drop its access log, since app/api/middleware.py logs every request with
    # its duration.
    for name in ("uvicorn", "uvicorn.error"):
        server = logging.getLogger(name)
        server.handlers.clear()
        server.propagate = True
    access = logging.getLogger("uvicorn.access")
    access.handlers.clear()
    access.propagate = False
    access.disabled = True
