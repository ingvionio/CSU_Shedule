"""Очередь изменений для отложенного сообщения группе."""
from datetime import date, datetime

from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, Index, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class ScheduleChange(Base):
    __tablename__ = "schedule_changes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("groups.id", ondelete="CASCADE"), index=True)
    source: Mapped[str] = mapped_column(String(16))
    ref_id: Mapped[int | None] = mapped_column(Integer)
    action: Mapped[str] = mapped_column(String(16))
    day: Mapped[date | None] = mapped_column(Date)
    text: Mapped[str] = mapped_column(String(300))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    message_id: Mapped[int | None] = mapped_column(ForeignKey("messages.id", ondelete="SET NULL"))
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint("source IN ('override','exam','import')", name="ck_schedule_changes_source"),
        CheckConstraint("action IN ('created','changed','removed','uploaded')", name="ck_schedule_changes_action"),
        Index("ix_schedule_changes_pending", "processed_at", "group_id", "created_at"),
    )
