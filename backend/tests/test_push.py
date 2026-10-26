"""Push: подписка устройства, доставка, удаление отозванных подписок."""

import pytest
from pywebpush import WebPushException
from sqlalchemy import delete, select

from app.core.config import get_settings
from app.core.db import SessionLocal
from app.models import Message, MessageRecipient, PushSubscription
from app.services import push as push_service

API = "/api/v1"


def subscription_body(name="a"):
    return {"endpoint": f"https://push.example.com/{name}", "keys": {"p256dh": f"key-{name}", "auth": f"auth-{name}"}}


@pytest.fixture(autouse=True)
def _clean(db_schema):
    yield
    with SessionLocal() as session:
        session.execute(delete(PushSubscription))
        session.execute(delete(MessageRecipient))
        session.execute(delete(Message))
        session.commit()


@pytest.fixture
def vapid(monkeypatch):
    monkeypatch.setattr(get_settings(), "vapid_public_key", "public-key")
    monkeypatch.setattr(get_settings(), "vapid_private_key", "private-key")


@pytest.fixture
def sent(monkeypatch) -> list[tuple[str, dict]]:
    """Вместо push-сервиса — список; endpoint с «gone» отвечает 410."""
    calls: list[tuple[str, dict]] = []

    def fake_send(subscription, data):
        if "gone" in subscription.endpoint:
            response = type("Response", (), {"status_code": 410})()
            raise WebPushException("gone", response=response)
        calls.append((subscription.endpoint, data))

    monkeypatch.setattr(push_service, "_send", fake_send)
    return calls


def student(client, group_id, device):
    response = client.post(
        f"{API}/auth/student/register", json={"full_name": "Аня Андреева", "group_id": group_id, "device_key": device}
    )
    body = response.json()
    return body["profile"]["id"], {"Authorization": f"Bearer {body['access_token']}"}


def test_конфиг_без_ключей(bare_client):
    assert bare_client.get(f"{API}/push/config").json() == {"public_key": None}


def test_конфиг_с_ключами(bare_client, vapid):
    assert bare_client.get(f"{API}/push/config").json() == {"public_key": "public-key"}


def test_подписка_и_отписка(bare_client, test_groups):
    _, headers = student(bare_client, test_groups["ТЕСТ ПИ 991"], "device-push-00000001")
    created = bare_client.post(f"{API}/me/push-subscriptions", json=subscription_body(), headers=headers)
    assert created.status_code == 201

    # Повторная подписка того же браузера не плодит записи.
    again = bare_client.post(f"{API}/me/push-subscriptions", json=subscription_body(), headers=headers)
    assert again.json()["id"] == created.json()["id"]

    _, other = student(bare_client, test_groups["ТЕСТ ПИ 991"], "device-push-00000002")
    subscription_id = created.json()["id"]
    assert bare_client.delete(f"{API}/me/push-subscriptions/{subscription_id}", headers=other).status_code == 404
    assert bare_client.delete(f"{API}/me/push-subscriptions/{subscription_id}", headers=headers).status_code == 204


def test_подписка_только_по_https(bare_client, test_groups):
    _, headers = student(bare_client, test_groups["ТЕСТ ПИ 991"], "device-push-00000003")
    body = subscription_body() | {"endpoint": "http://evil.example.com/x"}
    assert bare_client.post(f"{API}/me/push-subscriptions", json=body, headers=headers).status_code == 422


def test_доставка_и_удаление_отозванной_подписки(bare_client, bare_admin_headers, test_groups, vapid, sent):
    _, anya = student(bare_client, test_groups["ТЕСТ ПИ 991"], "device-push-00000004")
    bare_client.post(f"{API}/me/push-subscriptions", json=subscription_body("phone"), headers=anya)
    bare_client.post(f"{API}/me/push-subscriptions", json=subscription_body("gone"), headers=anya)

    # TestClient выполняет фоновые задачи сразу после ответа.
    response = bare_client.post(
        f"{API}/admin/messages",
        json={"title": "Перенос пары", "body": "На четверг", "importance": "high", "target": {"type": "all"}},
        headers=bare_admin_headers,
    )
    assert response.status_code == 201

    assert len(sent) == 1
    endpoint, data = sent[0]
    assert endpoint.endswith("/phone")
    assert data["title"] == "Перенос пары"
    assert data["url"] == f"/?message={response.json()['id']}"

    with SessionLocal() as session:
        endpoints = session.scalars(select(PushSubscription.endpoint)).all()
    assert endpoints == ["https://push.example.com/phone"]


def test_напоминание_с_пометкой(bare_client, bare_admin_headers, test_groups, vapid, sent):
    _, anya = student(bare_client, test_groups["ТЕСТ ПИ 991"], "device-push-00000005")
    bare_client.post(f"{API}/me/push-subscriptions", json=subscription_body("phone"), headers=anya)
    message = bare_client.post(
        f"{API}/admin/messages",
        json={"title": "Анкета", "body": "Заполните", "target": {"type": "all"}},
        headers=bare_admin_headers,
    ).json()
    bare_client.post(f"{API}/admin/messages/{message['id']}/remind", headers=bare_admin_headers)
    assert sent[-1][1]["title"] == "Напоминание: Анкета"


def test_без_ключей_push_не_отправляется(bare_client, bare_admin_headers, test_groups, sent):
    _, anya = student(bare_client, test_groups["ТЕСТ ПИ 991"], "device-push-00000006")
    bare_client.post(f"{API}/me/push-subscriptions", json=subscription_body("phone"), headers=anya)
    bare_client.post(
        f"{API}/admin/messages",
        json={"title": "x", "body": "y", "target": {"type": "all"}},
        headers=bare_admin_headers,
    )
    assert sent == []
