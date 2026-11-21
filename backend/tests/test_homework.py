"""Групповая домашка: редакторы, версии и личное выполнение."""

from datetime import date

from sqlalchemy import delete

from app.core.db import SessionLocal
import pytest
from tests.moodle_helpers import login_student

from app.models import GroupEditor, GroupHomework, HomeworkCompletion, HomeworkRevision, User

API = "/api/v1"


@pytest.fixture(autouse=True)
async def _clean_homework(db_schema):
    yield
    async with SessionLocal() as session:
        await session.execute(delete(HomeworkCompletion))
        await session.execute(delete(HomeworkRevision))
        await session.execute(delete(GroupHomework))
        await session.execute(delete(GroupEditor))
        await session.commit()


async def student(client, group_id, name, device):
    response = await login_student(client, group_id, name, device)
    assert response.status_code == 200, response.text
    body = response.json()
    return body["profile"]["id"], {"Authorization": f"Bearer {body['access_token']}"}


async def test_редактор_создаёт_домашку_и_студент_отмечает_выполнение(bare_client, bare_admin_headers, test_groups):
    group_id = test_groups["ТЕСТ ПИ 991"]
    user_id, headers = await student(bare_client, group_id, "Староста Тестова", "homework-editor-000001")
    assigned = await bare_client.post(f"{API}/admin/groups/{group_id}/editors", json={"user_id": user_id, "is_primary": True}, headers=bare_admin_headers)
    assert assigned.status_code == 200, assigned.text

    created = await bare_client.post(f"{API}/me/homework", json={
        "title": "Лабораторная №2", "body": "Сделать задачи 1–5", "lesson_date": "2026-11-10",
        "due_date": "2026-11-12", "source": "from_class",
    }, headers=headers)
    assert created.status_code == 201, created.text
    homework = created.json()
    assert homework["created_by"] == user_id
    assert homework["completed_by_me"] is False

    listed = (await bare_client.get(f"{API}/me/homework", params={"start": "2026-11-09", "end": "2026-11-15"}, headers=headers)).json()
    assert listed["can_edit"] is True
    assert listed["items"][0]["title"] == "Лабораторная №2"

    done = await bare_client.post(f"{API}/me/homework/{homework['id']}/complete", headers=headers)
    assert done.status_code == 200
    assert done.json()["completed_by_me"] is True


async def test_обычный_студент_не_может_публиковать(bare_client, bare_admin_headers, test_groups):
    group_id = test_groups["ТЕСТ ПИ 991"]
    _, headers = await student(bare_client, group_id, "Обычный Тестов", "homework-student-0001")
    response = await bare_client.post(f"{API}/me/homework", json={"title": "Чужая запись", "body": ""}, headers=headers)
    assert response.status_code == 403


async def test_версия_защищает_от_затирания(bare_client, bare_admin_headers, test_groups):
    group_id = test_groups["ТЕСТ ПИ 991"]
    user_id, headers = await student(bare_client, group_id, "Редактор Версий", "homework-version-0001")
    await bare_client.post(f"{API}/admin/groups/{group_id}/editors", json={"user_id": user_id}, headers=bare_admin_headers)
    item = (await bare_client.post(f"{API}/me/homework", json={"title": "Исходное", "body": ""}, headers=headers)).json()
    body = {"title": "Новое", "version": item["version"]}
    assert (await bare_client.patch(f"{API}/me/homework/{item['id']}", json=body, headers=headers)).status_code == 200
    stale = await bare_client.patch(f"{API}/me/homework/{item['id']}", json={"title": "Старое", "version": item["version"]}, headers=headers)
    assert stale.status_code == 409

