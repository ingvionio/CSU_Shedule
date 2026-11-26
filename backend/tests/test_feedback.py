import asyncio
from unittest.mock import AsyncMock
"""Обращения: отправка студентом, «мои обращения», папки, ответы, письма.

Обращения пишутся в общую базу, поэтому после каждого теста таблицы
обращений очищаются, а адресаты возвращаются без почты.
"""

import pytest
from datetime import datetime, timedelta, timezone
from sqlalchemy import delete, select, update

from app.core.config import get_settings
from app.core.db import SessionLocal
from app.models import EmailOutbox, EmailStatus, FeedbackMessage, FeedbackRecipient, FeedbackReply, User
from app.services import mailer
from app.services.feedback import secret_hash
from app.services.worker import process_email
from tests.moodle_helpers import login_student

TOKEN = "device-token-0123456789"
OTHER_TOKEN = "device-token-9876543210"


@pytest.fixture(autouse=True)
async def _clean_feedback(db_schema):
    yield
    async with SessionLocal() as session:
        await session.execute(delete(EmailOutbox))
        await session.execute(delete(FeedbackReply))
        await session.execute(delete(FeedbackMessage))
        await session.execute(update(FeedbackRecipient).values(emails=[], is_active=True))
        await session.commit()


@pytest.fixture
def client(bare_client):
    return bare_client


@pytest.fixture
def admin_headers(bare_admin_headers):
    return bare_admin_headers


@pytest.fixture
def group_ids(test_groups):
    return {"ПИ 201": test_groups["ТЕСТ ПИ 991"]}


@pytest.fixture
def sent(monkeypatch) -> list[mailer.EmailData]:
    """Почта «настроена», письма складываются в список вместо SMTP."""
    letters: list[mailer.EmailData] = []
    monkeypatch.setattr(get_settings(), "smtp_user", "bot@yandex.ru")
    monkeypatch.setattr(mailer, "_send", AsyncMock(side_effect=letters.append))
    return letters


@pytest.fixture
async def send(client, group_ids):
    login = await login_student(client, group_ids["ПИ 201"], "Иван Петров", TOKEN)
    assert login.status_code == 200, login.text
    authorization = f"Bearer {login.json()['access_token']}"

    async def post_feedback(token=TOKEN, **body):
        payload = {"kind": "methodist", "text": "Когда будет пересдача?", **body}
        headers = {"Authorization": authorization}
        if token:
            headers["X-Feedback-Token"] = token
        return await client.post("/api/v1/feedback", json=payload, headers=headers)

    post_feedback.headers = {"Authorization": authorization}
    return post_feedback


async def recipient_id(client, headers, kind):
    recipients = (await client.get("/api/v1/admin/feedback/recipients", headers=headers)).json()
    return next(item["id"] for item in recipients if item["kind"] == kind)


