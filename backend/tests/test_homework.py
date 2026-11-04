"""Групповая домашка: редакторы, версии и личное выполнение."""

from datetime import date

from sqlalchemy import delete

from app.core.db import SessionLocal
import pytest

from app.models import GroupEditor, GroupHomework, HomeworkCompletion, HomeworkRevision, User

API = "/api/v1"


@pytest.fixture(autouse=True)
def _clean_homework(db_schema):
    yield
    with SessionLocal() as session:
        session.execute(delete(HomeworkCompletion))
        session.execute(delete(HomeworkRevision))
        session.execute(delete(GroupHomework))
        session.execute(delete(GroupEditor))
        session.commit()


def student(client, group_id, name, device):
    response = client.post(f"{API}/auth/student/register", json={"full_name": name, "group_id": group_id, "device_key": device})
    assert response.status_code == 200, response.text
    body = response.json()
    return body["profile"]["id"], {"Authorization": f"Bearer {body['access_token']}"}


def test_редактор_создаёт_домашку_и_студент_отмечает_выполнение(bare_client, bare_admin_headers, test_groups):
    group_id = test_groups["ТЕСТ ПИ 991"]
    user_id, headers = student(bare_client, group_id, "Староста Тестова", "homework-editor-000001")
    assigned = bare_client.post(f"{API}/admin/groups/{group_id}/editors", json={"user_id": user_id, "is_primary": True}, headers=bare_admin_headers)
    assert assigned.status_code == 200, assigned.text

    created = bare_client.post(f"{API}/me/homework", json={
        "title": "Лабораторная №2", "body": "Сделать задачи 1–5", "lesson_date": "2026-11-10",
        "due_date": "2026-11-12", "source": "from_class",
    }, headers=headers)
    assert created.status_code == 201, created.text
    homework = created.json()
    assert homework["created_by"] == user_id
    assert homework["completed_by_me"] is False

    listed = bare_client.get(f"{API}/me/homework", params={"start": "2026-11-09", "end": "2026-11-15"}, headers=headers).json()
    assert listed["can_edit"] is True
    assert listed["items"][0]["title"] == "Лабораторная №2"

    done = bare_client.post(f"{API}/me/homework/{homework['id']}/complete", headers=headers)
    assert done.status_code == 200
    assert done.json()["completed_by_me"] is True


def test_обычный_студент_не_может_публиковать(bare_client, bare_admin_headers, test_groups):
    group_id = test_groups["ТЕСТ ПИ 991"]
    _, headers = student(bare_client, group_id, "Обычный Тестов", "homework-student-0001")
    response = bare_client.post(f"{API}/me/homework", json={"title": "Чужая запись", "body": ""}, headers=headers)
    assert response.status_code == 403


def test_версия_защищает_от_затирания(bare_client, bare_admin_headers, test_groups):
    group_id = test_groups["ТЕСТ ПИ 991"]
    user_id, headers = student(bare_client, group_id, "Редактор Версий", "homework-version-0001")
    bare_client.post(f"{API}/admin/groups/{group_id}/editors", json={"user_id": user_id}, headers=bare_admin_headers)
    item = bare_client.post(f"{API}/me/homework", json={"title": "Исходное", "body": ""}, headers=headers).json()
    body = {"title": "Новое", "version": item["version"]}
    assert bare_client.patch(f"{API}/me/homework/{item['id']}", json=body, headers=headers).status_code == 200
    stale = bare_client.patch(f"{API}/me/homework/{item['id']}", json={"title": "Старое", "version": item["version"]}, headers=headers)
    assert stale.status_code == 409

