"""Флаг недели и автоматические сообщения проходят через публичный контракт."""
from datetime import timedelta

import pytest
from tests import asgi_client
from sqlalchemy import select

from app.api.v1 import public
from app.core.db import get_db
from app.core.security import issue_token
from app.main import app
from app.models import Message, Semester
from app.schemas.message import MessageIn
from app.services import messages, worker
from tests.test_schedule_changes import DAY, NOW, add, db, groups


@pytest.fixture
async def client(db, monkeypatch):
    monkeypatch.setattr(public, "_today", lambda: DAY)
    app.dependency_overrides[get_db] = lambda: db
    async with asgi_client(app) as client:
        yield client
    app.dependency_overrides.pop(get_db, None)


async def test_week_pending_api(db, client):
    group = (await groups(db))[1]
    for number, pending in [(11, False), (12, True), (13, True)]:
        response = await client.get(f"/api/v1/groups/{group.id}/schedule?week={number}")
        assert response.status_code == 200, response.text
        assert response.json()["week"]["schedule_pending"] is pending
    assert (await client.get(f"/api/v1/groups/{group.id}/schedule")).json()["week"]["schedule_pending"]
    bachelor = (await groups(db))[0]
    assert not (await client.get(f"/api/v1/groups/{bachelor.id}/schedule")).json()["week"]["schedule_pending"]


async def test_admin_filter_detail_and_permissions(db, client):
    await add(db); await db.commit()
    await worker.process_schedule_changes(db, NOW + timedelta(minutes=3))
    automatic = (await db.scalars(select(Message))).one()
    manual = await messages.create_message(db, MessageIn(title="Обычное сообщение", body="Текст", target={"type": "all"}), "admin", NOW)
    headers = {"Authorization": f"Bearer {issue_token('admin', 'admin', 1)[0]}"}
    url = "/api/v1/admin/messages"
    assert [item["id"] for item in (await client.get(url, headers=headers)).json()] == [manual.id]
    shown = (await client.get(url + "?include_automatic=true", headers=headers)).json()
    assert {item["id"] for item in shown} == {manual.id, automatic.id}
    item = (await client.get(f"{url}/{automatic.id}", headers=headers)).json()
    assert item["created_by"] == "system" and item["title"] == "Изменение расписания"
    assert "push" in item and "recipients" in item
    assert (await client.get(url + "?include_automatic=true")).status_code == 401
    student = {"Authorization": f"Bearer {issue_token('1', 'student', 1)[0]}"}
    assert (await client.get(url + "?include_automatic=true", headers=student)).status_code == 403
