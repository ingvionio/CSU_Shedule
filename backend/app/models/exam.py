"""Разовые события сессии и пересдач."""
import datetime as dt
from datetime import datetime

from sqlalchemy import JSON, Boolean, CheckConstraint, Column, Date, DateTime, ForeignKey, Index, Integer, String, Table, Text, Time, func, false
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base
from app.models.catalog import Group


exam_event_groups = Table(
    "exam_event_groups", Base.metadata,
    Column("event_id", ForeignKey("exam_events.id", ondelete="CASCADE"), primary_key=True),
    Column("group_id", ForeignKey("groups.id", ondelete="CASCADE"), primary_key=True),
    Index("ix_exam_event_groups_group_event", "group_id", "event_id"),
)


class ExamImport(Base):
    __tablename__ = "exam_imports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    semester_id: Mapped[int] = mapped_column(ForeignKey("semesters.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(16))
    file_name: Mapped[str] = mapped_column(String(300))
    events_count: Mapped[int] = mapped_column(Integer, default=0)
    warnings: Mapped[list[dict]] = mapped_column(JSON, default=list)
    uploaded_by: Mapped[str | None] = mapped_column(String(64))
    uploaded_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (CheckConstraint("kind IN ('session','retake')", name="ck_exam_imports_kind"),)


class ExamEvent(Base):
    __tablename__ = "exam_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    semester_id: Mapped[int] = mapped_column(ForeignKey("semesters.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(16))
    date: Mapped[dt.date] = mapped_column(Date)
    start_time: Mapped[dt.time | None] = mapped_column(Time)
    subject: Mapped[str] = mapped_column(String(300))
    teacher: Mapped[str | None] = mapped_column(String(200))
    room: Mapped[str | None] = mapped_column(String(200))
    note: Mapped[str | None] = mapped_column(Text)
    cancelled: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    original: Mapped[dict[str, str | None] | None] = mapped_column(JSON(none_as_null=True))
    event_type: Mapped[str | None] = mapped_column(String(24))
    source: Mapped[str] = mapped_column(String(16))
    import_id: Mapped[int | None] = mapped_column(ForeignKey("exam_imports.id", ondelete="SET NULL"))
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    groups: Mapped[list[Group]] = relationship(secondary=exam_event_groups, lazy="selectin", order_by=Group.name,
                                              passive_deletes=True)

    __table_args__ = (
        CheckConstraint("kind IN ('session','retake')", name="ck_exam_events_kind"),
        CheckConstraint("source IN ('import','manual')", name="ck_exam_events_source"),
        CheckConstraint("event_type IN ('consultation','exam','credit','graded_credit','other')", name="ck_exam_events_event_type"),
        Index("ix_exam_events_semester_kind_date", "semester_id", "kind", "date"),
    )
