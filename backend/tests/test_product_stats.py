"""ЛК продукта: вход, приём событий, события входа Moodle и метрики."""

from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

import pytest
from sqlalchemy import delete, select

from app.core.config import get_settings
from app.core.db import SessionLocal
from app.core.security import ROLE_STUDENT, issue_token
from app.models import ProductEvent, User
from app.services import product_stats
from app.services.feedback import secret_hash

DEVICE = "device-key-0001"
NOW = datetime(2026, 11, 19, 12, 0, tzinfo=timezone.utc)  # 17:00 по Челябинску


@pytest.fixture
def product(bare_client, monkeypatch):
    monkeypatch.setattr(get_settings(), "product_password", "prod-secret")
    with SessionLocal() as session:
        session.execute(delete(ProductEvent))
        session.commit()
    yield bare_client
    with SessionLocal() as session:
        session.execute(delete(ProductEvent))
        session.execute(delete(User))
        session.commit()


@pytest.fixture
def product_headers(product) -> dict[str, str]:
    response = product.post("/api/v1/auth/product/login", json={"login": "product", "password": "prod-secret"})
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def _student(name: str, group_id: int | None = None, created_at: datetime = NOW) -> int:
    with SessionLocal() as session:
        user = User(full_name=name, group_id=group_id, role="student", created_at=created_at)
        session.add(user)
        session.commit()
        return user.id


def _student_headers(user_id: int) -> dict[str, str]:
    token, _ = issue_token(str(user_id), ROLE_STUDENT, 1)
    return {"Authorization": f"Bearer {token}"}


def _events(*items: tuple[str, datetime, int | None, str | None, str | None]) -> None:
    """(имя, время, user_id, устройство, платформа)."""
    with SessionLocal() as session:
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
        session.commit()


def _stored() -> list[ProductEvent]:
    with SessionLocal() as session:
        return list(session.scalars(select(ProductEvent).order_by(ProductEvent.id)))


# --- вход в ЛК ---


def test_product_login(product):
    ok = product.post("/api/v1/auth/product/login", json={"login": "product", "password": "prod-secret"})
    assert ok.status_code == 200 and ok.json()["access_token"]
    wrong = product.post("/api/v1/auth/product/login", json={"login": "product", "password": "nope"})
    assert wrong.status_code == 401


def test_product_login_disabled_without_password(product, monkeypatch):
    monkeypatch.setattr(get_settings(), "product_password", "")
    response = product.post("/api/v1/auth/product/login", json={"login": "product", "password": ""})
    assert response.status_code == 401
    assert "PRODUCT_PASSWORD" in response.json()["detail"]


def test_roles_are_separated(product, product_headers, bare_admin_headers):
    student = _student_headers(_student("Иванов Иван"))
    assert product.get("/api/v1/product/summary").status_code == 401
    assert product.get("/api/v1/product/summary", headers=bare_admin_headers).status_code == 403
    assert product.get("/api/v1/product/summary", headers=student).status_code == 403
    assert product.get("/api/v1/product/summary", headers=product_headers).status_code == 200
    assert product.get("/api/v1/admin/catalog", headers=product_headers).status_code == 403
    assert product.get("/api/v1/me", headers=product_headers).status_code == 403


# --- приём событий ---


def test_events_anonymous_and_filtered(product):
    response = product.post(
        "/api/v1/events",
        json={
            "device_key": DEVICE,
            "platform": "PWA",
            "app_version": "1.2.0",
            "events": [{"name": "landing_view"}, {"name": "unknown_thing"}, {"name": "login_success"}],
        },
    )
    assert response.status_code == 204
    stored = _stored()
    assert [(e.name, e.user_id, e.platform, e.app_version) for e in stored] == [("landing_view", None, "pwa", "1.2.0")]
    assert stored[0].device_hash == secret_hash(DEVICE)
    assert all(DEVICE not in (e.device_hash or "") for e in stored)


