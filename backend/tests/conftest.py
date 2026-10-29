import os
from pathlib import Path

# База для тестов — отдельный SQLite-файл, настройки читаются при импорте app.core.db.
TEST_DB = Path(__file__).parent / "test_api.db"
os.environ["DATABASE_URL"] = f"sqlite+pysqlite:///{TEST_DB.as_posix()}"
os.environ["ADMIN_LOGIN"] = "admin"
os.environ["ADMIN_PASSWORD"] = "secret"
os.environ["JWT_SECRET"] = "test-secret"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import select  # noqa: E402

from app.core.db import SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Base, Semester  # noqa: E402
from app.services.importer import import_workbook  # noqa: E402

EXCEL = Path(__file__).resolve().parents[2] / "Расписание_ИИТ_1_сем_26_27_уч_г_РАБОЧИЙ_ВАРИАНТ.xlsx"


@pytest.fixture(scope="session")
def db_schema():
    """Пустая база со схемой. Нужна тестам, которым не нужен файл расписания."""
    TEST_DB.unlink(missing_ok=True)
    Base.metadata.create_all(engine)

    yield

    engine.dispose()
    TEST_DB.unlink(missing_ok=True)


@pytest.fixture(scope="session")
def filled_db(db_schema):
    """Заливает в базу расписание из реального файла."""
    if not EXCEL.exists():
        pytest.skip(f"нет файла расписания: {EXCEL}")

    from app.cli import seed_semester
    from datetime import date

    seed_semester("1 семестр 2026/27", date(2026, 9, 1), 18, "odd")

    with SessionLocal() as session:
        semester = session.scalar(select(Semester).where(Semester.is_active.is_(True)))
        import_workbook(session, str(EXCEL), semester, file_name=EXCEL.name)


@pytest.fixture
def client(filled_db) -> TestClient:
    return TestClient(app)


@pytest.fixture
def bare_client(db_schema) -> TestClient:
    """Клиент без расписания из Excel: группы тесты заводят сами."""
    return TestClient(app)


TEST_GROUPS = [
    ("ТЕСТ ПИ 991", 1, "ПИ"),
    ("ТЕСТ ПИ 992", 2, "ПИ"),
    ("ТЕСТ БИ 991", 1, "БИ"),
]


@pytest.fixture
def test_groups(db_schema) -> dict[str, int]:
    """Свои группы с префиксом «ТЕСТ»; после теста удаляются вместе со студентами."""
    from sqlalchemy import delete

    from app.models import Group, User

    with SessionLocal() as session:
        groups = [Group(name=name, course=course, direction=direction) for name, course, direction in TEST_GROUPS]
        session.add_all(groups)
        session.commit()
        ids = {group.name: group.id for group in groups}

    yield ids

    with SessionLocal() as session:
        session.execute(delete(User))
        session.execute(delete(Group).where(Group.name.like("ТЕСТ %")))
        session.commit()


@pytest.fixture
def bare_admin_headers(bare_client) -> dict[str, str]:
    response = bare_client.post("/api/v1/auth/admin/login", json={"login": "admin", "password": "secret"})
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


@pytest.fixture
def group_ids(client) -> dict[str, int]:
    return {group["name"]: group["id"] for group in client.get("/api/v1/groups").json()}


@pytest.fixture
def admin_headers(client) -> dict[str, str]:
    response = client.post("/api/v1/auth/admin/login", json={"login": "admin", "password": "secret"})
    return {"Authorization": f"Bearer {response.json()['access_token']}"}
