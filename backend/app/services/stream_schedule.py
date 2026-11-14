"""Общие занятия выбранных групп с сохранением элементов основной группы."""

from __future__ import annotations

from collections import defaultdict
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Group, Lesson, LessonOverride, Semester
from app.services import schedule
from app.services.groups import level_of
from app.services.weeks import WeekInfo


class StreamScheduleError(Exception):
    """Группы нельзя объединить в поток."""


def load_groups(session: Session, group_ids: list[int]) -> list[Group]:
    ids = list(dict.fromkeys(group_ids))
    if len(ids) < 2:
        raise StreamScheduleError("выберите не менее двух разных групп потока")
    groups = [schedule.get_group(session, group_id) for group_id in ids]
    primary = groups[0]
    if any(group.course != primary.course or level_of(group.direction) != level_of(primary.direction)
           for group in groups[1:]):
        raise StreamScheduleError("группы потока должны быть одного курса и уровня обучения")
    return groups


def build_stream_schedule(
    session: Session, groups: list[Group], semester: Semester, week_number: int, today: date,
) -> tuple[WeekInfo, list[dict]]:
    schedules = [schedule.build_week_schedule(session, group, semester, week_number, today)
                 for group in groups]
    all_items = [item for _, days in schedules for day in days for item in day["lessons"]]
    lesson_ids = {int(item["id"][2:]) for item in all_items if item["id"].startswith("l-")}
    override_ids = {int(item["id"][2:]) for item in all_items if item["id"].startswith("o-")}
    sources = {lesson.id: lesson for lesson in session.scalars(select(Lesson).where(Lesson.id.in_(lesson_ids)))}
    overrides = {item.id: item for item in session.scalars(
        select(LessonOverride).where(LessonOverride.id.in_(override_ids))
    )}

    def key(day: dict, item: dict) -> tuple:
        if item["id"].startswith("l-"):
            source = sources[int(item["id"][2:])]
            origin = day["date"]
        else:
            override = overrides[int(item["id"][2:])]
            if override.kind == "add":
                return ("added", override.batch_id)
            source = override.lesson
            origin = override.date
        # Предмет и время берём из постоянной пары, даже после замены или переноса.
        return ("source", origin, source.start_time, source.subject.name)

    indexes: list[dict[tuple, list[tuple[dict, dict]]]] = []
    for _, days in schedules[1:]:
        index = defaultdict(list)
        for day in days:
            for item in day["lessons"]:
                index[key(day, item)].append((day, item))
        indexes.append(index)

    info, primary_days = schedules[0]
    result = []
    for day in primary_days:
        common = []
        for item in day["lessons"]:
            identity = key(day, item)
            if not all(identity in index for index in indexes):
                continue
            differences = []
            for group, index in zip(groups[1:], indexes):
                candidates = index[identity]
                # В одной неделе могут быть обе стороны переноса одного занятия.
                other_day, other = next((candidate for candidate in candidates
                                         if candidate[1]["status"] == item["status"]), candidates[0])
                details = _differences(day, item, other_day, other)
                if details:
                    differences.append(f"{group.name}: {', '.join(details)}")
            common.append({**item, "note_key": None, "stream_diff": differences or None})
        result.append({**day, "lessons": common})
    return info, result


def _point_label(point: dict) -> str:
    day = date.fromisoformat(point["date"]).strftime("%d.%m.%Y")
    return f"{day} {point['start_time']}–{point['end_time']}"


def _differences(day: dict, item: dict, other_day: dict, other: dict) -> list[str]:
    details = []
    if other["status"] != item["status"]:
        details.append({"regular": "без изменений", "changed": "изменена", "cancelled": "отменена",
                        "moved_out": "перенесена", "moved_in": "перенос", "added": "доп. пара"}[other["status"]])
    if (day["date"], item["start_time"], item["end_time"]) != (
        other_day["date"], other["start_time"], other["end_time"]
    ):
        details.append(_point_label({"date": other_day["date"].isoformat(), **other}))
    moved_to = (other.get("change") or {}).get("moved_to")
    if moved_to and moved_to != (item.get("change") or {}).get("moved_to"):
        details.append(f"на {_point_label(moved_to)}")
    if item["room"] != other["room"]:
        details.append(f"ауд. {other['room']}" if other["room"] else "аудитория не указана")
    if item["teacher"] != other["teacher"]:
        details.append(f"преп. {other['teacher']}" if other["teacher"] else "преподаватель не указан")
    if item["type"] != other["type"]:
        details.append(other["type"]["name"])
    if item["subject"] != other["subject"]:
        details.append(other["subject"])
    return details
