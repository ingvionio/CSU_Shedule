import os
from pathlib import Path

# База для тестов — отдельный SQLite-файл, настройки читаются при импорте app.core.db.
TEST_DB = Path(__file__).parent / "test_api.db"
os.environ["DATABASE_URL"] = f"sqlite+pysqlite:///{TEST_DB.as_posix()}"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import select  # noqa: E402

from app.core.db import SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Base, Semester  # noqa: E402
from app.services.importer import import_workbook  # noqa: E402

EXCEL = Path(__file__).resolve().parents[2] / "Расписание_ИИТ_1_сем_26_27_уч_г_РАБОЧИЙ_ВАРИАНТ.xlsx"


@pytest.fixture(scope="session")
def filled_db():
    """Разворачивает базу и заливает в неё расписание из реального файла."""
    if not EXCEL.exists():
        pytest.skip(f"нет файла расписания: {EXCEL}")

    TEST_DB.unlink(missing_ok=True)
    Base.metadata.create_all(engine)

    from app.cli import seed_semester
    from datetime import date

    seed_semester("1 семестр 2026/27", date(2026, 9, 1), 18, "odd")

    with SessionLocal() as session:
        semester = session.scalar(select(Semester).where(Semester.is_active.is_(True)))
        import_workbook(session, str(EXCEL), semester, file_name=EXCEL.name)

    yield

    engine.dispose()
    TEST_DB.unlink(missing_ok=True)


@pytest.fixture
def client(filled_db) -> TestClient:
    return TestClient(app)


@pytest.fixture
def group_ids(client) -> dict[str, int]:
    return {group["name"]: group["id"] for group in client.get("/api/v1/groups").json()}
