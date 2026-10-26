"""Обращения: отправка студентом, «мои обращения», папки, ответы, письма.

Обращения пишутся в общую базу, поэтому после каждого теста таблицы
обращений очищаются, а адресаты возвращаются без почты.
"""

import pytest
from sqlalchemy import delete, select, update

from app.core.config import get_settings
from app.core.db import SessionLocal
from app.models import EmailOutbox, EmailStatus, FeedbackMessage, FeedbackRecipient
from app.services import mailer

TOKEN = "device-token-0123456789"
OTHER_TOKEN = "device-token-9876543210"


@pytest.fixture(autouse=True)
def _clean_feedback(filled_db):
    yield
    with SessionLocal() as session:
        session.execute(delete(EmailOutbox))
        session.execute(delete(FeedbackMessage))
        session.execute(update(FeedbackRecipient).values(emails=[], is_active=True))
        session.commit()


@pytest.fixture
def sent(monkeypatch) -> list[EmailOutbox]:
    """Почта «настроена», письма складываются в список вместо SMTP."""
    letters: list[EmailOutbox] = []
    monkeypatch.setattr(get_settings(), "smtp_user", "bot@yandex.ru")
    monkeypatch.setattr(mailer, "_send", lambda item: letters.append(item))
    return letters


def send(client, token=TOKEN, **body):
    payload = {"kind": "methodist", "text": "Когда будет пересдача?", **body}
    headers = {"X-Feedback-Token": token} if token else {}
    return client.post("/api/v1/feedback", json=payload, headers=headers)


def recipient_id(client, headers, kind):
    recipients = client.get("/api/v1/admin/feedback/recipients", headers=headers).json()
    return next(item["id"] for item in recipients if item["kind"] == kind)


