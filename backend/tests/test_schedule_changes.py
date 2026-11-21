"""Уведомления расписания: транзакции, накопление и готовая неделя."""
from datetime import date, datetime, time, timedelta, timezone

import pytest
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import Base, Group, Lesson, LessonOverride, Message, MessageRecipient, PushDelivery, PushSubscription, Semester, Subject, User
from app.models.schedule_change import ScheduleChange
from app.schemas.admin import OverrideIn
from app.schemas.exam import ExamCreate, ExamPatch
from app.schemas.message import MessageIn
from app.services import exams, messages, overrides, schedule, schedule_changes, worker
from app.services.importer import ensure_reference_data

NOW = datetime(2026, 11, 16, 10, tzinfo=timezone.utc)
DAY = NOW.date()


@pytest.fixture
def db(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'changes.db'}")
    @event.listens_for(engine, "connect")
    def foreign_keys(connection, _):
        connection.execute("PRAGMA foreign_keys=ON")
    Base.metadata.create_all(engine)
    monkeypatch.setattr(schedule_changes, "today", lambda: DAY)
    monkeypatch.setattr(get_settings(), "schedule_change_delay_seconds", 120)
    monkeypatch.setattr(get_settings(), "vapid_public_key", "public")
    monkeypatch.setattr(get_settings(), "vapid_private_key", "private")
    monkeypatch.setattr(get_settings(), "fcm_credentials_file", "")
    with Session(engine, expire_on_commit=False) as db:
        semester = Semester(title="Осень", start_date=date(2026, 9, 1), end_date=date(2027, 1, 3), total_weeks=18, is_active=True)
        db.add_all([semester, Group(name="ПИ 101", course=1, direction="ПИ"), Group(name="МПИ 101", course=1, direction="МПИ")])
        ensure_reference_data(db)
        db.commit()
        yield db
    engine.dispose()


def groups(db):
    return list(db.scalars(select(Group).order_by(Group.id)))


def rows(db):
    return list(db.scalars(select(ScheduleChange).order_by(ScheduleChange.id)))


def add(db, group_id=None, **values):
    return schedule_changes.record(db, group_id=group_id or groups(db)[0].id, source="override", action="created", ref_id=1, day=DAY, text="Изменение", now=NOW, **values)


def test_record_no_commit_past_and_rollback(db):
    add(db)
    db.flush()
    assert len(rows(db)) == 1
    db.rollback()
    assert rows(db) == []
    schedule_changes.record(db, group_id=groups(db)[0].id, source="exam", action="created", day=DAY - timedelta(days=1), text="Прошлое", now=NOW)
    db.commit()
    assert rows(db) == []


def test_worker_debounce_grouping_outbox_and_repeat(db):
    first, second = groups(db)
    user = User(full_name="Студент", group_id=first.id, device_key_hash="changes-device")
    db.add(user); db.flush()
    db.add(PushSubscription(user_id=user.id, endpoint="https://push.invalid/1", p256dh="key", auth="auth"))
    add(db, first.id)
    add(db, second.id)
    db.commit()
    assert worker.process_schedule_changes(db, NOW + timedelta(seconds=119)) == 0
    schedule_changes.record(db, group_id=first.id, source="import", action="uploaded", text="Расписание обновлено", now=NOW + timedelta(seconds=60))
    db.commit()
    assert worker.process_schedule_changes(db, NOW + timedelta(seconds=121)) == 1
    assert worker.process_schedule_changes(db, NOW + timedelta(seconds=181)) == 1
    assert worker.process_schedule_changes(db, NOW + timedelta(minutes=10)) == 0
    sent = list(db.scalars(select(Message)))
    assert len(sent) == 2 and all(m.created_by == "system" and m.importance == "normal" for m in sent)
    assert db.scalar(select(func.count(PushDelivery.id))) == 1
    assert db.scalar(select(func.count(MessageRecipient.id))) == 1
    assert all(row.processed_at and row.message_id for row in rows(db))


def test_worker_cancels_created_changed_removed_and_handles_reused_ref(db):
    group_id = groups(db)[0].id
    for action in ["created", "changed", "removed"]:
        schedule_changes.record(db, group_id=group_id, source="exam", ref_id=7, action=action, day=DAY, text=action, now=NOW)
    db.commit()
    worker.process_schedule_changes(db, NOW + timedelta(minutes=3))
    assert db.scalar(select(func.count(Message.id))) == 0
    assert all(row.processed_at and row.message_id is None for row in rows(db))
    for action in ["created", "removed", "created"]:
        schedule_changes.record(db, group_id=group_id, source="override", ref_id=7, action=action, day=DAY, text=action, now=NOW)
    db.commit()
    worker.process_schedule_changes(db, NOW + timedelta(minutes=3))
    assert db.scalars(select(Message)).one().body == "created"


