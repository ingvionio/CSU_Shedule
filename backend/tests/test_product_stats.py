"""ЛК продукта: вход, приём событий, события входа Moodle и метрики."""

from datetime import date, datetime, timedelta, timezone
from unittest.mock import AsyncMock, Mock

import pytest
from sqlalchemy import delete, select

from app.core.config import get_settings
from app.core.db import SessionLocal
from app.core.security import ROLE_STUDENT, issue_token
from tests.moodle_helpers import login_student
from app.models import EmailOutbox, FeedbackMessage, Message, MessageRecipient, ProductEvent, PushSubscription, User
from tests.test_notes import notes_demo  # noqa: F401 — фикстура для события заметки
from app.services import product_stats
from app.services.feedback import secret_hash

DEVICE = "device-key-0001"
NOW = datetime(2026, 11, 19, 12, 0, tzinfo=timezone.utc)  # 17:00 по Челябинску


@pytest.fixture
async def product(bare_client, monkeypatch):
    monkeypatch.setattr(get_settings(), "product_password", "prod-secret")
    async with SessionLocal() as session:
        await session.execute(delete(ProductEvent))
        await session.commit()
    yield bare_client
    async with SessionLocal() as session:
        for model in (ProductEvent, PushSubscription, MessageRecipient, Message, EmailOutbox, FeedbackMessage, User):
            await session.execute(delete(model))
        await session.commit()


@pytest.fixture
async def product_headers(product) -> dict[str, str]:
    response = await product.post("/api/v1/auth/product/login", json={"login": "product", "password": "prod-secret"})
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


async def _student(name: str, group_id: int | None = None, created_at: datetime = NOW) -> int:
    async with SessionLocal() as session:
        user = User(full_name=name, group_id=group_id, role="student", created_at=created_at)
        session.add(user)
        await session.commit()
        return user.id


def _student_headers(user_id: int) -> dict[str, str]:
    token, _ = issue_token(str(user_id), ROLE_STUDENT, 1)
    return {"Authorization": f"Bearer {token}"}


async def _events(*items: tuple[str, datetime, int | None, str | None, str | None]) -> None:
    """(имя, время, user_id, устройство, платформа)."""
    async with SessionLocal() as session:
        session.add_all(
            ProductEvent(
                name=name,
                occurred_at=moment,
                user_id=user_id,
                device_hash=secret_hash(device) if device else None,
                platform=platform,
            )
            for name, moment, user_id, device, platform in items
        )
        await session.commit()


async def _stored() -> list[ProductEvent]:
    async with SessionLocal() as session:
        return list(await session.scalars(select(ProductEvent).order_by(ProductEvent.id)))


# --- вход в ЛК ---


async def test_product_login(product):
    ok = await product.post("/api/v1/auth/product/login", json={"login": "product", "password": "prod-secret"})
    assert ok.status_code == 200 and ok.json()["access_token"]
    wrong = await product.post("/api/v1/auth/product/login", json={"login": "product", "password": "nope"})
    assert wrong.status_code == 401


async def test_product_login_disabled_without_password(product, monkeypatch):
    monkeypatch.setattr(get_settings(), "product_password", "")
    response = await product.post("/api/v1/auth/product/login", json={"login": "product", "password": ""})
    assert response.status_code == 401
    assert "PRODUCT_PASSWORD" in response.json()["detail"]


async def test_roles_are_separated(product, product_headers, bare_admin_headers):
    student = _student_headers(await _student("Иванов Иван"))
    assert (await product.get("/api/v1/product/summary")).status_code == 401
    assert (await product.get("/api/v1/product/summary", headers=bare_admin_headers)).status_code == 403
    assert (await product.get("/api/v1/product/summary", headers=student)).status_code == 403
    assert (await product.get("/api/v1/product/summary", headers=product_headers)).status_code == 200
    assert (await product.get("/api/v1/admin/catalog", headers=product_headers)).status_code == 403
    assert (await product.get("/api/v1/me", headers=product_headers)).status_code == 403


# --- приём событий ---


