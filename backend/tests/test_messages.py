"""Рассылка: адресация, инбокс, прочтение и «Ознакомлен», напоминания, досылка."""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import delete, update

from app.core.db import SessionLocal
from app.models import Message, MessageRecipient
from app.services import push as push_service
from tests.moodle_helpers import login_student

API = "/api/v1"


@pytest.fixture(autouse=True)
async def _clean_messages(db_schema):
    yield
    async with SessionLocal() as session:
        await session.execute(delete(MessageRecipient))
        await session.execute(delete(Message))
        await session.commit()


@pytest.fixture
def pushed(monkeypatch) -> list[tuple[int, list[int], bool]]:
    calls: list[tuple[int, list[int], bool]] = []
    async def notify(message_id, user_ids, reminder):
        calls.append((message_id, user_ids, reminder))

    monkeypatch.setattr(push_service, "notify_message", notify)
    return calls


async def student(client, group_id, name, device):
    response = await login_student(client, group_id, name, device)
    assert response.status_code == 200, response.text
    body = response.json()
    return body["profile"]["id"], {"Authorization": f"Bearer {body['access_token']}"}


@pytest.fixture
async def students(bare_client, test_groups):
    """Аня и Борис в ПИ 1 курса, Вера в ПИ 2 курса, Глеб в БИ 1 курса."""
    return {
        "anya": await student(bare_client, test_groups["ТЕСТ ПИ 991"], "Аня Андреева", "device-anya-0000000"),
        "boris": await student(bare_client, test_groups["ТЕСТ ПИ 991"], "Борис Белов", "device-boris-000000"),
        "vera": await student(bare_client, test_groups["ТЕСТ ПИ 992"], "Вера Волкова", "device-vera-0000000"),
        "gleb": await student(bare_client, test_groups["ТЕСТ БИ 991"], "Глеб Громов", "device-gleb-0000000"),
    }


