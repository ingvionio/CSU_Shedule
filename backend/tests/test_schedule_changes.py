from sqlalchemy.ext.asyncio import create_async_engine
"""Уведомления расписания: транзакции, накопление и готовая неделя."""
from datetime import date, datetime, time, timedelta, timezone

import pytest
from sqlalchemy import event, func, select
from sqlalchemy.ext.asyncio import AsyncSession

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
async def db(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'changes.db'}")
    @event.listens_for(engine.sync_engine, "connect")
    def foreign_keys(connection, _):
        connection.execute("PRAGMA foreign_keys=ON")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    monkeypatch.setattr(schedule_changes, "today", lambda: DAY)
    monkeypatch.setattr(get_settings(), "schedule_change_delay_seconds", 120)
    monkeypatch.setattr(get_settings(), "vapid_public_key", "public")
    monkeypatch.setattr(get_settings(), "vapid_private_key", "private")
    monkeypatch.setattr(get_settings(), "fcm_credentials_file", "")
    async with AsyncSession(engine, expire_on_commit=False) as db:
        semester = Semester(title="Осень", start_date=date(2026, 9, 1), end_date=date(2027, 1, 3), total_weeks=18, is_active=True)
        db.add_all([semester, Group(name="ПИ 101", course=1, direction="ПИ"), Group(name="МПИ 101", course=1, direction="МПИ")])
        await ensure_reference_data(db)
        await db.commit()
        yield db
    await engine.dispose()


async def groups(db):
    return list(await db.scalars(select(Group).order_by(Group.id)))


async def rows(db):
    return list(await db.scalars(select(ScheduleChange).order_by(ScheduleChange.id)))


async def add(db, group_id=None, **values):
    return await schedule_changes.record(db, group_id=group_id or (await groups(db))[0].id, source="override", action="created", ref_id=1, day=DAY, text="Изменение", now=NOW, **values)


async def test_record_no_commit_past_and_rollback(db):
    await add(db)
    await db.flush()
    assert len(await rows(db)) == 1
    await db.rollback()
    assert await rows(db) == []
    await schedule_changes.record(db, group_id=(await groups(db))[0].id, source="exam", action="created", day=DAY - timedelta(days=1), text="Прошлое", now=NOW)
    await db.commit()
    assert await rows(db) == []


async def test_worker_debounce_grouping_outbox_and_repeat(db):
    first, second = await groups(db)
    user = User(full_name="Студент", group_id=first.id, device_key_hash="changes-device")
    db.add(user); await db.flush()
    db.add(PushSubscription(user_id=user.id, endpoint="https://push.invalid/1", p256dh="key", auth="auth"))
    await add(db, first.id)
    await add(db, second.id)
    await db.commit()
    assert await worker.process_schedule_changes(db, NOW + timedelta(seconds=119)) == 0
    await schedule_changes.record(db, group_id=first.id, source="import", action="uploaded", text="Расписание обновлено", now=NOW + timedelta(seconds=60))
    await db.commit()
    assert await worker.process_schedule_changes(db, NOW + timedelta(seconds=121)) == 1
    assert await worker.process_schedule_changes(db, NOW + timedelta(seconds=181)) == 1
    assert await worker.process_schedule_changes(db, NOW + timedelta(minutes=10)) == 0
    sent = list(await db.scalars(select(Message)))
    assert len(sent) == 2 and all(m.created_by == "system" and m.importance == "normal" for m in sent)
    assert await db.scalar(select(func.count(PushDelivery.id))) == 1
    assert await db.scalar(select(func.count(MessageRecipient.id))) == 1
    assert all(row.processed_at and row.message_id for row in await rows(db))


async def test_worker_cancels_created_changed_removed_and_handles_reused_ref(db):
    group_id = (await groups(db))[0].id
    for action in ["created", "changed", "removed"]:
        await schedule_changes.record(db, group_id=group_id, source="exam", ref_id=7, action=action, day=DAY, text=action, now=NOW)
    await db.commit()
    await worker.process_schedule_changes(db, NOW + timedelta(minutes=3))
    assert await db.scalar(select(func.count(Message.id))) == 0
    assert all(row.processed_at and row.message_id is None for row in await rows(db))
    for action in ["created", "removed", "created"]:
        await schedule_changes.record(db, group_id=group_id, source="override", ref_id=7, action=action, day=DAY, text=action, now=NOW)
    await db.commit()
    await worker.process_schedule_changes(db, NOW + timedelta(minutes=3))
    assert (await db.scalars(select(Message))).one().body == "created"


