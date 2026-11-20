"""Обращения: отправка студентом, «мои обращения», папки, ответы, письма.

Обращения пишутся в общую базу, поэтому после каждого теста таблицы
обращений очищаются, а адресаты возвращаются без почты.
"""

import asyncio
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import delete, select, update

from app.core.config import get_settings
from app.core.db import SessionLocal, engine
from app.models import EmailOutbox, EmailStatus, FeedbackMessage, FeedbackRecipient
from app.services import mailer

TOKEN = "device-token-0123456789"
OTHER_TOKEN = "device-token-9876543210"


@pytest.fixture(autouse=True)
async def _clean_feedback(db_schema):
    yield
    async with SessionLocal() as session:
        await session.execute(delete(EmailOutbox))
        await session.execute(delete(FeedbackMessage))
        await session.execute(update(FeedbackRecipient).values(emails=[], is_active=True))
        await session.commit()


@pytest.fixture
def sent(monkeypatch) -> list[EmailOutbox]:
    """Почта «настроена», письма складываются в список вместо SMTP."""
    letters: list[EmailOutbox] = []
    monkeypatch.setattr(get_settings(), "smtp_user", "bot@yandex.ru")
    monkeypatch.setattr(mailer, "_send", AsyncMock(side_effect=letters.append))
    return letters


async def send(bare_client, token=TOKEN, **body):
    payload = {"kind": "methodist", "text": "Когда будет пересдача?", **body}
    headers = {"X-Feedback-Token": token} if token else {}
    return await bare_client.post("/api/v1/feedback", json=payload, headers=headers)


async def recipient_id(bare_client, headers, kind):
    recipients = (await bare_client.get("/api/v1/admin/feedback/recipients", headers=headers)).json()
    return next(item["id"] for item in recipients if item["kind"] == kind)


