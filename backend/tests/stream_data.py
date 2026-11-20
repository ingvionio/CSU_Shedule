from datetime import date, time

import pytest
from sqlalchemy import event
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models import Base, Group, Lesson, Room, Semester, Subject
from app.services.importer import ensure_reference_data


@pytest.fixture
async def stream_factory(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{(tmp_path / 'stream.db').as_posix()}")

    @event.listens_for(engine.sync_engine, "connect")
    def foreign_keys(connection, _):
        connection.execute("PRAGMA foreign_keys=ON")

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as db:
        semester = Semester(title="Тест потока", start_date=date(2026, 8, 31),
                            end_date=date(2027, 1, 3), total_weeks=18, is_active=True)
        db.add(semester)
        await ensure_reference_data(db)
        groups = [Group(name=name, course=course, direction=direction) for name, course, direction in [
            ("ИТ1-ПрИб-11", 1, "ПрИ"), ("ИТ1-ПИб-11", 1, "ПИ"),
            ("МИТ 101", 1, "МИТ"), ("ПИ 201", 2, "ПИ"), ("ИТ1-БИб-11", 1, "БИ"),
        ]]
        db.add_all(groups)
        subject, room = Subject(name="Общая пара"), Room(name="325")
        db.add_all([subject, room])
        await db.flush()
        for group in groups[:2]:
            db.add(Lesson(semester_id=semester.id, group_id=group.id, weekday=1,
                          start_time=time(8), end_time=time(9, 30), slot=1,
                          subject=subject, lesson_type="lecture", room=room,
                          valid_from=semester.start_date))
            own_subject = Subject(name=f"Только {group.name}")
            db.add(Lesson(semester_id=semester.id, group_id=group.id, weekday=2,
                          start_time=time(8), end_time=time(9, 30), slot=1,
                          subject=own_subject, lesson_type="lecture", valid_from=semester.start_date))
        await db.commit()

    try:
        yield factory
    finally:
        await engine.dispose()
