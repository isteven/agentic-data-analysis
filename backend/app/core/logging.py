import logging
import sys
from typing import TextIO

# Timestamp, level and logger name on every line, so a "[DEBUG]"-tagged message says
# when and where it happened.
LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"
_HANDLER_NAME = "apda"


def configure_logging(level: str, stream: TextIO | None = None) -> None:
    """Send log records at `level` and above to stderr (or `stream`), with a timestamp.

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
    handler.setFormatter(logging.Formatter(LOG_FORMAT, datefmt="%Y-%m-%d %H:%M:%S"))
    root.addHandler(handler)
    root.setLevel(level.upper())