async def set_emails(bare_client, headers, kind, emails):
    response = await bare_client.patch(
        f"/api/v1/admin/feedback/recipients/{await recipient_id(bare_client, headers, kind)}",
        json={"emails": emails},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    return response.json()


async def outbox():
    async with SessionLocal() as session:
        return list((await session.scalars(select(EmailOutbox).order_by(EmailOutbox.id))).all())


# --- студент ---


async def test_обращение_сохраняется_и_видно_автору(bare_client, test_groups):
    group_id = test_groups["ТЕСТ ПИ 991"]
    response = await send(bare_client, group_id=group_id)
    assert response.status_code == 201
    assert response.json()["kind_title"] == "Методист"

    mine = (await bare_client.get("/api/v1/feedback/mine", headers={"X-Feedback-Token": TOKEN})).json()
    assert len(mine) == 1
    assert mine[0]["status"] == "new"
    assert mine[0]["text"] == "Когда будет пересдача?"
    assert "admin_note" not in mine[0]


async def test_чужие_обращения_не_видны(bare_client):
    await send(bare_client)
    assert (await bare_client.get("/api/v1/feedback/mine", headers={"X-Feedback-Token": OTHER_TOKEN})).json() == []
    assert (await bare_client.get("/api/v1/feedback/mine")).json() == []


async def test_анонимное_обращение_без_токена(bare_client, bare_admin_headers):
    assert (await send(bare_client, token=None)).status_code == 201
    items = (await bare_client.get("/api/v1/admin/feedback", headers=bare_admin_headers)).json()
    assert items[0]["author_name"] is None and items[0]["contact"] is None


async def test_проверка_формы(bare_client):
    assert (await send(bare_client, text="ой")).status_code == 422
    assert (await send(bare_client, kind="rector")).status_code == 422
    assert (await send(bare_client, group_id=999999)).status_code == 404
    # Скрытое поле заполнил бот.
    assert (await send(bare_client, website="http://spam")).status_code == 400


async def test_ограничение_частоты_на_устройство(bare_client, monkeypatch):
    monkeypatch.setattr(get_settings(), "feedback_rate_limit_per_hour", 2)
    assert (await send(bare_client)).status_code == 201
    assert (await send(bare_client)).status_code == 201
    assert (await send(bare_client)).status_code == 429
    # Другое устройство с того же IP (Wi-Fi вуза) не задето.
    assert (await send(bare_client, token=OTHER_TOKEN)).status_code == 201


async def test_ограничение_частоты_на_ip(bare_client, monkeypatch):
    monkeypatch.setattr(get_settings(), "feedback_ip_rate_limit_per_hour", 2)
    assert (await send(bare_client, token=None)).status_code == 201
    assert (await send(bare_client, token=OTHER_TOKEN)).status_code == 201
    assert (await send(bare_client)).status_code == 429


# --- админка ---


async def test_обращения_закрыты_без_входа(bare_client):
    assert (await bare_client.get("/api/v1/admin/feedback")).status_code == 401
    assert (await bare_client.get("/api/v1/admin/feedback/recipients")).status_code == 401


async def test_папки_и_счётчики(bare_client, bare_admin_headers):
    await send(bare_client, kind="methodist")
    await send(bare_client, kind="methodist")
    await send(bare_client, kind="deanery")
    await send(bare_client, kind="unknown", text="Кто занимается военным столом?")

    folders = {item["kind"]: item for item in (await bare_client.get("/api/v1/admin/feedback/folders", headers=bare_admin_headers)).json()}
    assert folders["methodist"] == {"kind": "methodist", "title": "Методист", "total": 2, "new": 2}
    assert folders["deanery"]["new"] == 1
    assert folders["unknown"]["new"] == 1
    assert folders["dev"]["total"] == 0

    methodist = (await bare_client.get("/api/v1/admin/feedback", params={"kind": "methodist"}, headers=bare_admin_headers)).json()
    assert len(methodist) == 2
    assert methodist[0]["recipient_title"] == "Методист"

    unknown = (await bare_client.get("/api/v1/admin/feedback", params={"kind": "unknown"}, headers=bare_admin_headers)).json()
    assert unknown[0]["recipient_title"] is None


async def test_ответ_виден_студенту(bare_client, bare_admin_headers):
    message_id = (await send(bare_client, kind="deanery")).json()["id"]

    response = await bare_client.post(
        f"/api/v1/admin/feedback/{message_id}/replies",
        json={"text": "Справку можно получить в 210 кабинете."},
        headers=bare_admin_headers,
    )
    assert response.status_code == 201
    assert response.json()["status"] == "answered"
    assert response.json()["replies"][0]["author_name"] == "admin"

    mine = (await bare_client.get("/api/v1/feedback/mine", headers={"X-Feedback-Token": TOKEN})).json()
    assert mine[0]["status"] == "answered"
    reply = mine[0]["replies"][0]
    assert reply["author_title"] == "Деканат"
    assert reply["text"] == "Справку можно получить в 210 кабинете."
    assert "author_name" not in reply


async def test_статус_и_заметка(bare_client, bare_admin_headers):
    message_id = (await send(bare_client)).json()["id"]
    response = await bare_client.patch(
        f"/api/v1/admin/feedback/{message_id}",
        json={"status": "in_progress", "admin_note": "уточнить у кафедры"},
        headers=bare_admin_headers,
    )
    assert response.status_code == 200
    assert response.json()["status"] == "in_progress"
    assert response.json()["admin_note"] == "уточнить у кафедры"
    assert (await bare_client.patch("/api/v1/admin/feedback/999999", json={"status": "archived"}, headers=bare_admin_headers)).status_code == 404


# --- почта ---


async def test_письмо_адресату_с_reply_to(bare_client, bare_admin_headers, sent):
    await set_emails(bare_client, bare_admin_headers, "methodist", ["Method@csu.ru", "method@csu.ru", "helper@csu.ru"])
    await send(bare_client, author_name="Иван Петров", contact="ivan@mail.ru")

    assert sorted(item.to_address for item in sent) == ["helper@csu.ru", "method@csu.ru"]
    assert all(item.reply_to == "ivan@mail.ru" for item in sent)
    assert "Иван Петров" in sent[0].body and "Когда будет пересдача?" in sent[0].body
    assert {item.status for item in await outbox()} == {EmailStatus.SENT.value}


async def test_без_почты_адресата_писем_нет(bare_client, sent):
    await send(bare_client, kind="deanery")
    assert sent == [] and await outbox() == []


async def test_неверный_email_адресата(bare_client, bare_admin_headers):
    response = await bare_client.patch(
        f"/api/v1/admin/feedback/recipients/{await recipient_id(bare_client, bare_admin_headers, 'dev')}",
        json={"emails": ["не почта"]},
        headers=bare_admin_headers,
    )
    assert response.status_code == 422


async def test_выключенный_адресат_не_получает_писем(bare_client, bare_admin_headers, sent):
    await set_emails(bare_client, bare_admin_headers, "dev", ["me@yandex.ru"])
    await bare_client.patch(
        f"/api/v1/admin/feedback/recipients/{await recipient_id(bare_client, bare_admin_headers, 'dev')}",
        json={"is_active": False},
        headers=bare_admin_headers,
    )
    await send(bare_client, kind="dev")
    assert sent == []


async def test_перенос_из_нераспределённых_отправляет_письмо(bare_client, bare_admin_headers, sent):
    await set_emails(bare_client, bare_admin_headers, "deanery", ["dekanat@csu.ru"])
    message_id = (await send(bare_client, kind="unknown", text="Кто занимается военным столом?")).json()["id"]
    assert sent == []

    response = await bare_client.patch(f"/api/v1/admin/feedback/{message_id}", json={"kind": "deanery"}, headers=bare_admin_headers)
    assert response.json()["kind"] == "deanery"
    assert response.json()["recipient_title"] == "Деканат"
    assert [item.to_address for item in sent] == ["dekanat@csu.ru"]


async def test_ответ_уходит_студенту_на_почту(bare_client, bare_admin_headers, sent):
    message_id = (await send(bare_client, contact="student@mail.ru")).json()["id"]
    await bare_client.post(f"/api/v1/admin/feedback/{message_id}/replies", json={"text": "В четверг."}, headers=bare_admin_headers)

    assert [item.to_address for item in sent] == ["student@mail.ru"]
    assert "В четверг." in sent[0].body


async def test_ответ_без_почты_студента_только_в_приложении(bare_client, bare_admin_headers, sent):
    message_id = (await send(bare_client, contact="@telegram_nick")).json()["id"]
    await bare_client.post(f"/api/v1/admin/feedback/{message_id}/replies", json={"text": "В четверг."}, headers=bare_admin_headers)
    assert sent == []


async def test_сбой_smtp_не_теряет_обращение(bare_client, bare_admin_headers, monkeypatch):
    async def broken(item):
        raise OSError("smtp недоступен")

    monkeypatch.setattr(get_settings(), "smtp_user", "bot@yandex.ru")
    monkeypatch.setattr(mailer, "_send", broken)
    await set_emails(bare_client, bare_admin_headers, "dev", ["me@yandex.ru"])

    assert (await send(bare_client, kind="dev")).status_code == 201
    [item] = await outbox()
    assert item.status == EmailStatus.PENDING.value
    assert item.attempts == 1 and "smtp недоступен" in item.last_error

    # Досылка после починки.
    letters = []
    monkeypatch.setattr(mailer, "_send", AsyncMock(side_effect=letters.append))
    async with SessionLocal() as session:
        assert await mailer.deliver_pending(session) == 1
    assert (await outbox())[0].status == EmailStatus.SENT.value


async def test_без_настроек_почты_письмо_пропускается(bare_client, bare_admin_headers, monkeypatch):
    monkeypatch.setattr(get_settings(), "smtp_user", "")
    await set_emails(bare_client, bare_admin_headers, "dev", ["me@yandex.ru"])
    await send(bare_client, kind="dev")
    assert (await outbox())[0].status == EmailStatus.SKIPPED.value


async def test_smtp_wait_leaves_database_connection_available(bare_client, bare_admin_headers, monkeypatch):
    started = asyncio.Event()
    release = asyncio.Event()
    monkeypatch.setattr(get_settings(), "smtp_user", "bot@example.com")

    async def deliver(message, *, username, use_tls, timeout, **kwargs):
        assert message["To"] == "methodist@example.com"
        assert username == "bot@example.com" and use_tls and timeout == 20
        started.set()
        await release.wait()

    send = AsyncMock(side_effect=deliver)
    monkeypatch.setattr(mailer, "send", send)
    recipients = await bare_client.get("/api/v1/admin/feedback/recipients", headers=bare_admin_headers)
    recipient = next(item for item in recipients.json() if item["kind"] == "methodist")
    url = f"/api/v1/admin/feedback/recipients/{recipient['id']}"
    configured = await bare_client.patch(
        url, headers=bare_admin_headers, json={"emails": ["methodist@example.com"]},
    )
    assert configured.status_code == 200
    feedback = asyncio.create_task(
        bare_client.post("/api/v1/feedback", json={"kind": "methodist", "text": "Когда будет пересдача?"})
    )
    try:
        await asyncio.wait_for(started.wait(), timeout=5)
        assert engine.pool.checkedout() == 0
        response = await asyncio.wait_for(bare_client.get("/api/v1/groups"), timeout=5)
        assert response.status_code == 200
    finally:
        release.set()
        result = await feedback
        await bare_client.patch(url, headers=bare_admin_headers, json={"emails": []})
    assert result.status_code == 201
    send.assert_awaited_once()