def test_events_user_comes_from_token_only(product):
    user_id = _student("Петров Пётр")
    response = product.post(
        "/api/v1/events",
        headers=_student_headers(user_id),
        json={"device_key": DEVICE, "user_id": 999, "events": [{"name": "app_open"}]},
    )
    assert response.status_code == 204
    assert [e.user_id for e in _stored()] == [user_id]


def test_events_bad_token_is_anonymous(product, bare_admin_headers):
    expired, _ = issue_token("1", ROLE_STUDENT, -1)
    for headers in (bare_admin_headers, {"Authorization": f"Bearer {expired}"}, {"Authorization": "Bearer junk"}):
        response = product.post("/api/v1/events", headers=headers, json={"device_key": DEVICE, "events": [{"name": "app_open"}]})
        assert response.status_code == 204
    assert [e.user_id for e in _stored()] == [None, None, None]


def test_events_batch_size_and_limit(product, monkeypatch):
    too_many = {"device_key": DEVICE, "events": [{"name": "app_open"}] * 21}
    assert product.post("/api/v1/events", json=too_many).status_code == 422

    monkeypatch.setattr(get_settings(), "product_events_limit_per_hour", 3)
    batch = {"device_key": DEVICE, "events": [{"name": "app_open"}] * 2}
    for _ in range(3):
        assert product.post("/api/v1/events", json=batch).status_code == 204
    assert len(_stored()) == 3
    other = {"device_key": "another-device-1", "events": [{"name": "app_open"}]}
    assert product.post("/api/v1/events", json=other).status_code == 204
    assert len(_stored()) == 4


# --- события входа Moodle ---


@pytest.fixture
def moodle(monkeypatch):
    from app.services import moodle

    monkeypatch.setattr(get_settings(), "moodle_mock", False)
    monkeypatch.setattr(moodle.MoodleClient, "execute_login", Mock(return_value=("", "key")))
    monkeypatch.setattr(moodle.MoodleClient, "get_profile_info", Mock(return_value=("Сидоров Сидор", "777", "key", "")))
    monkeypatch.setattr(moodle.MoodleClient, "get_enrolled_courses", Mock(return_value=[]))
    monkeypatch.setattr(moodle, "match_student_group", lambda courses, html, groups: groups[0])
    return moodle


def _login(client):
    return client.post(
        "/api/v1/auth/moodle/login",
        headers={"X-Client-Platform": "apk", "X-Client-Version": "1.1.1"},
        json={"username": "sidorov", "password": "pw", "device_key": DEVICE},
    )


def test_login_success_event(product, test_groups, moodle):
    response = _login(product)
    assert response.status_code == 200
    [event] = _stored()
    assert event.name == "login_success"
    assert event.user_id == response.json()["profile"]["id"]
    assert (event.device_hash, event.platform, event.app_version) == (secret_hash(DEVICE), "apk", "1.1.1")


@pytest.mark.parametrize(
    ("error", "name"),
    [("MoodleAuthError", "login_failed_auth"), ("MoodleGroupError", "login_failed_group"), ("MoodleError", "login_failed_other")],
)
def test_login_failure_events(product, test_groups, moodle, monkeypatch, error, name):
    exc = getattr(moodle, error)
    monkeypatch.setattr(moodle.MoodleClient, "execute_login", Mock(side_effect=exc("сбой") if error != "MoodleGroupError" else exc()))
    response = _login(product)
    assert response.status_code >= 400
    assert [(e.name, e.user_id) for e in _stored()] == [(name, None)]


def test_broken_event_write_does_not_break_login(product, test_groups, moodle, monkeypatch):
    from app.services import product_events

    monkeypatch.setattr(product_events, "_event", Mock(side_effect=RuntimeError("БД упала")))
    response = _login(product)
    assert response.status_code == 200 and response.json()["access_token"]
    assert _stored() == []


# --- метрики ---