async def test_events_anonymous_and_filtered(product):
    response = await product.post(
        "/api/v1/events",
        json={
            "device_key": DEVICE,
            "platform": "PWA",
            "app_version": "1.2.0",
            "events": [{"name": "landing_view"}, {"name": "unknown_thing"}, {"name": "login_success"}],
        },
    )
    assert response.status_code == 204
    stored = await _stored()
    assert [(e.name, e.user_id, e.platform, e.app_version) for e in stored] == [("landing_view", None, "pwa", "1.2.0")]
    assert stored[0].device_hash == secret_hash(DEVICE)
    assert all(DEVICE not in (e.device_hash or "") for e in stored)


async def test_events_user_comes_from_token_only(product, test_groups):
    login = await login_student(product, test_groups["ТЕСТ ПИ 991"], "Петров Пётр")
    body = login.json()
    user_id = body["profile"]["id"]
    headers = {"Authorization": f"Bearer {body['access_token']}"}
    response = await product.post(
        "/api/v1/events",
        headers=headers,
        json={"device_key": DEVICE, "user_id": 999, "events": [{"name": "app_open"}]},
    )
    assert response.status_code == 204
    old_headers = _student_headers(user_id)
    assert (await product.post(
        "/api/v1/events", headers=old_headers, json={"device_key": DEVICE, "events": [{"name": "app_open"}]}
    )).status_code == 204
    assert (await product.post("/api/v1/auth/moodle/forget", headers=headers)).status_code == 200
    assert (await product.post(
        "/api/v1/events", headers=headers, json={"device_key": DEVICE, "events": [{"name": "app_open"}]}
    )).status_code == 204
    assert [e.user_id for e in await _stored() if e.name == "app_open"] == [user_id, None, None]


async def test_events_bad_token_is_anonymous(product, bare_admin_headers):
    expired, _ = issue_token("1", ROLE_STUDENT, -1)
    for headers in (bare_admin_headers, {"Authorization": f"Bearer {expired}"}, {"Authorization": "Bearer junk"}):
        response = await product.post("/api/v1/events", headers=headers, json={"device_key": DEVICE, "events": [{"name": "app_open"}]})
        assert response.status_code == 204
    assert [e.user_id for e in await _stored()] == [None, None, None]


async def test_events_token_of_deleted_user_is_anonymous(product):
    response = await product.post(
        "/api/v1/events", headers=_student_headers(987654), json={"device_key": DEVICE, "events": [{"name": "app_open"}]}
    )
    assert response.status_code == 204
    assert [e.user_id for e in await _stored()] == [None]


async def test_events_batch_size_and_limit(product, monkeypatch):
    too_many = {"device_key": DEVICE, "events": [{"name": "app_open"}] * 21}
    assert (await product.post("/api/v1/events", json=too_many)).status_code == 422

    monkeypatch.setattr(get_settings(), "product_events_limit_per_hour", 3)
    batch = {"device_key": DEVICE, "events": [{"name": "app_open"}] * 2}
    for _ in range(3):
        assert (await product.post("/api/v1/events", json=batch)).status_code == 204
    assert len(await _stored()) == 3
    other = {"device_key": "another-device-1", "events": [{"name": "app_open"}]}
    assert (await product.post("/api/v1/events", json=other)).status_code == 204
    assert len(await _stored()) == 4


# --- события входа Moodle ---


@pytest.fixture
def moodle(monkeypatch):
    from app.services import moodle

    monkeypatch.setattr(get_settings(), "moodle_mock", False)
    monkeypatch.setattr(moodle.MoodleClient, "execute_login", AsyncMock(return_value=('{"sessiontimeout":7200}', "key")))
    monkeypatch.setattr(moodle.MoodleClient, "get_profile_info", AsyncMock(return_value=("Сидоров Сидор", "777", "key", "")))
    monkeypatch.setattr(moodle.MoodleClient, "cookies", lambda self: {"MoodleSession": "fake-cookie"})
    monkeypatch.setattr(moodle.MoodleClient, "get_enrolled_courses", AsyncMock(return_value=[]))
    monkeypatch.setattr(moodle, "match_student_group", lambda courses, html, groups: groups[0])
    return moodle


