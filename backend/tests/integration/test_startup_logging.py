"""The API runs Alembic migrations at startup; that must not switch the app's logging off.
Alembic's fileConfig() disabled every logger that already existed (all app.* loggers)
and reset the root level to WARN, so the app's [DEBUG] info lines never appeared."""

import logging


# Sync on purpose: the app runs migrations in a worker thread, and Alembic's env calls
# asyncio.run(), which can't run inside an event loop.
def test_startup_migrations_leave_app_logging_on(migrated_db):
    from app.core.logging import configure_logging
    from app.main import _run_migrations

    app_logger = logging.getLogger("app.data.sql_runner")
    configure_logging("INFO")

    _run_migrations()

    assert app_logger.disabled is False
    assert logging.getLogger().level == logging.INFO
