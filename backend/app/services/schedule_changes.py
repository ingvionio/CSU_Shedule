"""Запись уведомлений в транзакции изменения и короткие русские тексты."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Group, LessonOverride
from app.models.exam import ExamEvent
from app.models.schedule_change import ScheduleChange

MONTHS = ("января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа", "сентября", "октября", "ноября", "декабря")
WEEKDAYS = ("пн", "вт", "ср", "чт", "пт", "сб", "вс")
Source = Literal["override", "exam", "import"]
Action = Literal["created", "changed", "removed", "uploaded"]


def today() -> date:
    return date.today()


async def record(db: AsyncSession, *, group_id: int, source: Source, action: Action, text: str,
           ref_id: int | None = None, day: date | None = None, now: datetime | None = None) -> ScheduleChange | None:
    if day is not None and day < today():
        return None
    # Сериализуем запись с другими писателями и сборщиком; NO KEY UPDATE
    # совместим с проверкой FK у уже созданного изменения.
    await db.scalar(select(Group.id).where(Group.id == group_id).with_for_update(key_share=True))
    item = ScheduleChange(group_id=group_id, source=source, ref_id=ref_id, action=action, day=day,
                          text=text if len(text) <= 300 else text[:297] + "…",
                          created_at=now or datetime.now(timezone.utc))
    db.add(item)
    return item


def date_label(day: date) -> str:
    return f"{day.day} {MONTHS[day.month - 1]} ({WEEKDAYS[day.weekday()]})"


def _value(value: object) -> str:
    return str(value) if value is not None and value != "" else "—"


def _time(value: time | None) -> str:
    return value.strftime("%H:%M") if value else "время не указано"


def _position(slot: int | None, start: time | None) -> str:
    return f"{slot} пара" if slot is not None else _time(start)


def override_text(item: LessonOverride, removed: bool = False) -> str:
    lesson = item.lesson
    source = lesson or item
    subject = source.subject.name
    prefix = f"{date_label(item.date)}, {_position(source.slot, source.start_time)} — {subject}: "
    if removed:
        return prefix + "изменение отменено, пара по обычному расписанию"
    if item.kind == "cancel":
        return prefix + "отменена"
    if item.kind == "move":
        return prefix + f"перенесена на {date_label(item.target_date)}, {_position(item.slot, item.start_time)}"
    if item.kind == "add":
        return prefix + "дополнительная пара"
    changes = []
    fields = (
        ("ауд.", lesson.room.name if lesson.room else None, item.room.name if item.room else None),
        ("преподаватель", lesson.teacher.full_name if lesson.teacher else None, item.teacher.full_name if item.teacher else None),
        ("предмет", lesson.subject.name, item.subject.name),
        ("формат", lesson.type.name, item.type.name),
        ("время", f"{_time(lesson.start_time)}–{_time(lesson.end_time)}", f"{_time(item.start_time)}–{_time(item.end_time)}"),
    )
    for label, before, after in fields:
        if before != after:
            changes.append(f"{label} {_value(before)} → {_value(after)}")
    return prefix + "изменения" + (": " + ", ".join(changes) if changes else "")


def exam_snapshot(item: ExamEvent) -> dict:
    return {field: getattr(item, field) for field in ("date", "start_time", "room", "teacher", "subject", "note", "event_type", "kind", "cancelled")} | {
        "groups": ", ".join(group.name for group in item.groups),
    }


def exam_text(item: ExamEvent, action: Action, before: dict | None = None) -> str:
    kind = "Пересдача" if item.kind == "retake" else "Сессия"
    prefix = f"{kind} {date_label(item.date)}" + (f", {_time(item.start_time)}" if item.start_time else "") + f" — {item.subject}: "
    if action == "created":
        return prefix + "добавлена"
    if action == "removed":
        return prefix + "удалена"
    current = exam_snapshot(item)
    changes = []
    before = before or {}
    if "date" in before and before["date"] != item.date:
        changes.append(f"перенесена с {date_label(before['date'])}")
    for field, label in (("start_time", "время"), ("room", "аудитория"), ("teacher", "преподаватель"),
                         ("subject", "предмет"), ("note", "примечание"), ("event_type", "формат"), ("groups", "группы"), ("kind", "вид расписания")):
        if field in before and before[field] != current[field]:
            old, new = before[field], current[field]
            if field == "start_time":
                old, new = _time(old), _time(new)
            elif field == "event_type":
                names = {"exam": "Экзамен", "consultation": "Консультация", "credit": "Зачёт", "graded_credit": "Дифф. зачёт", "other": "Другое"}
                old, new = names.get(old), names.get(new)
            elif field == "kind":
                old, new = ("Сессия" if old == "session" else "Пересдача"), ("Сессия" if new == "session" else "Пересдача")
            changes.append(f"{label} {_value(old)} → {_value(new)}")
    if "cancelled" in before and before["cancelled"] != item.cancelled:
        changes.append("отменена" if item.cancelled else "восстановлена")
    return prefix + (", ".join(changes) or "изменена")


async def record_exam(db: AsyncSession, item: ExamEvent, action: Action, before: dict | None = None,
                group_ids: set[int] | None = None) -> None:
    for group_id in sorted(group_ids if group_ids is not None else {group.id for group in item.groups}):
        await record(db, group_id=group_id, source="exam", ref_id=item.id, action=action, day=item.date,
               text=exam_text(item, action, before))


def weekly_text(number: int, monday: date) -> str:
    sunday = monday + timedelta(days=6)
    period = f"{monday.day}–{sunday.day} {MONTHS[sunday.month - 1]}" if monday.month == sunday.month else f"{monday.day} {MONTHS[monday.month - 1]} – {sunday.day} {MONTHS[sunday.month - 1]}"
    return f"Загружено расписание на неделю {number} ({period})"