async def _login(client):
    return await client.post(
        "/api/v1/auth/moodle/login",
        headers={"X-Client-Platform": "apk", "X-Client-Version": "1.1.1"},
        json={"username": "sidorov", "password": "pw", "device_key": DEVICE},
    )


async def test_login_success_event(product, test_groups, moodle):
    response = await _login(product)
    assert response.status_code == 200
    [event] = await _stored()
    assert event.name == "login_success"
    assert event.user_id == response.json()["profile"]["id"]
    assert (event.device_hash, event.platform, event.app_version) == (secret_hash(DEVICE), "apk", "1.1.1")


@pytest.mark.parametrize(
    ("error", "name"),
    [("MoodleAuthError", "login_failed_auth"), ("MoodleGroupError", "login_failed_group"), ("MoodleError", "login_failed_other")],
)
async def test_login_failure_events(product, test_groups, moodle, monkeypatch, error, name):
    exc = getattr(moodle, error)
    monkeypatch.setattr(moodle.MoodleClient, "execute_login", AsyncMock(side_effect=exc("сбой") if error != "MoodleGroupError" else exc()))
    response = await _login(product)
    assert response.status_code >= 400
    assert [(e.name, e.user_id) for e in await _stored()] == [(name, None)]


async def test_broken_event_write_does_not_break_login(product, test_groups, moodle, monkeypatch):
    from app.services import product_events

    monkeypatch.setattr(product_events, "_event", Mock(side_effect=RuntimeError("БД упала")))
    response = await _login(product)
    assert response.status_code == 200 and response.json()["access_token"]
    assert await _stored() == []


# --- события в приложении ---


async def _named(user_id: int | None = None) -> list[str]:
    return [e.name for e in await _stored() if user_id is None or e.user_id == user_id]


async def _register(client, group_id: int, device: str) -> tuple[int, dict[str, str]]:
    response = await login_student(client, group_id, "Аня Андреева", device)
    assert response.status_code == 200, response.text
    body = response.json()
    return body["profile"]["id"], {"Authorization": f"Bearer {body['access_token']}"}


async def _send_message(client, headers, importance="high", title="Перенос пары") -> dict:
    response = await client.post(
        "/api/v1/admin/messages",
        headers=headers,
        json={"title": title, "body": "На четверг", "importance": importance, "target": {"type": "all"}},
    )
    assert response.status_code == 201, response.text
    return response.json()


@pytest.fixture
def no_push(monkeypatch):
    from app.services import push as push_service

    monkeypatch.setattr(push_service, "notify_message", AsyncMock())


async def test_client_screen_events_accepted(product):
    names = ["schedule_day_view", "schedule_week_view", "map_open", "help_open", "push_open", "message_read"]
    await product.post("/api/v1/events", json={"device_key": DEVICE, "events": [{"name": n} for n in names]})
    # message_read пишет только сервер — от клиента пропускается.
    assert await _named() == names[:-1]


async def test_message_events(product, bare_admin_headers, test_groups, no_push):
    anya, headers = await _register(product, test_groups["ТЕСТ ПИ 991"], "device-anya-events-01")
    sent = await _send_message(product, bare_admin_headers)
    await product.get(f"/api/v1/me/messages/{sent['id']}", headers=headers)
    await product.get(f"/api/v1/me/messages/{sent['id']}", headers=headers)  # повторное открытие — не новое событие
    await product.post(f"/api/v1/me/messages/{sent['id']}/acknowledge", headers=headers)
    await product.post(f"/api/v1/me/messages/{sent['id']}/acknowledge", headers=headers)
    assert await _named(anya) == ["login_success", "message_received", "message_read", "message_ack"]
    assert all(e.props == {"message_id": sent["id"]} for e in await _stored() if e.user_id == anya and e.name != "login_success")


async def test_ack_without_open_counts_read(product, bare_admin_headers, test_groups, no_push):
    anya, headers = await _register(product, test_groups["ТЕСТ ПИ 991"], "device-anya-events-02")
    sent = await _send_message(product, bare_admin_headers)
    await product.post(f"/api/v1/me/messages/{sent['id']}/acknowledge", headers=headers)
    assert await _named(anya) == ["login_success", "message_received", "message_read", "message_ack"]