async def set_emails(client, headers, kind, emails):
    response = await client.patch(
        f"/api/v1/admin/feedback/recipients/{await recipient_id(client, headers, kind)}",
        json={"emails": emails},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    return response.json()


async def outbox():
    async with SessionLocal() as session:
        return list((await session.scalars(select(EmailOutbox).order_by(EmailOutbox.id))).all())


# --- студент ---


async def test_обращение_сохраняется_и_видно_автору(client, group_ids, send):
    group_id = group_ids["ПИ 201"]
    response = await send(group_id=group_id)
    assert response.status_code == 201
    assert response.json()["kind_title"] == "Методист"

    mine = (await client.get("/api/v1/feedback/mine", headers=send.headers)).json()
    assert len(mine) == 1
    assert mine[0]["status"] == "new"
    assert mine[0]["text"] == "Когда будет пересдача?"
    assert "admin_note" not in mine[0]


async def test_чужие_обращения_не_видны(client, send, test_groups):
    await send()
    other = await login_student(client, test_groups["ТЕСТ ПИ 992"], "Другой Студент", OTHER_TOKEN)
    headers = {"Authorization": f"Bearer {other.json()['access_token']}", "X-Feedback-Token": TOKEN}
    assert (await client.get("/api/v1/feedback/mine", headers=headers)).json() == []
    assert (await client.get("/api/v1/feedback/mine", headers={"X-Feedback-Token": TOKEN})).status_code == 401


async def test_обращение_студента_без_токена_устройства(client, admin_headers, send):
    assert (await send(token=None)).status_code == 201
    items = (await client.get("/api/v1/admin/feedback", headers=admin_headers)).json()
    assert items[0]["author_name"] == "Иван Петров" and items[0]["contact"] is None


async def test_проверка_формы(send):
    assert (await send(text="ой")).status_code == 422
    assert (await send(text=" " * 10)).status_code == 422
    assert (await send(text="Текст\x00 обращения")).status_code == 422
    assert (await send(kind="rector")).status_code == 422
    assert (await send(group_id=999999)).status_code == 404
    # Скрытое поле заполнил бот.
    assert (await send(website="http://spam")).status_code == 400


async def test_ограничение_частоты_на_студента(send, monkeypatch):
    monkeypatch.setattr(get_settings(), "feedback_rate_limit_per_hour", 2)
    assert (await send()).status_code == 201
    assert (await send(token=None, text="Как узнать даты зачётов?")).status_code == 201
    assert (await send(token=OTHER_TOKEN, text="Как узнать даты экзаменов?")).status_code == 429


async def test_повтор_не_создаёт_второе_обращение_или_письмо(client, admin_headers, sent, send):
    await set_emails(client, admin_headers, "methodist", ["method@csu.ru"])
    responses = await asyncio.gather(send(), send(token=OTHER_TOKEN))
    assert sorted(response.status_code for response in responses) == [201, 429]
    limited = next(response for response in responses if response.status_code == 429)
    assert int(limited.headers["Retry-After"]) > 0
    assert len(await outbox()) == 1


async def test_ограничение_частоты_на_ip(send, monkeypatch):
    monkeypatch.setattr(get_settings(), "feedback_ip_rate_limit_per_hour", 2)
    assert (await send(token=None)).status_code == 201
    assert (await send(token=OTHER_TOKEN, text="Как узнать даты зачётов?")).status_code == 201
    assert (await send(text="Как узнать даты экзаменов?")).status_code == 429


# --- справки ---

CERTIFICATE = {"kind": "certificate", "purpose": "Для предоставления работодателю", "copies": 2}


async def test_certificate_workflow(client, admin_headers, send, group_ids, test_groups):
    await set_emails(client, admin_headers, "methodist", ["method@csu.ru"])
    path = "/api/v1/feedback"
    details = "<strong>Справка для предоставления по месту требования</strong>"
    response = await client.post(path, json={**CERTIFICATE, "text": f" {details} ",
                                             "purpose": f" {CERTIFICATE['purpose']} "}, headers=send.headers)
    assert response.status_code == 201, response.text
    order_id = response.json()["id"]
    assert response.json()["kind_title"] == "Справка"
    assert await outbox() == []

    admin_path = "/api/v1/admin/feedback"
    assert (await client.get(admin_path, params={"kind": "certificate"})).status_code == 401
    assert (await client.get(admin_path, params={"kind": "certificate"}, headers=send.headers)).status_code == 403
    assert (await client.get(admin_path, params={"kind": "methodist"}, headers=admin_headers)).json() == []
    folders = (await client.get(f"{admin_path}/folders", headers=admin_headers)).json()
    assert {"kind": "certificate", "title": "Справки", "total": 1, "new": 1} in folders
    [order] = (await client.get(admin_path, params={"kind": "certificate", "status": "new"}, headers=admin_headers)).json()
    assert order["id"] == order_id
    assert order["author_name"] == "Иван Петров"
    assert order["group_id"] == group_ids["ПИ 201"]
    assert order["group_name"] == "ТЕСТ ПИ 991"
    assert order["recipient_title"] == "Методист"
    assert order["text"] == details
    assert (order["purpose"], order["copies"]) == (CERTIFICATE["purpose"], 2)
    assert datetime.fromisoformat(order["created_at"])

    order_path = f"{admin_path}/{order_id}"
    reply = {"text": "<em>Справка готова</em>"}
    assert (await client.patch(order_path, json={"status": "archived"}, headers=send.headers)).status_code == 403
    assert (await client.post(f"{order_path}/replies", json=reply, headers=send.headers)).status_code == 403
    assert (await client.patch(order_path, json={"kind": "deanery"}, headers=admin_headers)).status_code == 422
    in_progress = await client.patch(order_path, json={"status": "in_progress"}, headers=admin_headers)
    assert in_progress.json()["status"] == "in_progress"
    answered = await client.post(f"{order_path}/replies", json=reply, headers=admin_headers)
    assert answered.status_code == 201
    assert answered.json()["status"] == "answered"
    archived = await client.patch(order_path, json={"status": "archived"}, headers=admin_headers)
    assert archived.json()["status"] == "archived"

    [mine] = (await client.get(f"{path}/mine", headers=send.headers)).json()
    assert (mine["id"], mine["kind_title"], mine["status"]) == (order_id, "Справка", "archived")
    assert (mine["purpose"], mine["copies"]) == (CERTIFICATE["purpose"], 2)
    assert mine["replies"][0]["author_title"] == "Методист"
    assert mine["replies"][0]["text"] == reply["text"]
    other = await login_student(client, test_groups["ТЕСТ ПИ 992"], "Другой Студент", OTHER_TOKEN)
    other_headers = {"Authorization": f"Bearer {other.json()['access_token']}", "X-Feedback-Token": TOKEN}
    assert (await client.get(f"{path}/mine", headers=other_headers)).json() == []


async def test_certificate_requires_moodle_and_validates_payload(client, send):
    path = "/api/v1/feedback"
    order = CERTIFICATE
    assert (await client.post(path, json=order, headers={"X-Feedback-Token": TOKEN})).status_code == 401
    for forbidden in ({"author_name": "Другое имя"}, {"author_id": 999}, {"group_id": 999},
                      {"group_name": "Другая группа"}, {"contact": "test@example.com"}, {"recipient_id": 999}):
        invalid = await client.post(path, json={**order, **forbidden}, headers=send.headers)
        assert invalid.status_code == 422
    for text in ("x" * 4001, "Справка\x00", 123):
        assert (await client.post(path, json={**order, "text": text}, headers=send.headers)).status_code == 422
    for field in ("purpose", "copies"):
        assert (await client.post(path, json={key: value for key, value in order.items() if key != field},
                                  headers=send.headers)).status_code == 422
    for invalid_fields in ({"purpose": "   "}, {"purpose": "Цель\x00"}, {"purpose": "x" * 4001},
                           {"copies": 0}, {"copies": -1}, {"copies": 1.5}, {"copies": True},
                           {"copies": "2"}, {"copies": 2147483648}):
        assert (await client.post(path, json={**order, **invalid_fields}, headers=send.headers)).status_code == 422
    assert (await client.post(path, json={**order, "website": "spam"}, headers=send.headers)).status_code == 400
    assert (await client.get(f"{path}/mine", headers=send.headers)).json() == []
    assert (await client.post(path, json=order, headers=send.headers)).status_code == 201
    [mine] = (await client.get(f"{path}/mine", headers=send.headers)).json()
    assert mine["text"] == ""


async def test_parallel_certificate_orders_and_regular_feedback_share_account_quota(client, send, monkeypatch):
    monkeypatch.setattr(get_settings(), "feedback_rate_limit_per_hour", 2)
    responses = await asyncio.gather(*(
        client.post("/api/v1/feedback", json={**CERTIFICATE, "text": text},
                    headers={**send.headers, "X-Feedback-Token": token})
        for text, token in (("", TOKEN), ("   ", OTHER_TOKEN))
    ))
    assert sorted(response.status_code for response in responses) == [201, 429]
    rejected = next(response for response in responses if response.status_code == 429)
    assert "уже отправлено" in rejected.json()["detail"]
    assert int(rejected.headers["Retry-After"]) > 0
    assert (await send()).status_code == 201
    response = await client.post("/api/v1/feedback", json={**CERTIFICATE, "copies": 3}, headers=send.headers)
    assert response.status_code == 429
    assert "слишком много" in response.json()["detail"]


async def test_certificate_requires_group_in_moodle_profile(client, send):
    async with SessionLocal() as session:
        await session.execute(update(User).where(User.full_name == "Иван Петров").values(group_id=None))
        await session.commit()

    response = await client.post("/api/v1/feedback", json=CERTIFICATE, headers=send.headers)
    assert response.status_code == 409
    assert (await client.get("/api/v1/feedback/mine", headers=send.headers)).json() == []
    assert (await send()).status_code == 201


async def test_certificate_and_regular_feedback_share_ip_quota(client, send, monkeypatch):
    monkeypatch.setattr(get_settings(), "feedback_ip_rate_limit_per_hour", 1)
    assert (await client.post("/api/v1/feedback", json=CERTIFICATE, headers=send.headers)).status_code == 201
    assert (await send()).status_code == 429


async def test_certificate_stays_with_methodist_when_mail_is_disabled(client, admin_headers, send):
    methodist_id = await recipient_id(client, admin_headers, "methodist")
    disabled = await client.patch(
        f"/api/v1/admin/feedback/recipients/{methodist_id}", json={"is_active": False}, headers=admin_headers,
    )
    assert disabled.status_code == 200
    assert (await client.post("/api/v1/feedback", json=CERTIFICATE, headers=send.headers)).status_code == 201
    [order] = (await client.get("/api/v1/admin/feedback", params={"kind": "certificate"}, headers=admin_headers)).json()
    assert order["recipient_title"] == "Методист"
    assert await outbox() == []


async def test_certificate_duplicate_checks_purpose_and_copies(client, send):
    path = "/api/v1/feedback"
    for fields in ({}, {"copies": 3}, {"purpose": "Для вуза"}):
        response = await client.post(path, json={**CERTIFICATE, **fields}, headers=send.headers)
        assert response.status_code == 201, response.text
    repeated = {**CERTIFICATE, "purpose": f" {CERTIFICATE['purpose']} "}
    assert (await client.post(path, json=repeated, headers=send.headers)).status_code == 429


async def test_regular_feedback_cannot_be_converted_to_certificate(client, admin_headers, send):
    message_id = (await send()).json()["id"]
    response = await client.patch(f"/api/v1/admin/feedback/{message_id}", json={"kind": "certificate"}, headers=admin_headers)
    assert response.status_code == 422


# --- админка ---


async def test_обращения_закрыты_без_входа(client):
    assert (await client.get("/api/v1/admin/feedback")).status_code == 401
    assert (await client.get("/api/v1/admin/feedback/recipients")).status_code == 401


async def test_admin_feedback_cursor_preserves_access_to_legacy_rows(client, admin_headers, send):
    same_time = datetime.now(timezone.utc) - timedelta(days=1)
    async with SessionLocal() as session:
        for i in range(3):
            session.add(FeedbackMessage(kind="methodist", text=f"Архивное обращение {i}", created_at=same_time,
                                        author_token_hash=secret_hash(TOKEN)))
        await session.commit()
    first = await client.get("/api/v1/admin/feedback", params={"limit": 2}, headers=admin_headers)
    assert first.status_code == 200
    first_items = first.json()
    assert [item["text"] for item in first_items] == ["Архивное обращение 2", "Архивное обращение 1"]
    last = await client.get("/api/v1/admin/feedback", params={"before_id": first_items[-1]["id"]}, headers=admin_headers)
    assert [item["text"] for item in last.json()] == ["Архивное обращение 0"]
    student_headers = {**send.headers, "X-Feedback-Token": TOKEN}
    assert (await client.get("/api/v1/feedback/mine", headers=student_headers)).json() == []
    assert (await client.get("/api/v1/admin/feedback", params={"limit": 201}, headers=admin_headers)).status_code == 422


async def test_папки_и_счётчики(client, admin_headers, send):
    await send(kind="methodist", text="Как узнать даты зачётов?")
    await send(kind="methodist")
    await send(kind="deanery")
    await send(kind="unknown", text="Кто занимается военным столом?")

    folders = {item["kind"]: item for item in (await client.get("/api/v1/admin/feedback/folders", headers=admin_headers)).json()}
    assert folders["methodist"] == {"kind": "methodist", "title": "Методист", "total": 2, "new": 2}
    assert folders["deanery"]["new"] == 1
    assert folders["unknown"]["new"] == 1
    assert folders["dev"]["total"] == 0

    methodist = (await client.get("/api/v1/admin/feedback", params={"kind": "methodist"}, headers=admin_headers)).json()
    assert len(methodist) == 2
    assert methodist[0]["recipient_title"] == "Методист"

    unknown = (await client.get("/api/v1/admin/feedback", params={"kind": "unknown"}, headers=admin_headers)).json()
    assert unknown[0]["recipient_title"] is None


async def test_ответ_виден_студенту(client, admin_headers, send):
    message_id = (await send(kind="deanery")).json()["id"]

    response = await client.post(
        f"/api/v1/admin/feedback/{message_id}/replies",
        json={"text": "Справку можно получить в 210 кабинете."},
        headers=admin_headers,
    )
    assert response.status_code == 201
    assert response.json()["status"] == "answered"
    assert response.json()["replies"][0]["author_name"] == "admin"

    mine = (await client.get("/api/v1/feedback/mine", headers=send.headers)).json()
    assert mine[0]["status"] == "answered"
    reply = mine[0]["replies"][0]
    assert reply["author_title"] == "Деканат"
    assert reply["text"] == "Справку можно получить в 210 кабинете."
    assert "author_name" not in reply


async def test_статус_и_заметка(client, admin_headers, send):
    message_id = (await send()).json()["id"]
    response = await client.patch(
        f"/api/v1/admin/feedback/{message_id}",
        json={"status": "in_progress", "admin_note": "уточнить у кафедры"},
        headers=admin_headers,
    )
    assert response.status_code == 200
    assert response.json()["status"] == "in_progress"
    assert response.json()["admin_note"] == "уточнить у кафедры"
    assert (await client.patch("/api/v1/admin/feedback/999999", json={"status": "archived"}, headers=admin_headers)).status_code == 404


# --- почта ---


async def test_письмо_адресату_с_reply_to(client, admin_headers, sent, send):
    await set_emails(client, admin_headers, "methodist", ["Method@csu.ru", "method@csu.ru", "helper@csu.ru"])
    await send(contact="ivan@mail.ru")

    assert sent == []
    assert {item.status for item in await outbox()} == {EmailStatus.PENDING.value}
    async with SessionLocal() as session:
        await process_email(session, datetime.now(timezone.utc))

    assert sorted(item.to_address for item in sent) == ["helper@csu.ru", "method@csu.ru"]
    assert all(item.reply_to == "ivan@mail.ru" for item in sent)
    assert "Иван Петров" in sent[0].body and "Когда будет пересдача?" in sent[0].body
    assert {item.status for item in await outbox()} == {EmailStatus.SENT.value}


async def test_feedback_mail_uses_plain_text(monkeypatch):
    send_smtp = AsyncMock()
    monkeypatch.setattr(mailer, "send", send_smtp)
    monkeypatch.setattr(get_settings(), "smtp_user", "bot@example.com")
    body = "<strong>Текст обращения</strong>"
    await mailer._send(mailer.EmailData("recipient@example.com", None, "Тест", body))
    message = send_smtp.await_args.args[0]
    assert message.get_content_type() == "text/plain"
    assert message.get_content().strip() == body


async def test_без_почты_адресата_писем_нет(sent, send):
    await send(kind="deanery")
    assert sent == [] and await outbox() == []


async def test_неверный_email_адресата(client, admin_headers):
    response = await client.patch(
        f"/api/v1/admin/feedback/recipients/{await recipient_id(client, admin_headers, 'dev')}",
        json={"emails": ["не почта"]},
        headers=admin_headers,
    )
    assert response.status_code == 422


async def test_выключенный_адресат_не_получает_писем(client, admin_headers, sent, send):
    await set_emails(client, admin_headers, "dev", ["me@yandex.ru"])
    await client.patch(
        f"/api/v1/admin/feedback/recipients/{await recipient_id(client, admin_headers, 'dev')}",
        json={"is_active": False},
        headers=admin_headers,
    )
    await send(kind="dev")
    assert sent == []


async def test_перенос_из_нераспределённых_отправляет_письмо(client, admin_headers, sent, send):
    await set_emails(client, admin_headers, "deanery", ["dekanat@csu.ru"])
    message_id = (await send(kind="unknown", text="Кто занимается военным столом?")).json()["id"]
    assert sent == []

    response = await client.patch(f"/api/v1/admin/feedback/{message_id}", json={"kind": "deanery"}, headers=admin_headers)
    assert response.json()["kind"] == "deanery"
    assert response.json()["recipient_title"] == "Деканат"
    assert sent == []
    async with SessionLocal() as session:
        await process_email(session, datetime.now(timezone.utc))
    assert [item.to_address for item in sent] == ["dekanat@csu.ru"]


async def test_ответ_уходит_студенту_на_почту(client, admin_headers, sent, send):
    message_id = (await send(contact="student@mail.ru")).json()["id"]
    await client.post(f"/api/v1/admin/feedback/{message_id}/replies", json={"text": "В четверг."}, headers=admin_headers)

    assert sent == []
    async with SessionLocal() as session:
        await process_email(session, datetime.now(timezone.utc))
    assert [item.to_address for item in sent] == ["student@mail.ru"]
    assert "В четверг." in sent[0].body


async def test_ответ_без_почты_студента_только_в_приложении(client, admin_headers, sent, send):
    message_id = (await send(contact="@telegram_nick")).json()["id"]
    await client.post(f"/api/v1/admin/feedback/{message_id}/replies", json={"text": "В четверг."}, headers=admin_headers)
    assert sent == []


async def test_сбой_smtp_не_теряет_обращение(client, admin_headers, monkeypatch, send):
    def broken(item):
        raise OSError("smtp недоступен")

    monkeypatch.setattr(get_settings(), "smtp_user", "bot@yandex.ru")
    monkeypatch.setattr(mailer, "_send", broken)
    await set_emails(client, admin_headers, "dev", ["me@yandex.ru"])

    assert (await send(kind="dev")).status_code == 201
    now = datetime.now(timezone.utc)
    assert (await outbox())[0].attempts == 0
    async with SessionLocal() as session:
        await process_email(session, now)
    [item] = await outbox()
    assert item.status == EmailStatus.PENDING.value
    assert item.attempts == 1 and item.last_error == "Ошибка SMTP (OSError)"

    # Досылка после починки.
    letters = []
    monkeypatch.setattr(mailer, "_send", AsyncMock(side_effect=letters.append))
    async with SessionLocal() as session:
        await session.execute(update(EmailOutbox).values(next_attempt_at=now - timedelta(seconds=1)))
        await session.commit()
        assert await mailer.deliver_pending(session) == 1
    assert (await outbox())[0].status == EmailStatus.SENT.value


async def test_без_настроек_почты_письмо_пропускается(client, admin_headers, monkeypatch, send):
    monkeypatch.setattr(get_settings(), "smtp_user", "")
    await set_emails(client, admin_headers, "dev", ["me@yandex.ru"])
    await send(kind="dev")
    assert (await outbox())[0].status == EmailStatus.PENDING.value
    async with SessionLocal() as session:
        await process_email(session, datetime.now(timezone.utc))
    assert (await outbox())[0].status == EmailStatus.SKIPPED.value


async def test_smtp_wait_leaves_database_connection_available(client, admin_headers, monkeypatch, send):
    import asyncio
    from app.core.db import engine

    started, release = asyncio.Event(), asyncio.Event()
    monkeypatch.setattr(get_settings(), "smtp_user", "bot@example.com")

    async def deliver(message, *, username, use_tls, timeout, **kwargs):
        assert message["To"] == "methodist@example.com"
        assert username == "bot@example.com" and use_tls and timeout == 20
        started.set()
        await release.wait()

    smtp = AsyncMock(side_effect=deliver)
    monkeypatch.setattr(mailer, "send", smtp)
    await set_emails(client, admin_headers, "methodist", ["methodist@example.com"])
    assert (await send()).status_code == 201

    async def process():
        async with SessionLocal() as session:
            return await process_email(session, datetime.now(timezone.utc))

    sending = asyncio.create_task(process())
    try:
        await asyncio.wait_for(started.wait(), timeout=5)
        assert engine.pool.checkedout() == 0
        assert (await asyncio.wait_for(client.get("/api/v1/groups"), timeout=5)).status_code == 200
        assert not sending.done()
    finally:
        release.set()
        result = await sending
    assert result.sent == 1
    smtp.assert_awaited_once()