def test_worker_sorts_limits_and_upload_title(db):
    group_id = groups(db)[0].id
    for n in reversed(range(12)):
        schedule_changes.record(db, group_id=group_id, source="exam", ref_id=n, action="changed", day=DAY + timedelta(days=n), text=f"Строка {n}", now=NOW)
    db.commit()
    worker.process_schedule_changes(db, NOW + timedelta(minutes=3))
    message = db.scalars(select(Message)).one()
    assert message.title == "Изменение расписания"
    assert message.body.splitlines() == [f"Строка {n}" for n in range(10)] + ["и ещё 2"]
    schedule_changes.record(db, group_id=group_id, source="import", action="uploaded", text="Опубликовано расписание сессии", now=NOW)
    db.commit()
    worker.process_schedule_changes(db, NOW + timedelta(minutes=3))
    assert db.scalars(select(Message).order_by(Message.id.desc())).first().title == "Опубликовано расписание сессии"


def test_worker_commit_failure_rolls_back_message_push_and_marks(db, monkeypatch):
    user = User(full_name="Студент", group_id=groups(db)[0].id, device_key_hash="rollback-device")
    db.add(user); db.flush()
    db.add(PushSubscription(user_id=user.id, endpoint="https://push.invalid/rollback", p256dh="key", auth="auth"))
    add(db); db.commit()
    def fail():
        db.flush()
        assert db.scalar(select(func.count(Message.id))) == 1
        assert db.scalar(select(func.count(PushDelivery.id))) == 1
        assert all(row.processed_at for row in rows(db))
        raise RuntimeError("сбой записи")
    monkeypatch.setattr(db, "commit", fail)
    with pytest.raises(RuntimeError):
        worker.process_schedule_changes(db, NOW + timedelta(minutes=3))
    db.rollback()
    assert rows(db)[0].processed_at is None
    assert db.scalar(select(func.count(Message.id))) == 0
    assert db.scalar(select(func.count(PushDelivery.id))) == 0


def test_worker_locks_whole_group_and_rows(db):
    from sqlalchemy.dialects.postgresql import dialect
    add(db); db.commit()
    statements = []
    def capture(context):
        if context.is_select and context.statement._for_update_arg is not None:
            statements.append(str(context.statement.compile(dialect=dialect())))
    event.listen(db, "do_orm_execute", capture)
    try:
        worker.process_schedule_changes(db, NOW + timedelta(minutes=3))
    finally:
        event.remove(db, "do_orm_execute", capture)
    assert any("FROM groups" in sql and "FOR NO KEY UPDATE SKIP LOCKED" in sql for sql in statements)
    assert any("FROM schedule_changes" in sql and "FOR UPDATE SKIP LOCKED" in sql for sql in statements)


def make_lesson(db, group):
    semester = db.scalars(select(Semester)).one()
    subject = db.scalar(select(Subject).where(Subject.name == "Математика"))
    if subject is None:
        subject = Subject(name="Математика"); db.add(subject); db.flush()
    lesson = Lesson(semester_id=semester.id, group_id=group.id, weekday=1, start_time=time(9, 40), end_time=time(11, 10), slot=2, week_parity="both", subject_id=subject.id, lesson_type="lecture", valid_from=semester.start_date, valid_to=semester.end_date, status="published")
    db.add(lesson); db.commit()
    return semester, lesson


@pytest.mark.parametrize("kind,suffix", [("cancel", "отменена"), ("move", "перенесена на 17 ноября (вт), 4 пара"), ("replace", "изменения: ауд. — → 305"), ("add", "дополнительная пара")])
def test_override_texts_stream_and_undo(db, kind, suffix):
    group_list = groups(db)
    semester, source = make_lesson(db, group_list[0])
    make_lesson(db, group_list[1])
    data = dict(kind=kind, date=DAY, group_ids=[g.id for g in group_list], source_lesson_id=source.id)
    if kind == "move": data.update(target_date=DAY + timedelta(days=1), slot=4)
    if kind == "replace": data.update(room="305", subject="Математика", teacher="")
    if kind == "add": data.update(subject="Программирование", slot=5)
    _, created = overrides.create_overrides(db, semester, OverrideIn(**data), "admin", DAY)
    assert len(rows(db)) == 2
    assert all(row.text.endswith(suffix) for row in rows(db))
    assert all(row.text.startswith("16 ноября (пн), ") for row in rows(db))
    overrides.delete_override(db, created[0].id, True)
    assert len(rows(db)) == 4
    assert all("изменение отменено, пара по обычному расписанию" in row.text for row in rows(db)[2:])
    assert [row.ref_id for row in rows(db)[:2]] == [row.ref_id for row in rows(db)[2:]]


def test_override_commit_failure_rolls_back_change_and_queue(db, monkeypatch):
    semester, lesson = make_lesson(db, groups(db)[0])
    def fail():
        db.flush()
        raise RuntimeError("сбой")
    monkeypatch.setattr(db, "commit", fail)
    with pytest.raises(RuntimeError):
        overrides.create_overrides(db, semester, OverrideIn(kind="cancel", date=DAY, group_ids=[lesson.group_id], source_lesson_id=lesson.id), "admin", DAY)
    db.rollback()
    assert rows(db) == []
    assert db.scalar(select(func.count(LessonOverride.id))) == 0