async def test_push_events(product, bare_admin_headers, test_groups, monkeypatch):
    from app.services import push as push_service

    monkeypatch.setattr(get_settings(), "vapid_public_key", "public-key")
    monkeypatch.setattr(get_settings(), "vapid_private_key", "private-key")
    monkeypatch.setattr(push_service, "_send", AsyncMock())
    anya, headers = await _register(product, test_groups["ТЕСТ ПИ 991"], "device-anya-events-03")
    for name in ("phone", "laptop"):
        body = {"endpoint": f"https://push.example.com/{name}", "keys": {"p256dh": "k", "auth": "a"}}
        assert (await product.post("/api/v1/me/push-subscriptions", json=body, headers=headers)).status_code == 201
    await _send_message(product, bare_admin_headers, importance="normal")
    # Два устройства — одно событие доставки на студента.
    assert await _named(anya) == ["login_success", "push_subscribed", "push_subscribed", "message_received", "push_sent"]


async def test_feedback_event(product, test_groups):
    anya, headers = await _register(product, test_groups["ТЕСТ ПИ 991"], "device-anya-events-04")
    payload = {"kind": "methodist", "text": "Когда будет пересдача?"}
    with_user = await product.post("/api/v1/feedback", json=payload, headers={**headers, "X-Feedback-Token": "device-anya-events-04"})
    anonymous = await product.post("/api/v1/feedback", json=payload, headers={"X-Feedback-Token": "guest-device-000001"})
    assert with_user.status_code == anonymous.status_code == 201
    events = [(e.user_id, e.device_hash) for e in await _stored() if e.name == "feedback_sent"]
    assert events == [(anya, secret_hash("device-anya-events-04")), (None, secret_hash("guest-device-000001"))]


async def test_note_event(product, notes_demo, monkeypatch):  # noqa: F811
    from app.services import product_events
    from tests.test_notes import save

    group, lesson, owner, _ = notes_demo
    created = await save(product, owner, group, lesson)
    assert created.status_code == 200
    assert "note_saved" in await _named()

    monkeypatch.setattr(product_events, "_event", Mock(side_effect=RuntimeError("Ошибка статистики")))
    updated = await save(product, owner, group, lesson, body="Новый текст", version=created.json()["version"])
    assert updated.status_code == 200
    assert updated.json()["body"] == "Новый текст"


# --- метрики ---


TODAY = date(2026, 11, 19)


async def _summary(days: int = 30, end: date = TODAY, now: datetime = NOW) -> dict:
    async with SessionLocal() as session:
        return await session.run_sync(product_stats.summary, end - timedelta(days=days - 1), end, now=now)


OLD = NOW - timedelta(days=200)  # профиль создан давно — его дата не попадает в периоды теста


async def test_active_users_and_local_day(product):
    a, b, c = await _student("А", created_at=OLD), await _student("Б", created_at=OLD), await _student("В", created_at=OLD)
    await _events(
        ("app_open", NOW, a, "d1", "web"),
        ("app_open", NOW - timedelta(hours=1), a, "d1", "web"),
        ("login_success", NOW - timedelta(days=3), b, "d2", "pwa"),
        ("app_open", NOW - timedelta(days=20), c, "d3", "apk"),
        ("app_open", NOW - timedelta(days=40), c, "d3", "apk"),
        ("landing_view", NOW, None, "d9", "web"),  # гость: не активный пользователь
    )
    data = await _summary(30)
    assert (data["dau"], data["wau"], data["mau"], data["active_users"]) == (1, 2, 3, 3)
    assert data["users_total"] == 3
    assert data["by_platform"] == {"web": 1, "pwa": 1, "apk": 1}
    assert data["daily"][-1]["dau"] == 1 and len(data["daily"]) == 30
    # 7 дней: «В» заходил 20 дней назад — за период не активен, а MAU (по последнему дню) тот же.
    week = await _summary(7)
    assert (week["active_users"], week["mau"]) == (2, 3)


