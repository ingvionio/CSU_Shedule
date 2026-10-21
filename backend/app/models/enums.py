from enum import StrEnum


class WeekParity(StrEnum):
    """Чётность недели. `both` — пара идёт каждую неделю (нет мигалки)."""

    ODD = "odd"
    EVEN = "even"
    BOTH = "both"


class PublishStatus(StrEnum):
    DRAFT = "draft"
    PUBLISHED = "published"


class ImportStatus(StrEnum):
    PARSED = "parsed"
    FAILED = "failed"
    PUBLISHED = "published"


class OverrideKind(StrEnum):
    """Вид временного изменения на конкретную дату."""

    CANCEL = "cancel"
    MOVE = "move"
    REPLACE = "replace"
    ADD = "add"


class LessonStatus(StrEnum):
    """Статус пары в собранном расписании недели (контракт 03-schedule-json.md)."""

    REGULAR = "regular"
    CHANGED = "changed"
    CANCELLED = "cancelled"
    MOVED_OUT = "moved_out"
    MOVED_IN = "moved_in"
    ADDED = "added"
