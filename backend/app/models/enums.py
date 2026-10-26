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


class FeedbackKind(StrEnum):
    """Кому адресовано обращение — папка в админке."""

    DEV = "dev"
    METHODIST = "methodist"
    DEANERY = "deanery"
    # Студент не знает, к кому идти; админ потом переносит в нужную папку.
    UNKNOWN = "unknown"


class FeedbackStatus(StrEnum):
    NEW = "new"
    IN_PROGRESS = "in_progress"
    ANSWERED = "answered"
    ARCHIVED = "archived"


class EmailStatus(StrEnum):
    PENDING = "pending"
    SENT = "sent"
    FAILED = "failed"
    # Почта не настроена: письмо только записано в лог.
    SKIPPED = "skipped"