async def test_custom_period_in_the_past(product):
    user = await _student("Прошлый", created_at=OLD)
    await _events(("app_open", datetime(2026, 9, 10, 6, tzinfo=timezone.utc), user, "d1", "web"))
    async with SessionLocal() as session:
        data = await session.run_sync(product_stats.summary, date(2026, 9, 1), date(2026, 9, 30), now=NOW)
    assert (data["days"], data["active_users"], data["dau"]) == (30, 1, 0)
    assert (await _summary(30))["active_users"] == 0


async def test_period_validation(product, product_headers):
    reversed_period = await product.get("/api/v1/product/summary?start=2026-11-10&end=2026-11-01", headers=product_headers)
    too_long = await product.get("/api/v1/product/summary?start=2020-01-01&end=2026-11-01", headers=product_headers)
    default = await product.get("/api/v1/product/summary", headers=product_headers)
    assert reversed_period.status_code == too_long.status_code == 422
    assert default.status_code == 200 and default.json()["days"] == 30


async def test_late_utc_evening_is_next_local_day(product):
    user = await _student("Ночной")
    late = datetime(2026, 11, 18, 23, 30, tzinfo=timezone.utc)  # 19.11 04:30 по Челябинску
    await _events(("app_open", late, user, "d1", None))
    data = await _summary(1)
    assert data["dau"] == 1
    assert data["start_date"].isoformat() == "2026-11-19"


async def test_funnel_counts_unique_devices(product):
    user = await _student("Воронкин")
    await _events(
        ("landing_view", NOW, None, "d1", "web"),
        ("landing_view", NOW, None, "d1", "web"),
        ("landing_view", NOW, None, "d2", "web"),
        ("landing_view", NOW - timedelta(days=10), None, "d3", "web"),  # вне периода 7 дней
        ("login_click", NOW, None, "d1", "web"),
        ("login_submit", NOW, None, "d1", "web"),
        ("login_submit", NOW, None, "d1", "web"),
        ("login_failed_auth", NOW, None, "d1", "web"),
        ("login_success", NOW, user, "d1", "web"),
    )
    data = await _summary(7)
    assert data["funnel"] == {
        "landing_view": 2, "login_click": 1, "login_submit": 1, "login_success": 1,
        "login_any": 1, "login_without_landing": 0,
    }
    assert data["login_failures"] == {"auth": 1, "group": 0, "other": 0}


async def test_funnel_is_strict_and_counts_logins_without_landing(product):
    """Форму можно открыть не с лендинга; шаг считается только среди прошедших предыдущий — конверсия ≤ 100%."""
    a, b = await _student("А", created_at=OLD), await _student("Б", created_at=OLD)
    await _events(
        ("landing_view", NOW, None, "d1", "web"),
        ("login_click", NOW, None, "d1", "web"),
        ("login_submit", NOW, None, "d1", "web"),
        ("login_success", NOW, a, "d1", "web"),
        # Пришёл по прямой ссылке: формы входа и вход без лендинга.
        ("login_click", NOW, None, "d2", "apk"),
        ("login_submit", NOW, None, "d2", "apk"),
        ("login_success", NOW, b, "d2", "apk"),
        # Отправил форму, минуя шаг «открыл форму» (старая сборка).
        ("landing_view", NOW, None, "d3", "web"),
        ("login_submit", NOW, None, "d3", "web"),
    )
    funnel = (await _summary(7))["funnel"]
    assert funnel == {
        "landing_view": 2, "login_click": 1, "login_submit": 1, "login_success": 1,
        "login_any": 2, "login_without_landing": 1,
    }


async def test_first_login_and_session_activity_count_as_active(product):
    """Активность до сбора событий: дни первого входа и последней активности сессии из профиля."""
    first = await _student("Новичок", created_at=NOW - timedelta(days=2))
    await _student("Старый", created_at=OLD)
    async with SessionLocal() as session:
        user = await session.get(User, first)
        user.session_last_active_at = NOW
        await session.commit()
    data = await _summary(7)
    assert data["active_users"] == 1
    assert [day["dau"] for day in data["daily"][-3:]] == [1, 0, 1]


