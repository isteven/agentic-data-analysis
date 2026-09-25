"""add the data_reader role that planner SQL runs as

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-25

"""

from collections.abc import Sequence

from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # NOLOGIN: nobody connects as it. The app switches into it per query (SET LOCAL ROLE),
    # so no second credential is needed. It is granted SELECT on the generated views only
    # (app/data/views.py re-grants after every rebuild); views run with their owner's
    # rights, so it never needs access to dataset_records or any app table.
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'data_reader') THEN
                CREATE ROLE data_reader NOLOGIN;
            END IF;
        END $$
        """)
    op.execute("GRANT data_reader TO CURRENT_USER")


def downgrade() -> None:
    op.execute("REVOKE data_reader FROM CURRENT_USER")
    op.execute("DROP OWNED BY data_reader")
    op.execute("DROP ROLE IF EXISTS data_reader")