async def test_worker_sorts_limits_and_upload_title(db):
    group_id = (await groups(db))[0].id
    for n in reversed(range(12)):
        await schedule_changes.record(db, group_id=group_id, source="exam", ref_id=n, action="changed", day=DAY + timedelta(days=n), text=f"Строка {n}", now=NOW)
    await db.commit()
    await worker.process_schedule_changes(db, NOW + timedelta(minutes=3))
    message = (await db.scalars(select(Message))).one()
    assert message.title == "Изменение расписания"
    assert message.body.splitlines() == [f"Строка {n}" for n in range(10)] + ["и ещё 2"]
    await schedule_changes.record(db, group_id=group_id, source="import", action="uploaded", text="Опубликовано расписание сессии", now=NOW)
    await db.commit()
    await worker.process_schedule_changes(db, NOW + timedelta(minutes=3))
    assert (await db.scalars(select(Message).order_by(Message.id.desc()))).first().title == "Опубликовано расписание сессии"


async def test_worker_commit_failure_rolls_back_message_push_and_marks(db, monkeypatch):
    user = User(full_name="Студент", group_id=(await groups(db))[0].id, device_key_hash="rollback-device")
    db.add(user); await db.flush()
    db.add(PushSubscription(user_id=user.id, endpoint="https://push.invalid/rollback", p256dh="key", auth="auth"))
    await add(db); await db.commit()
    async def fail():
        await db.flush()
        assert await db.scalar(select(func.count(Message.id))) == 1
        assert await db.scalar(select(func.count(PushDelivery.id))) == 1
        assert all(row.processed_at for row in await rows(db))
        raise RuntimeError("сбой записи")
    monkeypatch.setattr(db, "commit", fail)
    with pytest.raises(RuntimeError):
        await worker.process_schedule_changes(db, NOW + timedelta(minutes=3))
    await db.rollback()
    assert (await rows(db))[0].processed_at is None
    assert await db.scalar(select(func.count(Message.id))) == 0
    assert await db.scalar(select(func.count(PushDelivery.id))) == 0


async def test_worker_locks_whole_group_and_rows(db):
    from sqlalchemy.dialects.postgresql import dialect
    await add(db); await db.commit()
    statements = []
    def capture(context):
        if context.is_select and context.statement._for_update_arg is not None:
            statements.append(str(context.statement.compile(dialect=dialect())))
    event.listen(db.sync_session, "do_orm_execute", capture)
    try:
        await worker.process_schedule_changes(db, NOW + timedelta(minutes=3))
    finally:
        event.remove(db.sync_session, "do_orm_execute", capture)
    assert any("FROM groups" in sql and "FOR NO KEY UPDATE SKIP LOCKED" in sql for sql in statements)
    assert any("FROM schedule_changes" in sql and "FOR UPDATE SKIP LOCKED" in sql for sql in statements)


async def make_lesson(db, group):
    semester = (await db.scalars(select(Semester))).one()
    subject = await db.scalar(select(Subject).where(Subject.name == "Математика"))
    if subject is None:
        subject = Subject(name="Математика"); db.add(subject); await db.flush()
    lesson = Lesson(semester_id=semester.id, group_id=group.id, weekday=1, start_time=time(9, 40), end_time=time(11, 10), slot=2, week_parity="both", subject_id=subject.id, lesson_type="lecture", valid_from=semester.start_date, valid_to=semester.end_date, status="published")
    db.add(lesson); await db.commit()
    return semester, lesson


@pytest.mark.parametrize("kind,suffix", [("cancel", "отменена"), ("move", "перенесена на 17 ноября (вт), 4 пара"), ("replace", "изменения: ауд. — → 305"), ("add", "дополнительная пара")])
async def test_override_texts_stream_and_undo(db, kind, suffix):
    group_list = await groups(db)
    semester, source = await make_lesson(db, group_list[0])
    await make_lesson(db, group_list[1])
    data = dict(kind=kind, date=DAY, group_ids=[g.id for g in group_list], source_lesson_id=source.id)
    if kind == "move": data.update(target_date=DAY + timedelta(days=1), slot=4)
    if kind == "replace": data.update(room="305", subject="Математика", teacher="")
    if kind == "add": data.update(subject="Программирование", slot=5)
    _, created = await overrides.create_overrides(db, semester, OverrideIn(**data), "admin", DAY)
    assert len(await rows(db)) == 2
    assert all(row.text.endswith(suffix) for row in await rows(db))
    assert all(row.text.startswith("16 ноября (пн), ") for row in await rows(db))
    await overrides.delete_override(db, created[0].id, True)
    assert len(await rows(db)) == 4
    assert all("изменение отменено, пара по обычному расписанию" in row.text for row in (await rows(db))[2:])
    assert [row.ref_id for row in (await rows(db))[:2]] == [row.ref_id for row in (await rows(db))[2:]]


async def test_override_commit_failure_rolls_back_change_and_queue(db, monkeypatch):
    semester, lesson = await make_lesson(db, (await groups(db))[0])
    async def fail():
        await db.flush()
        raise RuntimeError("сбой")
    monkeypatch.setattr(db, "commit", fail)
    with pytest.raises(RuntimeError):
        await overrides.create_overrides(db, semester, OverrideIn(kind="cancel", date=DAY, group_ids=[lesson.group_id], source_lesson_id=lesson.id), "admin", DAY)
    await db.rollback()
    assert await rows(db) == []
    assert await db.scalar(select(func.count(LessonOverride.id))) == 0


