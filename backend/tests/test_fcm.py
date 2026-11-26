from unittest.mock import AsyncMock
"""FCM: контракт подписки, outbox и отправка без сети."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import httpx
from sqlalchemy import select

from app.core.config import get_settings
from app.core.db import SessionLocal
from app.models import Message, PushDelivery, PushSubscription, User
from app.services import fcm, messages, push, worker
from tests.test_notification_worker import db, create, delivery, NOW  # noqa: F401
from tests.test_push import student, subscription_body, _clean  # noqa: F401

API = "/api/v1"
TOKEN = "fcm-registration-token-123456"


@pytest.fixture(autouse=True)
def no_fcm(monkeypatch):
    monkeypatch.setattr(get_settings(), "fcm_credentials_file", "")


async def test_fcm_subscription_upsert_and_platform(bare_client, test_groups):
    _, headers = await student(bare_client, test_groups["ТЕСТ ПИ 991"], "device-fcm-000000001")
    body = {"platform": "fcm", "token": TOKEN}
    first = await bare_client.post(f"{API}/me/push-subscriptions", json=body, headers=headers)
    assert first.status_code == 201
    second = await bare_client.post(f"{API}/me/push-subscriptions", json=body, headers=headers)
    assert second.json() == first.json()
    async with SessionLocal() as session:
        item = (await session.scalars(select(PushSubscription))).one()
        assert (item.platform, item.endpoint, item.p256dh, item.auth) == ("fcm", TOKEN, None, None)
    _, other = await student(bare_client, test_groups["ТЕСТ ПИ 991"], "device-fcm-000000002")
    assert (await bare_client.delete(f"{API}/me/push-subscriptions/{first.json()['id']}", headers=other)).status_code == 404
    assert (await bare_client.delete(f"{API}/me/push-subscriptions/{first.json()['id']}", headers=headers)).status_code == 204


@pytest.mark.parametrize("body", [
    {"platform": "unknown", "token": TOKEN}, {"platform": "fcm"},
    {"platform": "fcm", "token": "x" * 19}, {"platform": "fcm", "token": "x" * 4097},
    {"platform": "web", "token": TOKEN}, {"token": TOKEN},
    {"platform": "fcm", **subscription_body()},
    {"endpoint": "https://push.example.com"}, {"platform": None, **subscription_body()},
])
async def test_invalid_subscription(bare_client, test_groups, body):
    _, headers = await student(bare_client, test_groups["ТЕСТ ПИ 991"], "device-fcm-invalid-001")
    assert (await bare_client.post(f"{API}/me/push-subscriptions", json=body, headers=headers)).status_code == 422


@pytest.mark.parametrize("length", [20, 4096])
async def test_fcm_token_boundaries(bare_client, test_groups, length):
    _, headers = await student(bare_client, test_groups["ТЕСТ ПИ 991"], "device-fcm-boundary-01")
    assert (await bare_client.post(f"{API}/me/push-subscriptions", json={"platform": "fcm", "token": "я" * length}, headers=headers)).status_code == 201


async def test_explicit_web_platform(bare_client, test_groups):
    _, headers = await student(bare_client, test_groups["ТЕСТ ПИ 991"], "device-fcm-web-000001")
    response = await bare_client.post(f"{API}/me/push-subscriptions", json={"platform": "web", **subscription_body()}, headers=headers)
    assert response.status_code == 201
    async with SessionLocal() as session:
        assert (await session.get(PushSubscription, response.json()["id"])).platform == "web"


@pytest.mark.parametrize("enabled", [True, False])
async def test_config_fcm_without_vapid(bare_client, monkeypatch, enabled):
    monkeypatch.setattr(get_settings(), "fcm_credentials_file", "/app/secrets/fcm.json" if enabled else "")
    monkeypatch.setattr(get_settings(), "vapid_public_key", "")
    monkeypatch.setattr(get_settings(), "vapid_private_key", "")
    assert (await bare_client.get(f"{API}/push/config")).json() == {"public_key": None, "fcm": enabled}


@pytest.mark.parametrize("platform", ["web", "fcm"])
async def test_enqueue_only_configured_platform_and_stats(db, monkeypatch, platform):
    user_id = (await db.scalars(select(User.id))).one()
    db.add(PushSubscription(user_id=user_id, endpoint=TOKEN, platform="fcm"))
    await db.commit()
    monkeypatch.setattr(get_settings(), "fcm_credentials_file", "/app/secrets/fcm.json" if platform == "fcm" else "")
    if platform == "fcm":
        monkeypatch.setattr(get_settings(), "vapid_private_key", "")
    message = await create(db)
    item = await delivery(db)
    assert (await db.get(PushSubscription, item.subscription_id)).platform == platform
    stats = (await messages.push_stats(db, [message.id]))[message.id]
    assert stats.configured and stats.total == 1
    reminded, devices = await messages.remind(db, message.id, NOW)
    assert (reminded, devices) == (1, 1)
    items = (await db.scalars(select(PushDelivery).where(PushDelivery.kind == "reminder"))).all()
    assert len(items) == 1 and (await db.get(PushSubscription, items[0].subscription_id)).platform == platform


async def test_worker_selects_sender_and_skips_disabled_platform(db, monkeypatch):
    monkeypatch.setattr(get_settings(), "fcm_credentials_file", "/app/secrets/fcm.json")
    user_id = (await db.scalars(select(User.id))).one()
    db.add(PushSubscription(user_id=user_id, endpoint=TOKEN, platform="fcm"))
    await db.commit()
    await create(db)
    calls = []
    monkeypatch.setattr(push, "send_one", AsyncMock(side_effect=lambda subscription, data: calls.append(("web", subscription.endpoint)) or push.SendResult("sent")))
    monkeypatch.setattr(fcm, "send_one", AsyncMock(side_effect=lambda subscription, data: calls.append(("fcm", subscription.endpoint)) or push.SendResult("sent")))
    assert (await worker.process_push(db, NOW)).sent == 2
    assert sorted(calls) == [("fcm", TOKEN), ("web", "https://push.example.com/1")]
    message = await create(db)
    monkeypatch.setattr(get_settings(), "fcm_credentials_file", "")
    calls.clear()
    result = await worker.process_push(db, NOW)
    assert (result.sent, result.skipped) == (1, 1)
    skipped = (await db.scalars(select(PushDelivery).where(PushDelivery.message_id == message.id, PushDelivery.status == "skipped"))).one()
    assert skipped.last_error == "push не настроен"
    assert calls == [("web", "https://push.example.com/1")]


@pytest.fixture
def transport(monkeypatch):
    token = AsyncMock(return_value=("test-project", "access-token"))
    post = AsyncMock(return_value=SimpleNamespace(status_code=200))
    monkeypatch.setattr(fcm, "_access_token", token)
    client = AsyncMock()
    client.__aenter__.return_value = client
    client.post = post
    monkeypatch.setattr(fcm.httpx, "AsyncClient", Mock(return_value=client))
    return token, post


def data():
    return push.payload(Message(id=12, title="Анкета", body="Заполните", importance="high"), False)


async def send():
    return await fcm.send_one(push.SubscriptionData(TOKEN, None, None, "fcm"), data())


def response(status, code=None, message="Ошибка доставки"):
    return SimpleNamespace(status_code=status, json=lambda: {"error": {
        "status": "INVALID_ARGUMENT", "message": message,
        "details": [{"@type": "type.googleapis.com/google.firebase.fcm.v1.FcmError", "errorCode": code}] if code else [],
    }})


async def test_fcm_request_body(transport):
    _, post = transport
    assert (await send()).status == "sent"
    args, kwargs = post.call_args
    assert args == ("https://fcm.googleapis.com/v1/projects/test-project/messages:send",)
    assert kwargs["headers"] == {"Authorization": "Bearer access-token"}
    assert kwargs["timeout"] == 10
    message = kwargs["json"]["message"]
    assert message == {
        "token": TOKEN,
        "notification": {"title": "Анкета", "body": "Заполните"},
        "data": {"message_id": "12", "url": "/?message=12", "importance": "high"},
        "android": {"priority": "HIGH", "ttl": "86400s", "notification": {"channel_id": "messages", "tag": "message-12"}},
    }
    assert all(isinstance(value, str) for value in message["data"].values())


@pytest.mark.parametrize("status,code,expected", [
    (404, None, "gone"), (400, "UNREGISTERED", "gone"), (403, "SENDER_ID_MISMATCH", "gone"),
    (400, "INVALID_ARGUMENT", "failed"), (403, None, "failed"),
    (429, None, "retry"), (500, None, "retry"), (503, None, "retry"),
])
async def test_fcm_http_results(transport, status, code, expected):
    transport[1].return_value = response(status, code)
    result = await send()
    assert result.status == expected
    assert "Ошибка доставки" in result.error
    if code:
        assert code in result.error


async def test_fcm_error_does_not_store_response_payload(transport):
    transport[1].return_value = response(400, "UNEXPECTEDVALUE", message=TOKEN)
    result = await send()
    assert result.error == "Ошибка доставки: FCM HTTP 400"


@pytest.mark.parametrize("error", [httpx.TimeoutException("таймаут"), httpx.ConnectError("сеть")])
async def test_fcm_network_retry(transport, error):
    transport[1].side_effect = error
    assert (await send()).status == "retry"


async def test_fcm_non_json_response(transport):
    transport[1].return_value = SimpleNamespace(status_code=503, json=Mock(side_effect=ValueError("не JSON")))
    assert (await send()).status == "retry"


async def test_fcm_401_resets_token_and_retries_once(transport, monkeypatch):
    token, post = transport
    invalidate = AsyncMock()
    monkeypatch.setattr(fcm, "_invalidate_token", invalidate)
    token.side_effect = [("test-project", "old"), ("test-project", "fresh")]
    post.side_effect = [response(401), SimpleNamespace(status_code=200)]
    assert (await send()).status == "sent"
    invalidate.assert_called_once_with("old")
    assert [call.kwargs["headers"]["Authorization"] for call in post.call_args_list] == ["Bearer old", "Bearer fresh"]
    post.side_effect = None
    post.return_value = response(401)
    token.side_effect = None
    assert (await send()).status == "retry"
    assert post.call_count == 4


async def test_oauth_credentials_cached_expired_and_invalidated(monkeypatch):
    monkeypatch.setattr(get_settings(), "fcm_credentials_file", "test-key.json")
    credentials = Mock(project_id="test-project", valid=False, token=None)

    def refresh(_):
        credentials.token = "fresh"
        credentials.valid = True

    credentials.refresh.side_effect = refresh
    monkeypatch.setattr(fcm, "_refresh_credentials", AsyncMock(side_effect=lambda item: item.refresh(None)))
    factory = Mock(return_value=credentials)
    monkeypatch.setattr(fcm, "_load_credentials", factory)
    monkeypatch.setattr(fcm, "_credentials", None)
    assert await fcm._access_token() == ("test-project", "fresh")
    assert await fcm._access_token() == ("test-project", "fresh")
    assert factory.call_count == 1 and credentials.refresh.call_count == 1
    credentials.valid = False
    await fcm._access_token()
    assert credentials.refresh.call_count == 2
    await fcm._invalidate_token("fresh")
    assert credentials.token is None
    credentials.valid = False
    await fcm._access_token()
    assert credentials.refresh.call_count == 3
