from unittest.mock import Mock

import pytest

from app.core.crypto import decrypt_secret, encrypt_secret
from app.models import Group
from app.services.moodle import match_student_group


def test_mock_prefix_requires_real_login_when_mock_disabled(bare_client, test_groups, monkeypatch):
    from app.core.config import get_settings
    from app.services.moodle import MoodleAuthError, MoodleClient

    monkeypatch.setattr(get_settings(), "moodle_mock", False)
    login = Mock(side_effect=MoodleAuthError())
    monkeypatch.setattr(MoodleClient, "execute_login", login)

    response = bare_client.post(
        "/api/v1/auth/moodle/login",
        json={"username": "mock_intruder", "password": "arbitrary"},
    )

    assert response.status_code == 401
    assert "access_token" not in response.json()
    login.assert_called_once_with("mock_intruder", "arbitrary")


@pytest.mark.parametrize("source", ["url", "link", "missing"])
def test_profile_requires_moodle_id(monkeypatch, source):
    from app.services.moodle import MoodleClient, MoodleError

    response = Mock()
    response.url = "https://eu.iit.csu.ru/user/profile.php"
    response.text = '<div class="card-profile"><h3>Иван Иванов</h3></div>'
    if source == "url":
        response.url += "?id=123"
    elif source == "link":
        response.text += '<a href="/user/profile.php?id=123">Профиль</a>'

    client = MoodleClient()
    monkeypatch.setattr(client.session, "get", Mock(return_value=response))
    if source == "missing":
        with pytest.raises(MoodleError, match="идентификатор") as error:
            client.get_profile_info()
        assert error.value.status_code == 502
    else:
        full_name, moodle_id, _, _ = client.get_profile_info()
        assert full_name == "Иван Иванов"
        assert moodle_id == "123"


def test_login_without_moodle_id_does_not_issue_token(bare_client, monkeypatch):
    from app.core.config import get_settings
    from app.services.moodle import MoodleClient

    monkeypatch.setattr(get_settings(), "moodle_mock", False)
    monkeypatch.setattr(MoodleClient, "execute_login", Mock(return_value=("", "key")))
    response = Mock(
        url="https://eu.iit.csu.ru/user/profile.php",
        text='<div class="card-profile"><h3>Иван Иванов</h3></div>',
    )
    monkeypatch.setattr("requests.Session.get", Mock(return_value=response))

    result = bare_client.post(
        "/api/v1/auth/moodle/login",
        json={"username": "student_without_id", "password": "password"},
    )

    assert result.status_code == 502
    assert "идентификатор" in result.json()["detail"]
    assert "access_token" not in result.json()


@pytest.mark.parametrize("invalid_id", ["", "unknown"])
def test_invalid_moodle_id_cannot_overwrite_existing_account(invalid_id):
    from datetime import datetime, timezone
    from sqlalchemy import create_engine, select
    from sqlalchemy.orm import Session

    from app.models import Base, User
    from app.services.moodle import MoodleError, MoodleSessionData, save_or_update_student

    engine = create_engine("sqlite+pysqlite:///:memory:")
    try:
        Base.metadata.create_all(engine)
        with Session(engine) as db:
            group = Group(name="ПрИ-401", course=4, direction="ПрИ")
            victim = User(full_name="Первый студент", moodle_id=invalid_id, moodle_username="first", group=group)
            db.add(victim)
            db.commit()
            victim_id = victim.id
            data = MoodleSessionData(
                moodle_id=invalid_id, moodle_username="second", full_name="Второй студент",
                group=group, cookies={}, sesskey="key", expires_at=datetime.now(timezone.utc),
            )

            with pytest.raises(MoodleError, match="идентификатор"):
                save_or_update_student(db, data, "password", None, None)

            db.expire_all()
            stored = db.get(User, victim_id)
            assert stored.full_name == "Первый студент"
            assert stored.moodle_username == "first"
            assert list(db.scalars(select(User.id))) == [victim_id]
    finally:
        engine.dispose()


def test_crypto_roundtrip():
    secret = "SuperSecretPassword123!@#"
    encrypted = encrypt_secret(secret)
    assert encrypted != secret
    assert decrypt_secret(encrypted) == secret


def test_crypto_invalid_payload():
    with pytest.raises(ValueError):
        decrypt_secret("invalid-base64-payload")