async def test_exam_create_patch_cancel_restore_delete_and_old_groups(db):
    first, second = await groups(db)
    item = await exams.create_event(db, ExamCreate(kind="retake", date=DAY, start_time=time(15, 15), subject="Информатика", room="132", group_ids=[first.id]))
    await exams.patch_event(db, item.id, ExamPatch(date=DAY + timedelta(days=1), room="132а", group_ids=[second.id]))
    assert {row.group_id for row in (await rows(db))[1:]} == {first.id, second.id}
    assert all("перенесена с 16 ноября (пн)" in row.text and "аудитория 132 → 132а" in row.text for row in (await rows(db))[1:])
    await exams.cancel_event(db, item.id, True)
    await exams.cancel_event(db, item.id, False)
    await exams.delete_event(db, item.id)
    assert [row.action for row in await rows(db)] == ["created", "changed", "changed", "changed", "changed", "removed"]
    assert (await rows(db))[0].text == "Пересдача 16 ноября (пн), 15:15 — Информатика: добавлена"
    assert (await rows(db))[-3].text.endswith("отменена")
    assert (await rows(db))[-2].text.endswith("восстановлена")
    assert (await rows(db))[-1].text.endswith("удалена")


@pytest.mark.parametrize("direction,number,pending", [("МПИ", 11, False), ("МПИ", 12, True), ("МПИ", 13, True), ("ПИ", 12, False)])
async def test_pending_empty_week(db, direction, number, pending):
    group = (await groups(db))[0]; group.direction = direction
    semester = (await db.scalars(select(Semester))).one()
    info, days = await schedule.build_week_schedule(db, group, semester, number, DAY)
    assert info.schedule_pending is pending
    assert all(not day["lessons"] for day in days)


async def test_pending_with_permanent_and_added_lessons(db):
    group = (await groups(db))[1]
    semester, lesson = await make_lesson(db, group)
    assert not (await schedule.build_week_schedule(db, group, semester, 12, DAY))[0].schedule_pending
    await db.delete(lesson); await db.commit()
    await overrides.create_overrides(db, semester, OverrideIn(kind="add", date=DAY, group_ids=[group.id], subject="Алгоритмы", slot=3), "admin", DAY)
    assert not (await schedule.build_week_schedule(db, group, semester, 12, DAY))[0].schedule_pending


async def test_replacing_override_keeps_only_the_latest_change(db):
    semester, lesson = await make_lesson(db, (await groups(db))[0])
    for room in ("214", "305"):
        await overrides.create_overrides(db, semester, OverrideIn(kind="replace", date=DAY, group_ids=[lesson.group_id], source_lesson_id=lesson.id, room=room), "admin", DAY)
    await worker.process_schedule_changes(db, datetime.now(timezone.utc) + timedelta(minutes=3))
    body = (await db.scalars(select(Message))).one().body
    assert body == "16 ноября (пн), 2 пара — Математика: изменения: ауд. — → 305"


async def test_past_override_and_exam_do_not_enqueue(db):
    semester, lesson = await make_lesson(db, (await groups(db))[0])
    past = DAY - timedelta(days=7)
    await overrides.create_overrides(db, semester, OverrideIn(kind="cancel", date=past, group_ids=[lesson.group_id], source_lesson_id=lesson.id), "admin", DAY)
    await exams.create_event(db, ExamCreate(kind="retake", date=past, subject="История", group_ids=[lesson.group_id]))
    assert await rows(db) == []


async def test_exam_noop_and_failed_commit(db, monkeypatch):
    item = await exams.create_event(db, ExamCreate(kind="session", date=DAY, subject="История", group_ids=[(await groups(db))[0].id]))
    await exams.patch_event(db, item.id, ExamPatch(subject="История"))
    await exams.cancel_event(db, item.id, False)
    assert len(await rows(db)) == 1
    async def fail():
        await db.flush()
        raise RuntimeError("сбой")
    monkeypatch.setattr(db, "commit", fail)
    item_id = item.id
    with pytest.raises(RuntimeError):
        await exams.patch_event(db, item_id, ExamPatch(room="305"))
    await db.rollback()
    assert len(await rows(db)) == 1
    assert (await db.get(type(item), item_id)).room is None


async def test_worker_does_not_cancel_different_sources_and_sends_late_undo(db):
    group_id = (await groups(db))[0].id
    await add(db)
    await schedule_changes.record(db, group_id=group_id, source="exam", ref_id=1, action="removed", day=DAY, text="Удалён экзамен", now=NOW)
    await db.commit()
    await worker.process_schedule_changes(db, NOW + timedelta(minutes=3))
    assert (await db.scalars(select(Message))).one().body == "Изменение\nУдалён экзамен"
    await schedule_changes.record(db, group_id=group_id, source="override", ref_id=1, action="removed", day=DAY, text="Изменение отменено", now=NOW)
    await db.commit()
    await worker.process_schedule_changes(db, NOW + timedelta(minutes=3))
    assert len(list(await db.scalars(select(Message)))) == 2
