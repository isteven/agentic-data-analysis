"""add agent_traces.seq: a run's trace order

Revision ID: 0006
Revises: 0005
Create Date: 2026-09-26

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("agent_traces", sa.Column("seq", sa.Integer, nullable=True))
    # Existing rows can't be ordered by created_at (one transaction, one timestamp).
    # Their physical order (ctid) is the best record of insertion order left: each run's
    # rows were inserted once, in emission order, and never updated.
    op.execute(
        """
        UPDATE agent_traces t SET seq = o.seq
        FROM (
            SELECT id, ROW_NUMBER() OVER (PARTITION BY run_id ORDER BY ctid) - 1 AS seq
            FROM agent_traces
        ) o
        WHERE t.id = o.id
        """
    )
    op.alter_column("agent_traces", "seq", nullable=False)
    op.create_index("ix_agent_traces_run_id_seq", "agent_traces", ["run_id", "seq"])


def downgrade() -> None:
    op.drop_index("ix_agent_traces_run_id_seq", table_name="agent_traces")
    op.drop_column("agent_traces", "seq")