async def test_passive_events_do_not_make_active(product):
    user = await _student("Получатель", created_at=OLD)
    await _events(("message_received", NOW, user, None, None), ("push_sent", NOW, user, None, None))
    assert (await _summary(7))["active_users"] == 0
    await _events(("schedule_week_view", NOW, user, "d1", "web"))
    assert (await _summary(7))["active_users"] == 1


async def test_tracking_since(product):
    assert (await _summary(7))["tracking_since"] is None
    await _events(("landing_view", NOW - timedelta(days=3), None, "d1", "web"))
    assert (await _summary(7))["tracking_since"].isoformat() == "2026-11-16"


async def test_apk_downloads_and_installs(product):
    await _events(
        ("apk_download", NOW, None, "d1", "web"),
        ("apk_download", NOW, None, "d2", "web"),
        ("app_open", NOW - timedelta(days=60), None, "old", "apk"),
        ("app_open", NOW - timedelta(days=1), None, "a1", "apk"),
        ("app_open", NOW, None, "a1", "apk"),
        ("landing_view", NOW, None, "a2", "apk"),
        ("app_open", NOW, None, "w1", "web"),
    )
    data = await _summary(7)
    assert (data["apk_downloads"], data["apk_installs"], data["apk_installs_total"]) == (2, 2, 3)


async def test_features(product):
    a, b = await _student("А"), await _student("Б")
    await _events(
        ("schedule_week_view", NOW, a, "d1", "web"),
        ("schedule_week_view", NOW, a, "d1", "web"),
        ("schedule_week_view", NOW, b, "d2", "web"),
        ("feedback_sent", NOW, None, "d3", "web"),
        ("message_ack", NOW - timedelta(days=40), a, None, None),
    )
    features = {f["name"]: (f["events"], f["users"]) for f in (await _summary(30))["features"]}
    assert features["schedule_week_view"] == (3, 2)
    assert features["feedback_sent"] == (1, 0)
    assert features["message_ack"] == (0, 0)
    assert features["map_open"] == (0, 0)


async def test_retention(product):
    # Пришли 1.10: один вернулся на 1-й неделе (9.10), второй — нет; третий пришёл 15.11 — его неделя не закончилась.
    first = datetime(2026, 10, 1, 5, tzinfo=timezone.utc)
    back, gone = await _student("Вернулся", created_at=first), await _student("Ушёл", created_at=first)
    fresh = await _student("Новичок", created_at=datetime(2026, 11, 15, 5, tzinfo=timezone.utc))
    await _events(
        ("login_success", first, back, "d1", "web"),
        ("login_success", first, gone, "d2", "web"),
        ("app_open", datetime(2026, 10, 9, 5, tzinfo=timezone.utc), back, "d1", "web"),
        ("login_success", datetime(2026, 11, 15, 5, tzinfo=timezone.utc), fresh, "d3", "web"),
    )
    async with SessionLocal() as session:
        data = await session.run_sync(product_stats.summary, date(2026, 9, 21), TODAY, now=NOW)
    week = {r["week"]: (r["eligible"], r["returned"]) for r in data["retention"]}
    assert week == {1: (2, 1), 2: (2, 0), 4: (2, 0)}


async def test_groups_coverage_and_push_share(product, test_groups):
    pi = test_groups["ТЕСТ ПИ 991"]
    a = await _student("А", pi)
    await _student("Б", pi, created_at=NOW - timedelta(days=60))
    await _events(("app_open", NOW, a, "d1", "web"))
    async with SessionLocal() as session:
        session.add(PushSubscription(user_id=a, endpoint="https://push.example.com/x", p256dh="k", auth="a"))
        await session.commit()
    data = await _summary(30)
    groups = {g["name"]: (g["users"], g["new"], g["active"]) for g in data["groups"]}
    assert groups["ТЕСТ ПИ 991"] == (2, 1, 1)
    assert groups["ТЕСТ БИ 991"] == (0, 0, 0)
    assert data["users_with_push"] == 1


# --- пользователи ---


