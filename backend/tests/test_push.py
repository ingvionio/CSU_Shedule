"""Push: подписка устройства, доставка, удаление отозванных подписок."""

import pytest
from pywebpush import WebPushException
from sqlalchemy import delete, select

from app.core.config import get_settings
from app.core.db import SessionLocal
from app.models import Message, MessageRecipient, PushDelivery, PushSubscription
from app.services import push as push_service
from app.services.worker import process_push
from datetime import datetime, timezone

from tests.moodle_helpers import login_student

API = "/api/v1"


def subscription_body(name="a"):
    return {"endpoint": f"https://push.example.com/{name}", "keys": {"p256dh": f"key-{name}", "auth": f"auth-{name}"}}


@pytest.fixture(autouse=True)
async def _clean(db_schema):
    yield
    async with SessionLocal() as session:
        await session.execute(delete(PushDelivery))
        await session.execute(delete(PushSubscription))
        await session.execute(delete(MessageRecipient))
        await session.execute(delete(Message))
        await session.commit()


@pytest.fixture
def vapid(monkeypatch):
    monkeypatch.setattr(get_settings(), "vapid_public_key", "public-key")
    monkeypatch.setattr(get_settings(), "vapid_private_key", "private-key")


@pytest.fixture
def sent(monkeypatch) -> list[tuple[str, dict]]:
    """Вместо push-сервиса — список; endpoint с «gone» отвечает 410."""
    calls: list[tuple[str, dict]] = []

    async def fake_send(subscription, data):
        if "gone" in subscription.endpoint:
            response = type("Response", (), {"status": 410})()
            raise WebPushException("gone", response=response)
        calls.append((subscription.endpoint, data))

    monkeypatch.setattr(push_service, "_send", fake_send)
    return calls


async def student(client, group_id, device):
    response = await login_student(client, group_id, name=device, device=device)
    body = response.json()
    return body["profile"]["id"], {"Authorization": f"Bearer {body['access_token']}"}


async def test_конфиг_без_ключей(bare_client):
    assert (await bare_client.get(f"{API}/push/config")).json() == {"public_key": None, "fcm": False}


async def test_конфиг_с_ключами(bare_client, vapid):
    assert (await bare_client.get(f"{API}/push/config")).json() == {"public_key": "public-key", "fcm": False}


async def test_подписка_и_отписка(bare_client, test_groups):
    _, headers = await student(bare_client, test_groups["ТЕСТ ПИ 991"], "device-push-00000001")
    created = await bare_client.post(f"{API}/me/push-subscriptions", json=subscription_body(), headers=headers)
    assert created.status_code == 201, created.text

    # Повторная подписка того же браузера не плодит записи.
    again = await bare_client.post(f"{API}/me/push-subscriptions", json=subscription_body(), headers=headers)
    assert again.json()["id"] == created.json()["id"]

    _, other = await student(bare_client, test_groups["ТЕСТ ПИ 991"], "device-push-00000002")
    subscription_id = created.json()["id"]
    assert (await bare_client.delete(f"{API}/me/push-subscriptions/{subscription_id}", headers=other)).status_code == 404
    assert (await bare_client.delete(f"{API}/me/push-subscriptions/{subscription_id}", headers=headers)).status_code == 204


async def test_подписка_только_по_https(bare_client, test_groups):
    _, headers = await student(bare_client, test_groups["ТЕСТ ПИ 991"], "device-push-00000003")
    body = subscription_body() | {"endpoint": "http://evil.example.com/x"}
    assert (await bare_client.post(f"{API}/me/push-subscriptions", json=body, headers=headers)).status_code == 422


async def test_web_push_rejects_unlisted_provider_at_api_and_delivery(bare_client, test_groups, sent):
    _, headers = await student(bare_client, test_groups["ТЕСТ ПИ 991"], "device-push-audit")
    endpoint = "https://unlisted.example.net/subscription"
    body = subscription_body() | {"endpoint": endpoint}
    assert (await bare_client.post(f"{API}/me/push-subscriptions", json=body, headers=headers)).status_code == 422
    assert (await push_service.send_one(push_service.SubscriptionData(endpoint, "key", "auth"), {})).status == "failed"
    assert sent == []


async def test_доставка_и_удаление_отозванной_подписки(bare_client, bare_admin_headers, test_groups, vapid, sent):
    _, anya = await student(bare_client, test_groups["ТЕСТ ПИ 991"], "device-push-00000004")
    await bare_client.post(f"{API}/me/push-subscriptions", json=subscription_body("phone"), headers=anya)
    await bare_client.post(f"{API}/me/push-subscriptions", json=subscription_body("gone"), headers=anya)

    # API только пишет очередь; доставку запускает отдельный worker.
    response = await bare_client.post(
        f"{API}/admin/messages",
        json={"title": "Перенос пары", "body": "На четверг", "importance": "high", "target": {"type": "all"}},
        headers=bare_admin_headers,
    )
    assert response.status_code == 201
    assert sent == []
    async with SessionLocal() as session:
        assert (await process_push(session, datetime.now(timezone.utc))).processed == 2

    assert len(sent) == 1
    endpoint, data = sent[0]
    assert endpoint.endswith("/phone")
    assert data["title"] == "Перенос пары"
    assert data["url"] == f"/?message={response.json()['id']}"

    async with SessionLocal() as session:
        endpoints = (await session.scalars(select(PushSubscription.endpoint))).all()
    assert endpoints == ["https://push.example.com/phone"]


async def test_напоминание_с_пометкой(bare_client, bare_admin_headers, test_groups, vapid, sent):
    _, anya = await student(bare_client, test_groups["ТЕСТ ПИ 991"], "device-push-00000005")
    await bare_client.post(f"{API}/me/push-subscriptions", json=subscription_body("phone"), headers=anya)
    message = (await bare_client.post(
        f"{API}/admin/messages",
        json={"title": "Анкета", "body": "Заполните", "target": {"type": "all"}},
        headers=bare_admin_headers,
    )).json()
    await bare_client.post(f"{API}/admin/messages/{message['id']}/remind", headers=bare_admin_headers)
    async with SessionLocal() as session:
        await process_push(session, datetime.now(timezone.utc))
    assert sorted(data["title"] for _, data in sent) == ["Анкета", "Напоминание: Анкета"]


async def test_без_ключей_push_не_отправляется(bare_client, bare_admin_headers, test_groups, sent):
    _, anya = await student(bare_client, test_groups["ТЕСТ ПИ 991"], "device-push-00000006")
    await bare_client.post(f"{API}/me/push-subscriptions", json=subscription_body("phone"), headers=anya)
    await bare_client.post(
        f"{API}/admin/messages",
        json={"title": "x", "body": "y", "target": {"type": "all"}},
        headers=bare_admin_headers,
    )
    assert sent == []
