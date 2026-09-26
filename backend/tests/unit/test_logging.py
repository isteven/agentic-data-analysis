"""Logging is configured once at startup: [DEBUG]-tagged info lines must actually come
out, with a timestamp. Unconfigured, the root logger dropped everything below WARNING."""

import io
import logging
import re

import pytest

from app.core.logging import configure_logging


@pytest.fixture
def root_logger():
    root = logging.getLogger()
    handlers, level = list(root.handlers), root.level
    yield root
    root.handlers[:] = handlers
    root.setLevel(level)


def test_info_lines_come_out_with_a_timestamp(root_logger):
    out = io.StringIO()
    configure_logging("INFO", stream=out)

    logging.getLogger("app.data.sql_runner").info("[DEBUG] rejected query")

    line = out.getvalue().strip()
    assert "[DEBUG] rejected query" in line
    assert re.match(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}", line)  # when it happened
    assert "app.data.sql_runner" in line  # and where


def test_configuring_twice_does_not_print_every_line_twice(root_logger):
    out = io.StringIO()
    configure_logging("INFO", stream=out)
    configure_logging("INFO", stream=out)

    logging.getLogger("app.x").info("once")

    assert out.getvalue().count("once") == 1


def test_the_level_setting_is_honoured(root_logger):
    out = io.StringIO()
    configure_logging("WARNING", stream=out)

    logging.getLogger("app.x").info("quiet")
    logging.getLogger("app.x").warning("loud")

    assert "quiet" not in out.getvalue()
    assert "loud" in out.getvalue()


def test_a_default_console_handler_is_replaced_not_doubled(root_logger):
    # The SAQ worker's CLI installs Python's default handler first; adding ours beside it
    # printed every line twice ("INFO:name:msg" and our timestamped line).
    default_out, out = io.StringIO(), io.StringIO()
    root_logger.addHandler(logging.StreamHandler(default_out))

    configure_logging("INFO", stream=out)
    logging.getLogger("app.x").info("once")

    assert default_out.getvalue() == ""
    assert out.getvalue().count("once") == 1
