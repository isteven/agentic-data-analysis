"""Logging is configured once at startup: [DEBUG]-tagged info lines must actually come
out, with a timestamp. Unconfigured, the root logger dropped everything below WARNING."""

import io
import json
import logging
import re

import pytest

from app.core.logging import bind_run, configure_logging


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


# --- Logs an observability tool can read (Loki/Grafana, Datadog, ELK, CloudWatch) ---



def json_lines(out: io.StringIO) -> list[dict]:
    return [json.loads(line) for line in out.getvalue().splitlines() if line.strip()]


def test_json_format_writes_one_object_per_line_with_standard_fields(root_logger):
    out = io.StringIO()
    configure_logging("INFO", fmt="json", stream=out)

    logging.getLogger("app.x").info("llm call", extra={"model": "gpt-4o", "input_tokens": 1200})

    [line] = json_lines(out)
    assert line["level"] == "INFO"
    assert line["logger"] == "app.x"
    assert line["message"] == "llm call"
    assert re.match(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$", line["ts"])  # ISO-8601 UTC
    assert (line["model"], line["input_tokens"]) == ("gpt-4o", 1200)  # fields stay typed


def test_every_line_logged_during_a_run_carries_its_run_id(root_logger):
    out = io.StringIO()
    configure_logging("INFO", fmt="json", stream=out)

    with bind_run("run-42"):
        logging.getLogger("app.x").info("inside")
    logging.getLogger("app.x").info("outside")

    inside, outside = json_lines(out)
    assert inside["run_id"] == "run-42"
    assert "run_id" not in outside


def test_text_format_shows_the_run_and_the_fields(root_logger):
    out = io.StringIO()
    configure_logging("INFO", fmt="text", stream=out)

    with bind_run("run-42"):
        logging.getLogger("app.x").info("llm call", extra={"model": "gpt-4o"})
    logging.getLogger("app.x").info("outside")

    inside, outside = out.getvalue().splitlines()
    assert "[run=run-42]" in inside and "model=gpt-4o" in inside
    assert "[run=-]" in outside


def test_json_lines_include_the_exception(root_logger):
    out = io.StringIO()
    configure_logging("INFO", fmt="json", stream=out)

    try:
        raise ValueError("boom")
    except ValueError:
        logging.getLogger("app.x").exception("step failed")

    [line] = json_lines(out)
    assert "ValueError: boom" in line["exception"]


def test_uvicorns_own_lines_come_out_in_the_same_format(root_logger):
    # Uvicorn gives its loggers their own handlers and stops propagation, so its startup
    # and access lines skipped our format - plain text in an otherwise-JSON stream.
    server, access = logging.getLogger("uvicorn.error"), logging.getLogger("uvicorn.access")
    saved = [(lg, list(lg.handlers), lg.propagate, lg.disabled) for lg in (server, access)]
    for lg in (server, access):
        lg.addHandler(logging.StreamHandler(io.StringIO()))
        lg.propagate = False
    out = io.StringIO()
    try:
        configure_logging("INFO", fmt="json", stream=out)

        server.info("Application startup complete.")
        access.info('172.19.0.1 - "GET /api/health HTTP/1.1" 200')

        # Startup lines come through as JSON; access lines are dropped, because our
        # request log already covers every request, with its duration.
        assert [e["message"] for e in json_lines(out)] == ["Application startup complete."]
    finally:
        for lg, handlers, propagate, disabled in saved:
            lg.handlers[:] = handlers
            lg.propagate, lg.disabled = propagate, disabled


def test_uvicorns_coloured_copy_of_the_message_is_not_a_field(root_logger):
    out = io.StringIO()
    configure_logging("INFO", fmt="json", stream=out)

    logging.getLogger("uvicorn.error").info("started", extra={"color_message": "\x1b[1mstarted\x1b[0m"})

    [line] = json_lines(out)
    assert "color_message" not in line
