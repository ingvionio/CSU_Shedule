from datetime import date, datetime

from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base
from app.models.catalog import Group, Subject
from app.models.lesson import Lesson
from app.models.user import User


class GroupEditor(Base):
    """Студент, которому разрешено вести общую домашку группы."""

    __tablename__ = "group_editors"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("groups.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    is_primary: Mapped[bool] = mapped_column(default=False)
    active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    group: Mapped[Group] = relationship(lazy="joined")
    user: Mapped[User] = relationship(lazy="joined")

    __table_args__ = (UniqueConstraint("group_id", "user_id", name="uq_group_editors_group_user"),)


class GroupHomework(Base):
    """Общая домашняя работа группы, опубликованная редактором."""

    __tablename__ = "group_homework"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("groups.id", ondelete="CASCADE"), index=True)
    lesson_id: Mapped[int | None] = mapped_column(ForeignKey("lessons.id", ondelete="SET NULL"), nullable=True)
    lesson_date: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    subject_id: Mapped[int | None] = mapped_column(ForeignKey("subjects.id", ondelete="SET NULL"), nullable=True)
    title: Mapped[str] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text)
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    source: Mapped[str] = mapped_column(String(24), default="from_class")
    status: Mapped[str] = mapped_column(String(16), default="published")
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    updated_by: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    group: Mapped[Group] = relationship(lazy="joined")
    lesson: Mapped[Lesson | None] = relationship(lazy="joined")
    subject: Mapped[Subject | None] = relationship(lazy="joined")
    creator: Mapped[User] = relationship(foreign_keys=[created_by], lazy="joined")
    updater: Mapped[User] = relationship(foreign_keys=[updated_by], lazy="joined")

    __table_args__ = (
        CheckConstraint("source IN ('from_class','moodle','chat','unknown')", name="ck_group_homework_source"),
        CheckConstraint("status IN ('published','completed','archived')", name="ck_group_homework_status"),
        Index("ix_group_homework_group_date", "group_id", "lesson_date", "status"),
    )


class HomeworkCompletion(Base):
    """Личный статус выполнения общей домашки."""

    __tablename__ = "homework_completions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    homework_id: Mapped[int] = mapped_column(ForeignKey("group_homework.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (UniqueConstraint("homework_id", "user_id", name="uq_homework_completion"),)


class HomeworkRevision(Base):
    """Аудит изменений: можно восстановить, кто и что менял."""

    __tablename__ = "homework_revisions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    homework_id: Mapped[int] = mapped_column(ForeignKey("group_homework.id", ondelete="CASCADE"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    title: Mapped[str] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text)
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    source: Mapped[str] = mapped_column(String(24))
    status: Mapped[str] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