async def test_users_list_filters_and_card(product, product_headers, test_groups):
    group_id = test_groups["ТЕСТ ПИ 991"]
    old = await _student("Старов Олег", group_id, created_at=datetime(2026, 9, 5, 5, tzinfo=timezone.utc))
    fresh = await _student("Новикова Анна", created_at=datetime.now(timezone.utc) - timedelta(days=1))
    recent = datetime.now(timezone.utc) - timedelta(hours=2)
    await _events(
        ("login_success", recent - timedelta(hours=1), old, "d1", "web"),
        ("app_open", recent, old, "d1", "apk"),
        ("schedule_week_view", recent, old, "d1", "apk"),
    )

    async def ids(**params):
        body = (await product.get("/api/v1/product/users", params=params, headers=product_headers)).json()
        return [item["id"] for item in body["items"]], body["total"]

    assert await ids() == ([old, fresh], 2)
    assert (await ids(sort="created"))[0] == [fresh, old]
    assert (await ids(sort="name"))[0] == [fresh, old]
    assert (await ids(sort="name", order="desc"))[0] == [old, fresh]
    assert (await ids(sort="created", order="asc"))[0] == [old, fresh]
    # Без группы — в конце при любом направлении.
    assert (await ids(sort="group"))[0] == [old, fresh]
    assert (await ids(sort="group", order="desc"))[0] == [old, fresh]
    assert (await product.get("/api/v1/product/users?order=sideways", headers=product_headers)).status_code == 422
    assert await ids(q="Новикова") == ([fresh], 1)
    assert await ids(group_id=group_id) == ([old], 1)
    assert await ids(created_from="2026-09-01", created_to="2026-09-30") == ([old], 1)
    assert await ids(last_seen_to="2026-09-30") == ([], 0)
    assert old in (await ids(last_seen_from=product_stats.local_date(recent).isoformat()))[0]

    first = (await product.get("/api/v1/product/users", headers=product_headers)).json()["items"][0]
    assert first["group"] == {"id": group_id, "name": "ТЕСТ ПИ 991", "course": 1}
    assert first["last_platform"] == "apk" and first["active_days_30"] >= 1

    card = (await product.get(f"/api/v1/product/users/{old}", headers=product_headers)).json()
    assert card["counts"] == {"login_success": 1, "app_open": 1, "schedule_week_view": 1}
    assert card["push_enabled"] is False

    page = (await product.get(f"/api/v1/product/users/{old}/events?limit=2", headers=product_headers)).json()
    assert [e["name"] for e in page["items"]] == ["schedule_week_view", "app_open"]
    rest = (await product.get(
        f"/api/v1/product/users/{old}/events?limit=2&before={page['next_before']}", headers=product_headers
    )).json()
    assert [e["name"] for e in rest["items"]] == ["login_success"] and rest["next_before"] is None

    assert (await product.get("/api/v1/product/users/999999", headers=product_headers)).status_code == 404
    assert (await product.get("/api/v1/product/users/999999/events", headers=product_headers)).status_code == 404


async def test_user_events_ordered_by_time(product, product_headers):
    user = await _student("Хронолог")
    # Вставлены не по порядку: лента всё равно от новых к старым по времени.
    await _events(
        ("app_open", NOW, user, "d1", "web"),
        ("message_read", NOW - timedelta(days=2), user, None, None),
        ("map_open", NOW - timedelta(days=1), user, "d1", "web"),
    )
    page = (await product.get(f"/api/v1/product/users/{user}/events?limit=2", headers=product_headers)).json()
    rest = (await product.get(f"/api/v1/product/users/{user}/events?limit=2&before={page['next_before']}", headers=product_headers)).json()
    assert [e["name"] for e in page["items"] + rest["items"]] == ["app_open", "map_open", "message_read"]


async def test_message_title_in_user_events(product, product_headers, bare_admin_headers, test_groups, no_push):
    anya, _ = await _register(product, test_groups["ТЕСТ ПИ 991"], "device-anya-events-05")
    await _send_message(product, bare_admin_headers, importance="normal")
    items = (await product.get(f"/api/v1/product/users/{anya}/events", headers=product_headers)).json()["items"]
    assert [(e["name"], e["detail"]) for e in items] == [("message_received", "Перенос пары"), ("login_success", None)]