def test_exam_create_patch_cancel_restore_delete_and_old_groups(db):
    first, second = groups(db)
    item = exams.create_event(db, ExamCreate(kind="retake", date=DAY, start_time=time(15, 15), subject="Информатика", room="132", group_ids=[first.id]))
    exams.patch_event(db, item.id, ExamPatch(date=DAY + timedelta(days=1), room="132а", group_ids=[second.id]))
    assert {row.group_id for row in rows(db)[1:]} == {first.id, second.id}
    assert all("перенесена с 16 ноября (пн)" in row.text and "аудитория 132 → 132а" in row.text for row in rows(db)[1:])
    exams.cancel_event(db, item.id, True)
    exams.cancel_event(db, item.id, False)
    exams.delete_event(db, item.id)
    assert [row.action for row in rows(db)] == ["created", "changed", "changed", "changed", "changed", "removed"]
    assert rows(db)[0].text == "Пересдача 16 ноября (пн), 15:15 — Информатика: добавлена"
    assert rows(db)[-3].text.endswith("отменена")
    assert rows(db)[-2].text.endswith("восстановлена")
    assert rows(db)[-1].text.endswith("удалена")


@pytest.mark.parametrize("direction,number,pending", [("МПИ", 11, False), ("МПИ", 12, True), ("МПИ", 13, True), ("ПИ", 12, False)])
def test_pending_empty_week(db, direction, number, pending):
    group = groups(db)[0]; group.direction = direction
    semester = db.scalars(select(Semester)).one()
    info, days = schedule.build_week_schedule(db, group, semester, number, DAY)
    assert info.schedule_pending is pending
    assert all(not day["lessons"] for day in days)


def test_pending_with_permanent_and_added_lessons(db):
    group = groups(db)[1]
    semester, lesson = make_lesson(db, group)
    assert not schedule.build_week_schedule(db, group, semester, 12, DAY)[0].schedule_pending
    db.delete(lesson); db.commit()
    overrides.create_overrides(db, semester, OverrideIn(kind="add", date=DAY, group_ids=[group.id], subject="Алгоритмы", slot=3), "admin", DAY)
    assert not schedule.build_week_schedule(db, group, semester, 12, DAY)[0].schedule_pending


def test_replacing_override_keeps_only_the_latest_change(db):
    semester, lesson = make_lesson(db, groups(db)[0])
    for room in ("214", "305"):
        overrides.create_overrides(db, semester, OverrideIn(kind="replace", date=DAY, group_ids=[lesson.group_id], source_lesson_id=lesson.id, room=room), "admin", DAY)
    worker.process_schedule_changes(db, datetime.now(timezone.utc) + timedelta(minutes=3))
    body = db.scalars(select(Message)).one().body
    assert body == "16 ноября (пн), 2 пара — Математика: изменения: ауд. — → 305"


def test_past_override_and_exam_do_not_enqueue(db):
    semester, lesson = make_lesson(db, groups(db)[0])
    past = DAY - timedelta(days=7)
    overrides.create_overrides(db, semester, OverrideIn(kind="cancel", date=past, group_ids=[lesson.group_id], source_lesson_id=lesson.id), "admin", DAY)
    exams.create_event(db, ExamCreate(kind="retake", date=past, subject="История", group_ids=[lesson.group_id]))
    assert rows(db) == []


def test_exam_noop_and_failed_commit(db, monkeypatch):
    item = exams.create_event(db, ExamCreate(kind="session", date=DAY, subject="История", group_ids=[groups(db)[0].id]))
    exams.patch_event(db, item.id, ExamPatch(subject="История"))
    exams.cancel_event(db, item.id, False)
    assert len(rows(db)) == 1
    def fail():
        db.flush()
        raise RuntimeError("сбой")
    monkeypatch.setattr(db, "commit", fail)
    with pytest.raises(RuntimeError):
        exams.patch_event(db, item.id, ExamPatch(room="305"))
    db.rollback()
    assert len(rows(db)) == 1
    assert db.get(type(item), item.id).room is None


def test_worker_does_not_cancel_different_sources_and_sends_late_undo(db):
    group_id = groups(db)[0].id
    add(db)
    schedule_changes.record(db, group_id=group_id, source="exam", ref_id=1, action="removed", day=DAY, text="Удалён экзамен", now=NOW)
    db.commit()
    worker.process_schedule_changes(db, NOW + timedelta(minutes=3))
    assert db.scalars(select(Message)).one().body == "Изменение\nУдалён экзамен"
    schedule_changes.record(db, group_id=group_id, source="override", ref_id=1, action="removed", day=DAY, text="Изменение отменено", now=NOW)
    db.commit()
    worker.process_schedule_changes(db, NOW + timedelta(minutes=3))
    assert len(list(db.scalars(select(Message)))) == 2
