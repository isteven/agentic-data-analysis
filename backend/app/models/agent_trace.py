import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class AgentTrace(Base):
    __tablename__ = "agent_traces"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("analysis_runs.id"), index=True)
    # Order within the run. All of a run's rows are inserted in one transaction, so they
    # share one created_at (Postgres now() is the transaction start): time can't order them.
    seq: Mapped[int] = mapped_column(Integer)
    node_name: Mapped[str] = mapped_column(String(64))
    step_type: Mapped[str] = mapped_column(String(16))  # reasoning | action | observation
    content: Mapped[str] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