async def send(client, headers, target, importance="normal", title="Перенос пары"):
    response = await client.post(
        f"{API}/admin/messages",
        json={"title": title, "body": "Пара переносится на четверг.", "importance": importance, "target": target},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()


async def recipients(client, headers, message_id) -> set[str]:
    detail = (await client.get(f"{API}/admin/messages/{message_id}", headers=headers)).json()
    return {item["full_name"] for item in detail["recipients"]}


@pytest.mark.parametrize(
    ("target", "expected"),
    [
        ({"type": "all"}, {"Аня Андреева", "Борис Белов", "Вера Волкова", "Глеб Громов"}),
        ({"type": "course", "courses": [1]}, {"Аня Андреева", "Борис Белов", "Глеб Громов"}),
        ({"type": "direction", "directions": ["ПИ"]}, {"Аня Андреева", "Борис Белов", "Вера Волкова"}),
        ({"type": "direction", "directions": ["ПИ"], "courses": [2]}, {"Вера Волкова"}),
    ],
)
async def test_адресация(bare_client, bare_admin_headers, students, pushed, target, expected):
    message = await send(bare_client, bare_admin_headers, target)
    assert message["recipients_total"] == len(expected)
    assert await recipients(bare_client, bare_admin_headers, message["id"]) == expected


async def test_адресация_группе_и_студентам(bare_client, bare_admin_headers, students, test_groups, pushed):
    to_group = await send(bare_client, bare_admin_headers, {"type": "group", "group_ids": [test_groups["ТЕСТ БИ 991"]]})
    assert await recipients(bare_client, bare_admin_headers, to_group["id"]) == {"Глеб Громов"}
    assert to_group["target_title"] == "Группа ТЕСТ БИ 991"

    ids = [students["anya"][0], students["vera"][0]]
    personal = await send(bare_client, bare_admin_headers, {"type": "students", "user_ids": ids})
    assert await recipients(bare_client, bare_admin_headers, personal["id"]) == {"Аня Андреева", "Вера Волкова"}


async def test_пустая_адресация_отклоняется(bare_client, bare_admin_headers, students):
    response = await bare_client.post(
        f"{API}/admin/messages",
        json={"title": "x", "body": "y", "target": {"type": "group", "group_ids": []}},
        headers=bare_admin_headers,
    )
    assert response.status_code == 422


async def test_push_уходит_всем_кроме_неважных(bare_client, bare_admin_headers, students, pushed):
    normal = await send(bare_client, bare_admin_headers, {"type": "course", "courses": [2]})
    low = await send(bare_client, bare_admin_headers, {"type": "course", "courses": [2]}, importance="low")
    assert pushed[0] == (normal["id"], [students["vera"][0]], False)
    assert pushed[1] == (low["id"], [], False)


async def test_прочтение_обычного_сообщения(bare_client, bare_admin_headers, students, pushed):
    message = await send(bare_client, bare_admin_headers, {"type": "all"})
    _, anya = students["anya"]

    inbox = (await bare_client.get(f"{API}/me/messages", headers=anya)).json()
    assert inbox["unread_count"] == 1
    assert inbox["messages"][0]["requires_ack"] is False

    opened = (await bare_client.get(f"{API}/me/messages/{message['id']}", headers=anya)).json()
    assert opened["read_at"] is not None
    assert opened["is_unread"] is False
    assert (await bare_client.get(f"{API}/me", headers=anya)).json()["unread_count"] == 0

    # «Ознакомлен» у обычных сообщений нет.
    assert (await bare_client.post(f"{API}/me/messages/{message['id']}/acknowledge", headers=anya)).status_code == 400

    listed = (await bare_client.get(f"{API}/admin/messages", headers=bare_admin_headers)).json()[0]
    assert (listed["recipients_total"], listed["read_count"], listed["acknowledged_count"]) == (4, 1, 0)


async def test_важное_прочитано_не_значит_ознакомлен(bare_client, bare_admin_headers, students, pushed):
    message = await send(bare_client, bare_admin_headers, {"type": "all"}, importance="high")
    _, anya = students["anya"]

    opened = (await bare_client.get(f"{API}/me/messages/{message['id']}", headers=anya)).json()
    assert opened["requires_ack"] is True
    assert opened["read_at"] is not None
    assert opened["is_unread"] is True
    assert (await bare_client.get(f"{API}/me", headers=anya)).json()["unread_count"] == 1

    acknowledged = (await bare_client.post(f"{API}/me/messages/{message['id']}/acknowledge", headers=anya)).json()
    assert acknowledged["acknowledged_at"] is not None
    assert acknowledged["is_unread"] is False

    detail = (await bare_client.get(f"{API}/admin/messages/{message['id']}", headers=bare_admin_headers)).json()
    assert (detail["read_count"], detail["acknowledged_count"]) == (1, 1)


async def test_чужое_сообщение_не_открыть(bare_client, bare_admin_headers, students, pushed):
    message = await send(bare_client, bare_admin_headers, {"type": "students", "user_ids": [students["anya"][0]]})
    _, boris = students["boris"]
    assert (await bare_client.get(f"{API}/me/messages/{message['id']}", headers=boris)).status_code == 404


async def test_напоминание_непрочитавшим_и_пауза(bare_client, bare_admin_headers, students, pushed):
    message = await send(bare_client, bare_admin_headers, {"type": "course", "courses": [1]}, importance="high")
    anya_id, anya = students["anya"]
    boris_id, boris = students["boris"]
    gleb_id, _ = students["gleb"]

    # Аня подтвердила, Борис только открыл — у важного ему тоже напоминаем.
    await bare_client.post(f"{API}/me/messages/{message['id']}/acknowledge", headers=anya)
    await bare_client.get(f"{API}/me/messages/{message['id']}", headers=boris)

    response = await bare_client.post(f"{API}/admin/messages/{message['id']}/remind", headers=bare_admin_headers)
    assert response.json() == {"reminded": 2}
    message_id, user_ids, reminder = pushed[-1]
    assert (message_id, set(user_ids), reminder) == (message["id"], {boris_id, gleb_id}, True)
    assert anya_id not in user_ids

    again = await bare_client.post(f"{API}/admin/messages/{message['id']}/remind", headers=bare_admin_headers)
    assert again.status_code == 429

    # Пауза прошла.
    async with SessionLocal() as session:
        await session.execute(
            update(Message).values(last_reminded_at=datetime.now(timezone.utc) - timedelta(hours=7))
        )
        await session.commit()
    assert (await bare_client.post(f"{API}/admin/messages/{message['id']}/remind", headers=bare_admin_headers)).status_code == 200


async def test_у_неважных_нет_напоминаний(bare_client, bare_admin_headers, students, pushed):
    message = await send(bare_client, bare_admin_headers, {"type": "all"}, importance="low")
    assert (await bare_client.post(f"{API}/admin/messages/{message['id']}/remind", headers=bare_admin_headers)).status_code == 400


async def test_досылка_новичку_и_при_смене_группы(bare_client, bare_admin_headers, test_groups, students, pushed):
    to_group = await send(bare_client, bare_admin_headers, {"type": "group", "group_ids": [test_groups["ТЕСТ ПИ 992"]]})
    await send(bare_client, bare_admin_headers, {"type": "students", "user_ids": [students["anya"][0]]}, title="Личное")

    # Новый студент группы получает групповое сообщение, но не чужое личное.
    _, dima = await student(bare_client, test_groups["ТЕСТ ПИ 992"], "Дима Добров", "device-dima-0000000")
    titles = [item["title"] for item in (await bare_client.get(f"{API}/me/messages", headers=dima)).json()["messages"]]
    assert titles == ["Перенос пары"]

    # Глеб перешёл в ПИ 992 — тоже получает.
    _, gleb = await student(bare_client, test_groups["ТЕСТ ПИ 992"], "Глеб Громов", "device-gleb-0000000")
    ids = [item["id"] for item in (await bare_client.get(f"{API}/me/messages", headers=gleb)).json()["messages"]]
    assert to_group["id"] in ids


async def test_удаление_скрывает_сообщение(bare_client, bare_admin_headers, students, pushed):
    message = await send(bare_client, bare_admin_headers, {"type": "all"})
    _, anya = students["anya"]
    assert (await bare_client.delete(f"{API}/admin/messages/{message['id']}", headers=bare_admin_headers)).status_code == 204
    assert (await bare_client.get(f"{API}/me/messages", headers=anya)).json() == {"unread_count": 0, "messages": []}
    assert (await bare_client.get(f"{API}/admin/messages", headers=bare_admin_headers)).json() == []


async def test_список_студентов_для_адресации(bare_client, bare_admin_headers, students, test_groups):
    found = (await bare_client.get(f"{API}/admin/users", params={"course": 1}, headers=bare_admin_headers)).json()
    assert {item["full_name"] for item in found} == {"Аня Андреева", "Борис Белов", "Глеб Громов"}

    by_group = (await bare_client.get(
        f"{API}/admin/users", params={"group_id": test_groups["ТЕСТ ПИ 992"]}, headers=bare_admin_headers
    )).json()
    assert [item["full_name"] for item in by_group] == ["Вера Волкова"]

    student_token = students["anya"][1]
    assert (await bare_client.get(f"{API}/admin/users", headers=student_token)).status_code == 403
