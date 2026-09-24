"""add dataset_records and the data schema for generated views

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-25

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "dataset_records",
        sa.Column(
            "dataset_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("datasets.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("row_num", sa.Integer, primary_key=True),
        sa.Column("record", postgresql.JSONB, nullable=False),
    )
    # Holds only views generated from dataset profiles (app/data/views.py); rebuilt by the
    # seed step, so its contents are deliberately not managed by Alembic.
    op.execute("CREATE SCHEMA IF NOT EXISTS data")


def downgrade() -> None:
    op.execute("DROP SCHEMA IF EXISTS data CASCADE")
    op.drop_table("dataset_records")