def set_emails(client, headers, kind, emails):
    response = client.patch(
        f"/api/v1/admin/feedback/recipients/{recipient_id(client, headers, kind)}",
        json={"emails": emails},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    return response.json()


def outbox():
    with SessionLocal() as session:
        return list(session.scalars(select(EmailOutbox).order_by(EmailOutbox.id)).all())


# --- студент ---


def test_обращение_сохраняется_и_видно_автору(client, group_ids):
    group_id = group_ids["ПИ 201"]
    response = send(client, group_id=group_id)
    assert response.status_code == 201
    assert response.json()["kind_title"] == "Методист"

    mine = client.get("/api/v1/feedback/mine", headers={"X-Feedback-Token": TOKEN}).json()
    assert len(mine) == 1
    assert mine[0]["status"] == "new"
    assert mine[0]["text"] == "Когда будет пересдача?"
    assert "admin_note" not in mine[0]


def test_чужие_обращения_не_видны(client):
    send(client)
    assert client.get("/api/v1/feedback/mine", headers={"X-Feedback-Token": OTHER_TOKEN}).json() == []
    assert client.get("/api/v1/feedback/mine").json() == []


def test_анонимное_обращение_без_токена(client, admin_headers):
    assert send(client, token=None).status_code == 201
    items = client.get("/api/v1/admin/feedback", headers=admin_headers).json()
    assert items[0]["author_name"] is None and items[0]["contact"] is None


def test_проверка_формы(client):
    assert send(client, text="ой").status_code == 422
    assert send(client, kind="rector").status_code == 422
    assert send(client, group_id=999999).status_code == 404
    # Скрытое поле заполнил бот.
    assert send(client, website="http://spam").status_code == 400


def test_ограничение_частоты_на_устройство(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "feedback_rate_limit_per_hour", 2)
    assert send(client).status_code == 201
    assert send(client).status_code == 201
    assert send(client).status_code == 429
    # Другое устройство с того же IP (Wi-Fi вуза) не задето.
    assert send(client, token=OTHER_TOKEN).status_code == 201


def test_ограничение_частоты_на_ip(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "feedback_ip_rate_limit_per_hour", 2)
    assert send(client, token=None).status_code == 201
    assert send(client, token=OTHER_TOKEN).status_code == 201
    assert send(client).status_code == 429


# --- админка ---


def test_обращения_закрыты_без_входа(client):
    assert client.get("/api/v1/admin/feedback").status_code == 401
    assert client.get("/api/v1/admin/feedback/recipients").status_code == 401


def test_папки_и_счётчики(client, admin_headers):
    send(client, kind="methodist")
    send(client, kind="methodist")
    send(client, kind="deanery")
    send(client, kind="unknown", text="Кто занимается военным столом?")

    folders = {item["kind"]: item for item in client.get("/api/v1/admin/feedback/folders", headers=admin_headers).json()}
    assert folders["methodist"] == {"kind": "methodist", "title": "Методист", "total": 2, "new": 2}
    assert folders["deanery"]["new"] == 1
    assert folders["unknown"]["new"] == 1
    assert folders["dev"]["total"] == 0

    methodist = client.get("/api/v1/admin/feedback", params={"kind": "methodist"}, headers=admin_headers).json()
    assert len(methodist) == 2
    assert methodist[0]["recipient_title"] == "Методист"

    unknown = client.get("/api/v1/admin/feedback", params={"kind": "unknown"}, headers=admin_headers).json()
    assert unknown[0]["recipient_title"] is None


def test_ответ_виден_студенту(client, admin_headers):
    message_id = send(client, kind="deanery").json()["id"]

    response = client.post(
        f"/api/v1/admin/feedback/{message_id}/replies",
        json={"text": "Справку можно получить в 210 кабинете."},
        headers=admin_headers,
    )
    assert response.status_code == 201
    assert response.json()["status"] == "answered"
    assert response.json()["replies"][0]["author_name"] == "admin"

    mine = client.get("/api/v1/feedback/mine", headers={"X-Feedback-Token": TOKEN}).json()
    assert mine[0]["status"] == "answered"
    reply = mine[0]["replies"][0]
    assert reply["author_title"] == "Деканат"
    assert reply["text"] == "Справку можно получить в 210 кабинете."
    assert "author_name" not in reply


def test_статус_и_заметка(client, admin_headers):
    message_id = send(client).json()["id"]
    response = client.patch(
        f"/api/v1/admin/feedback/{message_id}",
        json={"status": "in_progress", "admin_note": "уточнить у кафедры"},
        headers=admin_headers,
    )
    assert response.status_code == 200
    assert response.json()["status"] == "in_progress"
    assert response.json()["admin_note"] == "уточнить у кафедры"
    assert client.patch("/api/v1/admin/feedback/999999", json={"status": "archived"}, headers=admin_headers).status_code == 404


# --- почта ---


def test_письмо_адресату_с_reply_to(client, admin_headers, sent):
    set_emails(client, admin_headers, "methodist", ["Method@csu.ru", "method@csu.ru", "helper@csu.ru"])
    send(client, author_name="Иван Петров", contact="ivan@mail.ru")

    assert sorted(item.to_address for item in sent) == ["helper@csu.ru", "method@csu.ru"]
    assert all(item.reply_to == "ivan@mail.ru" for item in sent)
    assert "Иван Петров" in sent[0].body and "Когда будет пересдача?" in sent[0].body
    assert {item.status for item in outbox()} == {EmailStatus.SENT.value}


def test_без_почты_адресата_писем_нет(client, sent):
    send(client, kind="deanery")
    assert sent == [] and outbox() == []


def test_неверный_email_адресата(client, admin_headers):
    response = client.patch(
        f"/api/v1/admin/feedback/recipients/{recipient_id(client, admin_headers, 'dev')}",
        json={"emails": ["не почта"]},
        headers=admin_headers,
    )
    assert response.status_code == 422


def test_выключенный_адресат_не_получает_писем(client, admin_headers, sent):
    set_emails(client, admin_headers, "dev", ["me@yandex.ru"])
    client.patch(
        f"/api/v1/admin/feedback/recipients/{recipient_id(client, admin_headers, 'dev')}",
        json={"is_active": False},
        headers=admin_headers,
    )
    send(client, kind="dev")
    assert sent == []


def test_перенос_из_нераспределённых_отправляет_письмо(client, admin_headers, sent):
    set_emails(client, admin_headers, "deanery", ["dekanat@csu.ru"])
    message_id = send(client, kind="unknown", text="Кто занимается военным столом?").json()["id"]
    assert sent == []

    response = client.patch(f"/api/v1/admin/feedback/{message_id}", json={"kind": "deanery"}, headers=admin_headers)
    assert response.json()["kind"] == "deanery"
    assert response.json()["recipient_title"] == "Деканат"
    assert [item.to_address for item in sent] == ["dekanat@csu.ru"]


def test_ответ_уходит_студенту_на_почту(client, admin_headers, sent):
    message_id = send(client, contact="student@mail.ru").json()["id"]
    client.post(f"/api/v1/admin/feedback/{message_id}/replies", json={"text": "В четверг."}, headers=admin_headers)

    assert [item.to_address for item in sent] == ["student@mail.ru"]
    assert "В четверг." in sent[0].body


def test_ответ_без_почты_студента_только_в_приложении(client, admin_headers, sent):
    message_id = send(client, contact="@telegram_nick").json()["id"]
    client.post(f"/api/v1/admin/feedback/{message_id}/replies", json={"text": "В четверг."}, headers=admin_headers)
    assert sent == []


def test_сбой_smtp_не_теряет_обращение(client, admin_headers, monkeypatch):
    def broken(item):
        raise OSError("smtp недоступен")

    monkeypatch.setattr(get_settings(), "smtp_user", "bot@yandex.ru")
    monkeypatch.setattr(mailer, "_send", broken)
    set_emails(client, admin_headers, "dev", ["me@yandex.ru"])

    assert send(client, kind="dev").status_code == 201
    [item] = outbox()
    assert item.status == EmailStatus.PENDING.value
    assert item.attempts == 1 and "smtp недоступен" in item.last_error

    # Досылка после починки.
    letters = []
    monkeypatch.setattr(mailer, "_send", lambda letter: letters.append(letter))
    with SessionLocal() as session:
        assert mailer.deliver_pending(session) == 1
    assert outbox()[0].status == EmailStatus.SENT.value


def test_без_настроек_почты_письмо_пропускается(client, admin_headers, monkeypatch):
    monkeypatch.setattr(get_settings(), "smtp_user", "")
    set_emails(client, admin_headers, "dev", ["me@yandex.ru"])
    send(client, kind="dev")
    assert outbox()[0].status == EmailStatus.SKIPPED.value
