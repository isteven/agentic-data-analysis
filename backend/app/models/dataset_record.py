import uuid

from sqlalchemy import ForeignKey, Integer
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class DatasetRecord(Base):
    """One cleaned source row, stored as a JSON document. Queried only through the typed
    views generated in the `data` schema (app/data/views.py)."""

    __tablename__ = "dataset_records"

    dataset_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("datasets.id", ondelete="CASCADE"), primary_key=True
    )
    row_num: Mapped[int] = mapped_column(Integer, primary_key=True)
    record: Mapped[dict] = mapped_column(JSONB, nullable=False)
