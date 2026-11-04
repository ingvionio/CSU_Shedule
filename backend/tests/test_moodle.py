import pytest
from app.core.crypto import decrypt_secret, encrypt_secret
from app.models import Group
from app.services.moodle import match_student_group


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

    # Создаём группу в тестовой базе
    with SessionLocal() as db:
        group = Group(name="ИТ1-ПрИб-11", course=1, direction="ПрИ")
        db.add(group)
        db.commit()

    # Включаем MOODLE_MOCK
    from app.core.config import get_settings
    monkeypatch.setattr(get_settings(), "moodle_mock", True)

    resp = bare_client.post(
        "/api/v1/auth/moodle/login",
        json={"username": "ivanov_ii", "password": "any-password", "device_key": "device-key-mock-123456789"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert "access_token" in data
    assert data["profile"]["full_name"] == "Студент Ivanov_ii"
    assert data["profile"]["group_name"] == "ИТ1-ПрИб-11"
    assert data["profile"]["moodle_username"] == "ivanov_ii"

    # Проверяем эндпоинт /me
    token = data["access_token"]
    me_resp = bare_client.get("/api/v1/me", headers={"Authorization": f"Bearer {token}"})
    assert me_resp.status_code == 200
    me_data = me_resp.json()
    assert me_data["moodle_username"] == "ivanov_ii"

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