def test_active_users_and_local_day(product):
    a, b, c = _student("А"), _student("Б"), _student("В")
    _events(
        ("app_open", NOW, a, "d1", "web"),
        ("app_open", NOW - timedelta(hours=1), a, "d1", "web"),
        ("login_success", NOW - timedelta(days=3), b, "d2", "pwa"),
        ("app_open", NOW - timedelta(days=20), c, "d3", "apk"),
        ("app_open", NOW - timedelta(days=40), c, "d3", "apk"),
        ("landing_view", NOW, None, "d9", "web"),  # гость: не активный пользователь
    )
    data = product_stats.summary(SessionLocal(), 30, now=NOW)
    assert (data["dau"], data["wau"], data["mau"]) == (1, 2, 3)
    assert data["users_total"] == 3
    assert data["by_platform"] == {"web": 1, "pwa": 1, "apk": 1}
    assert data["daily"][-1]["dau"] == 1 and len(data["daily"]) == 30


def test_late_utc_evening_is_next_local_day(product):
    user = _student("Ночной")
    late = datetime(2026, 11, 18, 23, 30, tzinfo=timezone.utc)  # 19.11 04:30 по Челябинску
    _events(("app_open", late, user, "d1", None))
    data = product_stats.summary(SessionLocal(), 1, now=NOW)
    assert data["dau"] == 1
    assert data["start_date"].isoformat() == "2026-11-19"


def test_funnel_counts_unique_devices(product):
    user = _student("Воронкин")
    _events(
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
    data = product_stats.summary(SessionLocal(), 7, now=NOW)
    assert data["funnel"] == {"landing_view": 2, "login_click": 1, "login_submit": 1, "login_success": 1}
    assert data["login_failures"] == {"auth": 1, "group": 0, "other": 0}


def test_apk_downloads_and_installs(product):
    _events(
        ("apk_download", NOW, None, "d1", "web"),
        ("apk_download", NOW, None, "d2", "web"),
        ("app_open", NOW - timedelta(days=60), None, "old", "apk"),
        ("app_open", NOW - timedelta(days=1), None, "a1", "apk"),
        ("app_open", NOW, None, "a1", "apk"),
        ("landing_view", NOW, None, "a2", "apk"),
        ("app_open", NOW, None, "w1", "web"),
    )
    data = product_stats.summary(SessionLocal(), 7, now=NOW)
    assert (data["apk_downloads"], data["apk_installs"], data["apk_installs_total"]) == (2, 2, 3)


def test_summary_rejects_unknown_period(product, product_headers):
    assert product.get("/api/v1/product/summary?days=5", headers=product_headers).status_code == 422


def test_users_list_and_events(product, product_headers, test_groups):
    group_id = test_groups["ТЕСТ ПИ 991"]
    old = _student("Старов Олег", group_id, created_at=NOW - timedelta(days=50))
    fresh = _student("Новикова Анна", created_at=NOW - timedelta(days=1))
    recent = datetime.now(timezone.utc) - timedelta(hours=2)
    _events(
        ("login_success", recent - timedelta(hours=1), old, "d1", "web"),
        ("app_open", recent, old, "d1", "apk"),
    )

    response = product.get("/api/v1/product/users", headers=product_headers)
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    first = body["items"][0]
    assert first["id"] == old
    assert first["group"] == {"name": "ТЕСТ ПИ 991", "course": 1}
    assert first["last_platform"] == "apk" and first["active_days_30"] >= 1

    by_created = product.get("/api/v1/product/users?sort=created", headers=product_headers).json()
    assert [item["id"] for item in by_created["items"]] == [fresh, old]
    found = product.get("/api/v1/product/users", params={"q": "Новикова"}, headers=product_headers).json()
    assert [item["id"] for item in found["items"]] == [fresh]
    in_group = product.get(f"/api/v1/product/users?group_id={group_id}", headers=product_headers).json()
    assert in_group["total"] == 1

    page = product.get(f"/api/v1/product/users/{old}/events?limit=1", headers=product_headers).json()
    assert [e["name"] for e in page["items"]] == ["app_open"]
    assert page["next_before"] is not None
    rest = product.get(
        f"/api/v1/product/users/{old}/events?limit=1&before={page['next_before']}", headers=product_headers
    ).json()
    assert [e["name"] for e in rest["items"]] == ["login_success"]
    assert rest["next_before"] is None

    assert product.get("/api/v1/product/users/999999/events", headers=product_headers).status_code == 404