def test_match_student_group():
    g1 = Group(id=1, name="ИТ1-ПрИб-11")
    g2 = Group(id=2, name="КБ-301")
    g3 = Group(id=3, name="ИТ2-ПИб-21")
    groups = [g1, g2, g3]

    # Совпадение по точному названию в названии курса
    courses1 = [{"fullname": "Веб-разработка (группа ИТ1-ПрИб-11)", "shortname": "WEB-1"}]
    assert match_student_group(courses1, "", groups) == g1

    # Совпадение по короткому имени группы
    courses2 = [{"fullname": "Криптографические методы защиты (КБ-301)", "shortname": "CRYPTO"}]
    assert match_student_group(courses2, "", groups) == g2

    # Совпадение по фрагменту без разделителей
    courses3 = [{"fullname": "Базы данных (ит2 пиб 21)", "shortname": "DB"}]
    assert match_student_group(courses3, "", groups) == g3

    # Нет совпадения
    courses4 = [{"fullname": "Общеуниверситетский факультатив", "shortname": "OPT"}]
    assert match_student_group(courses4, "", groups) is None


def test_match_student_group_multiyear_and_stream():
    g_pri401 = Group(id=10, name="ПрИ-401", course=4, direction="ПрИ")
    g_pi401 = Group(id=11, name="ПИ-401", course=4, direction="ПИ")
    g_pri101 = Group(id=12, name="ИТ1-ПрИб-11", course=1, direction="ПрИ")
    groups = [g_pri401, g_pi401, g_pri101]

    # Студент 4 курса: есть старые курсы 1 курса и новые 4 курса (2026-2027)
    courses = [
        {"fullname": "Иностранный язык (ПрИ-101) (1-2 сем.) 2023-2024", "shortname": "ENG"},
        {"fullname": "Физика (ПрИ-101, ПИ-101) (1 сем.) 2023-2024", "shortname": "PHYS"},
        {"fullname": "Деловые коммуникации (ПИ-4, ПрИ-4) (1 сем.) 2026-2027", "shortname": "COMM"},
        {"fullname": "Защита информации (ПрИ-4) (1 сем.) 2026-2027", "shortname": "SEC"},
        {"fullname": "Программирование микроконтроллеров (ПрИ-4) (1 сем.) 2026-2027", "shortname": "MCU"},
    ]

    # Должен определить группу ПрИ-401 (текущий год 2026-2027 и исключительное направление ПрИ-4)
    matched = match_student_group(courses, "", groups)
    assert matched == g_pri401


def test_match_student_group_long_name_alias():
    # База содержит группу в формате "ИТ4-ПрИб-41"
    g_long = Group(id=20, name="ИТ4-ПрИб-41", course=4, direction="ПрИ")
    courses = [
        {"fullname": "Защита информации (ПрИ-4) (1 сем.) 2026-2027", "shortname": "SEC"},
    ]
    matched = match_student_group(courses, "", [g_long])
    assert matched == g_long


def test_moodle_mock_login(bare_client, monkeypatch):
    from app.core.db import SessionLocal

    # Создаём группу в тестовой базе (с реальным Excel она уже может быть)
    from sqlalchemy import select

    with SessionLocal() as db:
        if db.scalar(select(Group).where(Group.name == "ИТ1-ПрИб-11")) is None:
            db.add(Group(name="ИТ1-ПрИб-11", course=1, direction="ПрИ"))
            db.commit()

    # Включаем MOODLE_MOCK
    from app.core.config import get_settings
    monkeypatch.setattr(get_settings(), "moodle_mock", True)

    resp = bare_client.post(
        "/api/v1/auth/moodle/login",
        # Группа в логине: с реальным Excel групп много, без неё mock берёт первую.
        json={"username": "ivanov_ит1-приб-11", "password": "any-password", "device_key": "device-key-mock-123456789"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert "access_token" in data
    assert data["profile"]["full_name"] == "Студент Ivanov_ит1-приб-11"
    assert data["profile"]["group_name"] == "ИТ1-ПрИб-11"
    assert data["profile"]["moodle_username"] == "ivanov_ит1-приб-11"

    # Проверяем эндпоинт /me
    token = data["access_token"]
    me_resp = bare_client.get("/api/v1/me", headers={"Authorization": f"Bearer {token}"})
    assert me_resp.status_code == 200
    me_data = me_resp.json()
    assert me_data["moodle_username"] == "ivanov_ит1-приб-11"

    # Проверяем forget
    forget_resp = bare_client.post("/api/v1/auth/moodle/forget", headers={"Authorization": f"Bearer {token}"})
    assert forget_resp.status_code == 200
    assert forget_resp.json() == {"status": "ok"}


def test_extract_group_from_profile_html():
    from app.services.moodle import extract_group_from_profile_html

    profile_html = """
    <div class="userprofile">
      <section class="node_category card mb-3">
        <div class="card-body">
          <ul class="list-unstyled">
            <li class="contentnode">
              <dt>Учебная группа</dt>
              <dd>ПрИ-401</dd>
            </li>
          </ul>
        </div>
      </section>
    </div>
    """
    assert extract_group_from_profile_html(profile_html) == "ПрИ-401"

    # Проверка работы match_student_group напрямую из HTML профиля
    g = Group(id=50, name="ПрИ-401", course=4, direction="ПрИ")
    assert match_student_group([], profile_html, [g]) == g
