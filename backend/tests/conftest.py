import os
import unicodedata
from collections.abc import AsyncIterator
from pathlib import Path

# База для тестов — отдельный SQLite-файл, настройки читаются при импорте app.core.db.
TEST_DB = Path(__file__).parent / "test_api.db"
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{TEST_DB.as_posix()}"
os.environ["ADMIN_LOGIN"] = "admin"
os.environ["ADMIN_PASSWORD"] = "secret"
os.environ["JWT_SECRET"] = "test-secret"

import pytest  # noqa: E402
from httpx import AsyncClient  # noqa: E402
from sqlalchemy import select  # noqa: E402

from app.core.db import SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Base, Semester  # noqa: E402
from app.services.importer import import_workbook  # noqa: E402
from tests import asgi_client  # noqa: E402

EXCEL_NAME = "Расписание_ИИТ_1_сем_26_27_уч_г_РАБОЧИЙ_ВАРИАНТ.xlsx"


def _find_excel() -> Path:
    """Файл из Telegram/macOS приходит с «Й» в разложенной форме (И + кратка) — сравниваем по NFC."""
    root = Path(__file__).resolve().parents[2]
    wanted = unicodedata.normalize("NFC", EXCEL_NAME)
    for candidate in root.glob("*.xlsx"):
        if unicodedata.normalize("NFC", candidate.name) == wanted:
            return candidate
    return root / EXCEL_NAME


EXCEL = _find_excel()


@pytest.fixture(scope="session")
async def db_schema():
    """Пустая база со схемой. Нужна тестам, которым не нужен файл расписания."""
    TEST_DB.unlink(missing_ok=True)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    yield

    await engine.dispose()
    TEST_DB.unlink(missing_ok=True)


@pytest.fixture(scope="session")
async def filled_db(db_schema):
    """Заливает в базу расписание из реального файла."""
    if not EXCEL.exists():
        pytest.skip(f"нет файла расписания: {EXCEL}")

    from app.cli import seed_semester
    from datetime import date

    await seed_semester("1 семестр 2026/27", date(2026, 9, 1), 18, "odd")

    async with SessionLocal() as session:
        semester = await session.scalar(select(Semester).where(Semester.is_active.is_(True)))
        await import_workbook(session, str(EXCEL), semester, file_name=EXCEL.name)


@pytest.fixture
async def client(filled_db) -> AsyncIterator[AsyncClient]:
    async with asgi_client(app) as client:
        yield client


@pytest.fixture
async def bare_client(db_schema) -> AsyncIterator[AsyncClient]:
    """Клиент без расписания из Excel: группы тесты заводят сами."""
    async with asgi_client(app) as client:
        yield client


TEST_GROUPS = [
    ("ТЕСТ ПИ 991", 1, "ПИ"),
    ("ТЕСТ ПИ 992", 2, "ПИ"),
    ("ТЕСТ БИ 991", 1, "БИ"),
]


@pytest.fixture
async def test_groups(db_schema) -> dict[str, int]:
    """Свои группы с префиксом «ТЕСТ»; после теста удаляются вместе со студентами."""
    from sqlalchemy import delete

    from app.models import Group, User

    async with SessionLocal() as session:
        groups = [Group(name=name, course=course, direction=direction) for name, course, direction in TEST_GROUPS]
        session.add_all(groups)
        await session.commit()
        ids = {group.name: group.id for group in groups}

    yield ids

    async with SessionLocal() as session:
        await session.execute(delete(User))
        await session.execute(delete(Group).where(Group.name.like("ТЕСТ %")))
        await session.commit()


@pytest.fixture
async def bare_admin_headers(bare_client) -> dict[str, str]:
    response = await bare_client.post("/api/v1/auth/admin/login", json={"login": "admin", "password": "secret"})
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


@pytest.fixture
async def group_ids(client) -> dict[str, int]:
    return {group["name"]: group["id"] for group in (await client.get("/api/v1/groups")).json()}


@pytest.fixture
async def admin_headers(client) -> dict[str, str]:
    response = await client.post("/api/v1/auth/admin/login", json={"login": "admin", "password": "secret"})
    return {"Authorization": f"Bearer {response.json()['access_token']}"}
