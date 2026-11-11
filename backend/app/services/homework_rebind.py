from dataclasses import dataclass
from datetime import date, time

from sqlalchemy import Select, select, update
from sqlalchemy.orm import Session

from app.models import GroupHomework, Lesson, Semester
from app.services.schedule import lesson_occurs_on


@dataclass(frozen=True)
class HomeworkBinding:
    homework: GroupHomework
    group_id: int
    lesson_date: date | None
    start_time: time
    end_time: time
    subject_id: int
    subgroup: int | None


def collect_homework(session: Session, lesson_ids: Select[tuple[int]]) -> list[HomeworkBinding]:
    """Сохраняет привязки до удаления пар, включая архивную домашку."""
    rows = session.execute(select(GroupHomework, Lesson).join(
        Lesson, GroupHomework.lesson_id == Lesson.id,
    ).where(Lesson.id.in_(lesson_ids), GroupHomework.group_id == Lesson.group_id)).unique()
    return [HomeworkBinding(item, item.group_id, item.lesson_date, lesson.start_time, lesson.end_time,
                            lesson.subject_id, lesson.subgroup) for item, lesson in rows]


def rebind_homework(
    session: Session, semester: Semester, bindings: list[HomeworkBinding], lessons: list[Lesson],
) -> tuple[int, int]:
    """Восстанавливает только однозначные привязки к вновь вставленным парам."""
    by_subject: dict[tuple[int, int], list[Lesson]] = {}
    for lesson in lessons:
        by_subject.setdefault((lesson.group_id, lesson.subject_id), []).append(lesson)
    rebound = 0
    for binding in bindings:
        candidates = [lesson for lesson in by_subject.get((binding.group_id, binding.subject_id), [])
                      if binding.lesson_date is not None and lesson_occurs_on(semester, lesson, binding.lesson_date)]
        exact = [lesson for lesson in candidates if lesson.start_time == binding.start_time
                 and (binding.subgroup is None or lesson.subgroup == binding.subgroup)]
        matched = exact if exact else candidates
        lesson_id = matched[0].id if len(matched) == 1 else None
        # Явное updated_at подавляет onupdate: импорт не является правкой редактора.
        session.execute(update(GroupHomework).where(GroupHomework.id == binding.homework.id).values(
            lesson_id=lesson_id, updated_at=GroupHomework.updated_at,
        ))
        session.expire(binding.homework, ["lesson_id", "lesson"])
        rebound += lesson_id is not None
    return rebound, len(bindings) - rebound
