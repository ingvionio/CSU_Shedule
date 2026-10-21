import datetime as dt
from datetime import date, datetime, time

from sqlalchemy import (
    JSON,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Time,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin
from app.models.catalog import LessonType, Room, Subject, Teacher
from app.models.enums import ImportStatus, PublishStatus, WeekParity


class ScheduleImport(Base):
    """Одна загрузка Excel-файла."""

    __tablename__ = "schedule_imports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    semester_id: Mapped[int] = mapped_column(ForeignKey("semesters.id", ondelete="CASCADE"))
    file_name: Mapped[str] = mapped_column(String(300))
    status: Mapped[str] = mapped_column(String(16), default=ImportStatus.PARSED.value)
    # Ячейки, которые не удалось разобрать: [{sheet, cell, text, reason}]
    errors: Mapped[list | None] = mapped_column(JSON, nullable=True)
    lessons_count: Mapped[int] = mapped_column(Integer, default=0)
    uploaded_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        CheckConstraint("status IN ('parsed','failed','published')", name="ck_schedule_imports_status"),
    )


class Lesson(Base, TimestampMixin):
    """Постоянная (регулярная) пара группы."""

    __tablename__ = "lessons"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    semester_id: Mapped[int] = mapped_column(ForeignKey("semesters.id", ondelete="CASCADE"), index=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("groups.id", ondelete="CASCADE"), index=True)

    weekday: Mapped[int] = mapped_column(SmallInteger)  # 1 = пн ... 6 = сб
    start_time: Mapped[time] = mapped_column(Time)
    end_time: Mapped[time] = mapped_column(Time)
    # Номер в сетке звонков; null — пара вне сетки.
    slot: Mapped[int | None] = mapped_column(ForeignKey("time_slots.number"), nullable=True)
    week_parity: Mapped[str] = mapped_column(String(8), default=WeekParity.BOTH.value)

    subject_id: Mapped[int] = mapped_column(ForeignKey("subjects.id", ondelete="RESTRICT"))
    lesson_type: Mapped[str] = mapped_column(ForeignKey("lesson_types.code", ondelete="RESTRICT"))
    teacher_id: Mapped[int | None] = mapped_column(ForeignKey("teachers.id", ondelete="SET NULL"), nullable=True)
    room_id: Mapped[int | None] = mapped_column(ForeignKey("rooms.id", ondelete="SET NULL"), nullable=True)

    # Срок действия пары. Основной фильтр при сборке недели.
    valid_from: Mapped[date] = mapped_column(Date)
    valid_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    # Исходное ограничение из Excel: "(9-15 НЕД.)". Храним для прослеживаемости.
    week_from: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    week_to: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)

    # Подгруппа из Excel (группа занимает 2 столбца). Пока не используется при выдаче.
    subgroup: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)

    status: Mapped[str] = mapped_column(String(16), default=PublishStatus.PUBLISHED.value)
    import_id: Mapped[int | None] = mapped_column(
        ForeignKey("schedule_imports.id", ondelete="SET NULL"), nullable=True
    )
    # Исходный текст ячеек — чтобы можно было сверить разбор с файлом.
    source_ref: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source_text: Mapped[str | None] = mapped_column(String(600), nullable=True)

    subject: Mapped[Subject] = relationship(lazy="joined")
    type: Mapped[LessonType] = relationship(lazy="joined")
    teacher: Mapped[Teacher | None] = relationship(lazy="joined")
    room: Mapped[Room | None] = relationship(lazy="joined")

    __table_args__ = (
        CheckConstraint("weekday BETWEEN 1 AND 7", name="ck_lessons_weekday"),
        CheckConstraint("week_parity IN ('odd','even','both')", name="ck_lessons_week_parity"),
        CheckConstraint("status IN ('draft','published')", name="ck_lessons_status"),
        CheckConstraint("subgroup IS NULL OR subgroup BETWEEN 1 AND 4", name="ck_lessons_subgroup"),
        Index("ix_lessons_lookup", "group_id", "weekday", "status"),
    )


class LessonOverride(Base):
    """Временное изменение расписания группы на конкретную дату.

    Постоянные пары не перезаписываются: итоговая неделя собирается при
    запросе. Для `move`, `replace` и `add` запись хранит полное описание
    итоговой пары (недостающие поля при создании берутся из исходной).
    """

    __tablename__ = "lesson_overrides"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    semester_id: Mapped[int] = mapped_column(ForeignKey("semesters.id", ondelete="CASCADE"), index=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("groups.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(16))

    # Дата исходной пары (для `add` — дата новой пары).
    date: Mapped[dt.date] = mapped_column(Date, index=True)
    # Исходная постоянная пара; null для `add`.
    lesson_id: Mapped[int | None] = mapped_column(
        ForeignKey("lessons.id", ondelete="CASCADE"), nullable=True, index=True
    )
    # Для `move`: куда перенесли.
    target_date: Mapped[dt.date | None] = mapped_column(Date, nullable=True, index=True)

    # Итоговая пара для `move` / `replace` / `add`.
    start_time: Mapped[time | None] = mapped_column(Time, nullable=True)
    end_time: Mapped[time | None] = mapped_column(Time, nullable=True)
    slot: Mapped[int | None] = mapped_column(ForeignKey("time_slots.number"), nullable=True)
    subject_id: Mapped[int | None] = mapped_column(ForeignKey("subjects.id", ondelete="RESTRICT"), nullable=True)
    lesson_type: Mapped[str | None] = mapped_column(
        ForeignKey("lesson_types.code", ondelete="RESTRICT"), nullable=True
    )
    teacher_id: Mapped[int | None] = mapped_column(ForeignKey("teachers.id", ondelete="SET NULL"), nullable=True)
    room_id: Mapped[int | None] = mapped_column(ForeignKey("rooms.id", ondelete="SET NULL"), nullable=True)
    subgroup: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)

    comment: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # Одно действие админа для потока создаёт по записи на группу с общим batch_id.
    batch_id: Mapped[str] = mapped_column(String(36), index=True)
    status: Mapped[str] = mapped_column(String(16), default=PublishStatus.PUBLISHED.value)
    created_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    lesson: Mapped[Lesson | None] = relationship(lazy="joined")
    subject: Mapped[Subject | None] = relationship(lazy="joined")
    type: Mapped[LessonType | None] = relationship(lazy="joined")
    teacher: Mapped[Teacher | None] = relationship(lazy="joined")
    room: Mapped[Room | None] = relationship(lazy="joined")

    __table_args__ = (
        CheckConstraint("kind IN ('cancel','move','replace','add')", name="ck_lesson_overrides_kind"),
        CheckConstraint("status IN ('draft','published')", name="ck_lesson_overrides_status"),
        # У одной пары на одну дату — не больше одного изменения.
        UniqueConstraint("lesson_id", "date", name="uq_lesson_overrides_lesson_date"),
    )
