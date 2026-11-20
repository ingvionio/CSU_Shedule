from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

import jwt
import pytest
import requests
from pydantic import ValidationError
from sqlalchemy import select

from app.core.config import Settings, get_settings
from app.core.crypto import decrypt_secret, encrypt_secret
from app.core.db import SessionLocal
from app.core.security import issue_token
from app.models import User
from app.services import moodle, moodle_sessions
from app.services.moodle_sessions import start_worker as real_start_worker

API = "/api/v1"


@pytest.fixture
def login(bare_client, test_groups, monkeypatch):
    monkeypatch.setattr(get_settings(), "moodle_mock", True)

    def perform(username="session-owner", device="session-device-0001"):
        response = bare_client.post(f"{API}/auth/moodle/login", json={
            "username": username, "password": "never-store-this-password", "device_key": device,
        })
        assert response.status_code == 200, response.text
        body = response.json()
        return body, {"Authorization": f"Bearer {body['access_token']}"}

    return perform


def test_only_ciphertext_is_stored_and_bound_to_user(login):
    body, _ = login()
    with SessionLocal() as db:
        user = db.get(User, body["profile"]["id"])
        assert not hasattr(user, "moodle_encrypted_password")
        assert "mock_cookie_val" not in user.moodle_encrypted_cookies
        assert "mock_sesskey_123" not in user.moodle_encrypted_sesskey
        assert decrypt_secret(user.moodle_encrypted_sesskey, f"user:{user.id}:sesskey") == "mock_sesskey_123"
        with pytest.raises(ValueError):
            decrypt_secret(user.moodle_encrypted_sesskey, f"user:{user.id + 1}:sesskey")
        with pytest.raises(ValueError):
            decrypt_secret(user.moodle_encrypted_sesskey, f"user:{user.id}:cookies")


@pytest.mark.parametrize("key", ["", "not-base64", "YWJj", "a" * 44])
def test_key_is_required_and_strict(key):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, moodle_encryption_key=key)


def test_missing_key_prevents_startup(monkeypatch):
    monkeypatch.delenv("MOODLE_ENCRYPTION_KEY")
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_startup_errors_do_not_disclose_invalid_key():
    key = "invalid-secret-key-do-not-print"
    with pytest.raises(ValidationError) as error:
        Settings(_env_file=None, moodle_encryption_key=key)
    assert key not in str(error.value)


def test_ciphertexts_are_random_and_authenticated():
    first = encrypt_secret("cookie", "context")
    assert first != encrypt_secret("cookie", "context")
    with pytest.raises(ValueError):
        decrypt_secret(first, "other-context")


def test_old_tokens_and_registration_are_rejected(bare_client, login):
    body, _ = login()
    old, _ = issue_token(str(body["profile"]["id"]), "student", 1440)
    headers = {"Authorization": f"Bearer {old}"}
    assert bare_client.get(f"{API}/me", headers=headers).status_code == 401
    assert bare_client.post(f"{API}/auth/student/refresh", headers=headers, json={"active": True}).status_code == 401
    response = bare_client.post(f"{API}/auth/student/register", json={
        "full_name": "Чужой пользователь", "group_id": 1, "device_key": "untrusted-device-0001",
    })
    assert response.status_code == 410
    assert "access_token" not in response.json()


def test_devices_share_session_and_logout_revokes_all(bare_client, login):
    first, first_headers = login()
    second, second_headers = login(device="session-device-0002")
    assert first["profile"]["id"] == second["profile"]["id"]
    for headers in [first_headers, second_headers]:
        assert bare_client.get(f"{API}/me", headers=headers).status_code == 200
    assert bare_client.post(f"{API}/auth/moodle/forget", headers=first_headers).status_code == 200
    for headers in [first_headers, second_headers]:
        assert bare_client.get(f"{API}/me", headers=headers).status_code == 401
    with SessionLocal() as db:
        user = db.get(User, first["profile"]["id"])
        assert user.moodle_session_id is None
        assert user.moodle_encrypted_cookies is None
        assert user.moodle_encrypted_sesskey is None
        assert user.full_name == first["profile"]["full_name"]


def test_foreground_refresh_extends_activity_but_background_does_not(bare_client, login):
    body, headers = login()
    previous = datetime.now(timezone.utc) - timedelta(days=4)
    with SessionLocal() as db:
        db.get(User, body["profile"]["id"]).session_last_active_at = previous
        db.commit()
    assert bare_client.get(f"{API}/me", headers=headers).status_code == 200
    assert bare_client.post(f"{API}/auth/student/refresh", headers=headers, json={"active": False}).status_code == 200
    with SessionLocal() as db:
        assert moodle_sessions.as_utc(db.get(User, body["profile"]["id"]).session_last_active_at) == previous
    assert bare_client.post(f"{API}/auth/student/refresh", headers=headers, json={"active": True}).status_code == 200
    with SessionLocal() as db:
        assert moodle_sessions.as_utc(db.get(User, body["profile"]["id"]).session_last_active_at) > previous


def test_expired_access_token_can_refresh_only_while_shared_session_is_active(bare_client, login):
    body, _ = login()
    payload = jwt.decode(body["access_token"], get_settings().jwt_secret, algorithms=["HS256"])
    payload["exp"] = int((datetime.now(timezone.utc) - timedelta(hours=1)).timestamp())
    token = jwt.encode(payload, get_settings().jwt_secret, algorithm="HS256")
    headers = {"Authorization": f"Bearer {token}"}
    assert bare_client.get(f"{API}/me", headers=headers).status_code == 401
    assert bare_client.post(f"{API}/auth/student/refresh", headers=headers, json={"active": False}).status_code == 200
    with SessionLocal() as db:
        db.get(User, body["profile"]["id"]).session_last_active_at = datetime.now(timezone.utc) - timedelta(days=5)
        db.commit()
    assert bare_client.post(f"{API}/auth/student/refresh", headers=headers, json={"active": True}).status_code == 401


def test_expiry_cannot_be_revived_by_activity(bare_client, login):
    body, headers = login()
    with SessionLocal() as db:
        db.get(User, body["profile"]["id"]).session_last_active_at = datetime.now(timezone.utc) - timedelta(days=5)
        db.commit()
    assert bare_client.get(f"{API}/me", headers=headers).status_code == 401
    assert bare_client.post(f"{API}/auth/student/refresh", headers=headers, json={"active": True}).status_code == 401


def test_cleanup_preserves_profile_and_never_touches_expired_moodle(login, monkeypatch):
    body, _ = login()
    now = datetime.now(timezone.utc)
    touch = Mock()
    monkeypatch.setattr(moodle.MoodleClient, "touch_session", touch)
    with SessionLocal() as db:
        user = db.get(User, body["profile"]["id"])
        user.session_last_active_at = now - timedelta(days=5)
        db.commit()
    moodle_sessions.maintain_sessions(now=now)
    touch.assert_not_called()
    with SessionLocal() as db:
        user = db.get(User, body["profile"]["id"])
        assert user is not None
        assert user.moodle_encrypted_cookies is None
        assert user.moodle_encrypted_sesskey is None
        assert user.moodle_session_id is None


@pytest.mark.parametrize("outcome", ["ok", "network", "auth", "invalid-response"])
def test_worker_refresh_and_error_classification(login, monkeypatch, bare_client, outcome):
    body, headers = login()
    now = datetime.now(timezone.utc)
    with SessionLocal() as db:
        user = db.get(User, body["profile"]["id"])
        user.moodle_refresh_at = now - timedelta(seconds=1)
        active_at = moodle_sessions.as_utc(user.session_last_active_at)
        db.commit()
    monkeypatch.setattr(get_settings(), "moodle_mock", False)
    errors = {
        "network": moodle.MoodleError("Нет связи", 502),
        "auth": moodle.MoodleAuthError("Сессия истекла"),
        "invalid-response": moodle.MoodleError("Некорректный ответ", 502),
    }
    touch = Mock(return_value=600, side_effect=errors.get(outcome))
    monkeypatch.setattr(moodle.MoodleClient, "touch_session", touch)
    moodle_sessions.maintain_sessions(now=now)
    touch.assert_called_once_with("mock_sesskey_123")
    with SessionLocal() as db:
        user = db.get(User, body["profile"]["id"])
        if outcome == "auth":
            assert user.moodle_session_id is None
            assert user.moodle_encrypted_cookies is None
        else:
            assert moodle_sessions.as_utc(user.session_last_active_at) == active_at
            assert moodle_sessions.as_utc(user.moodle_refresh_at) > now
            assert user.moodle_session_id is not None
            if outcome == "ok":
                assert user.moodle_timeout_seconds == 600
                assert moodle_sessions.as_utc(user.moodle_refresh_at) <= now + timedelta(seconds=300)
    assert bare_client.get(f"{API}/me", headers=headers).status_code == (401 if outcome == "auth" else 200)


def test_late_worker_cannot_restore_logged_out_session(login, monkeypatch):
    body, _ = login()
    now = datetime.now(timezone.utc)
    with SessionLocal() as db:
        db.get(User, body["profile"]["id"]).moodle_refresh_at = now - timedelta(seconds=1)
        db.commit()

    def touch(*_):
        with SessionLocal() as db:
            moodle_sessions.revoke_session(db, body["profile"]["id"])
        return 600

    monkeypatch.setattr(get_settings(), "moodle_mock", False)
    monkeypatch.setattr(moodle.MoodleClient, "touch_session", touch)
    moodle_sessions.maintain_sessions(now=now)
    with SessionLocal() as db:
        assert db.get(User, body["profile"]["id"]).moodle_session_id is None


@pytest.mark.parametrize("errorcode", ["servicerequireslogin", "requireloginerror", "invalidsesskey"])
def test_touch_reports_auth_errors(errorcode, monkeypatch):
    client = moodle.MoodleClient()
    response = Mock(status_code=200)
    response.json.return_value = [{"error": True, "exception": {"errorcode": errorcode}}]
    monkeypatch.setattr(client.session, "post", Mock(return_value=response))
    with pytest.raises(moodle.MoodleAuthError):
        client.touch_session("key")


def test_touch_batches_keepalive_and_remaining_time(monkeypatch):
    client = moodle.MoodleClient()
    response = Mock(status_code=200)
    response.json.return_value = [
        {"error": False, "data": True},
        {"error": False, "data": {"userid": 123, "timeremaining": 7200}},
    ]
    post = Mock(return_value=response)
    monkeypatch.setattr(client.session, "post", post)
    assert client.touch_session("key") == 7200
    methods = [item["methodname"] for item in post.call_args.kwargs["json"]]
    assert methods == ["core_session_touch", "core_session_time_remaining"]


def test_touch_does_not_turn_network_error_into_logout(monkeypatch):
    client = moodle.MoodleClient()
    monkeypatch.setattr(client.session, "post", Mock(side_effect=requests.Timeout()))
    with pytest.raises(moodle.MoodleError) as exc:
        client.touch_session("key")
    assert exc.value.status_code == 502


def test_worker_starts_and_stops_without_network(monkeypatch):
    from threading import Event

    called = Event()
    monkeypatch.setattr(moodle_sessions, "maintain_sessions", lambda **_: called.set())
    stop, thread = real_start_worker()
    try:
        assert called.wait(2)
    finally:
        stop.set()
        thread.join(2)
    assert not thread.is_alive()


def test_application_lifespan_stops_worker(db_schema, monkeypatch):
    from threading import Event
    from fastapi.testclient import TestClient
    from app.main import app

    stop, thread = Event(), Mock()
    start = Mock(return_value=(stop, thread))
    monkeypatch.setattr(moodle_sessions, "start_worker", start)
    with TestClient(app) as client:
        assert client.get("/health").status_code == 200
        start.assert_called_once()
    assert stop.is_set()
    thread.join.assert_called_once_with(15)


def test_expired_token_can_log_out_active_shared_session(bare_client, login):
    first, _ = login()
    _, second_headers = login(device="other-device-0001")
    payload = jwt.decode(first["access_token"], get_settings().jwt_secret, algorithms=["HS256"])
    payload["exp"] = 1
    expired = jwt.encode(payload, get_settings().jwt_secret, algorithm="HS256")
    result = bare_client.post(f"{API}/auth/moodle/forget", headers={"Authorization": f"Bearer {expired}"})
    assert result.status_code == 200
    assert bare_client.get(f"{API}/me", headers=second_headers).status_code == 401


def test_old_session_is_not_revived_after_login(bare_client, login):
    body, old_headers = login()
    with SessionLocal() as db:
        db.get(User, body["profile"]["id"]).session_last_active_at = datetime.now(timezone.utc) - timedelta(days=5)
        db.commit()
    _, new_headers = login()
    assert bare_client.get(f"{API}/me", headers=new_headers).status_code == 200
    assert bare_client.get(f"{API}/me", headers=old_headers).status_code == 401
    assert bare_client.post(f"{API}/auth/student/refresh", headers=old_headers, json={"active": True}).status_code == 401


def test_worker_lease_prevents_duplicate_network_calls(login, monkeypatch):
    body, _ = login()
    now = datetime.now(timezone.utc)
    user_id = body["profile"]["id"]
    with SessionLocal() as db:
        db.get(User, user_id).moodle_refresh_at = now - timedelta(seconds=1)
        db.commit()

    def touch(*_):
        moodle_sessions._refresh_one(user_id, now)
        return 600

    monkeypatch.setattr(get_settings(), "moodle_mock", False)
    callback = Mock(side_effect=touch)
    monkeypatch.setattr(moodle.MoodleClient, "touch_session", callback)
    moodle_sessions.maintain_sessions(now=now)
    callback.assert_called_once()


def test_stale_worker_cannot_overwrite_relogin(login, monkeypatch):
    body, _ = login()
    user_id = body["profile"]["id"]
    now = datetime.now(timezone.utc)
    with SessionLocal() as db:
        db.get(User, user_id).moodle_refresh_at = now - timedelta(seconds=1)
        db.commit()
    monkeypatch.setattr(get_settings(), "moodle_mock", False)
    newer_cookies = None

    def touch(*_):
        nonlocal newer_cookies
        monkeypatch.setattr(get_settings(), "moodle_mock", True)
        login()
        with SessionLocal() as db:
            newer_cookies = db.get(User, user_id).moodle_encrypted_cookies
        return 600

    monkeypatch.setattr(moodle.MoodleClient, "touch_session", touch)
    moodle_sessions.maintain_sessions(now=now)
    with SessionLocal() as db:
        assert db.get(User, user_id).moodle_encrypted_cookies == newer_cookies
        assert db.get(User, user_id).moodle_timeout_seconds == 7200


def test_key_change_revokes_unreadable_sessions_without_touch(login, monkeypatch, bare_client):
    from pydantic import SecretStr

    body, headers = login()
    now = datetime.now(timezone.utc)
    with SessionLocal() as db:
        db.get(User, body["profile"]["id"]).moodle_refresh_at = now - timedelta(seconds=1)
        db.commit()
    monkeypatch.setattr(get_settings(), "moodle_encryption_key", SecretStr("eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHg="))
    touch = Mock()
    monkeypatch.setattr(moodle.MoodleClient, "touch_session", touch)
    moodle_sessions.maintain_sessions(now=now)
    touch.assert_not_called()
    assert bare_client.get(f"{API}/me", headers=headers).status_code == 401


@pytest.mark.parametrize("status,payload,location", [
    (401, {}, ""),
    (200, {"errorcode": "servicerequireslogin"}, ""),
    (303, {}, "/login/index.php"),
])
def test_explicit_auth_failures_are_recognized(status, payload, location, monkeypatch):
    client = moodle.MoodleClient()
    response = Mock(status_code=status, headers={"Location": location})
    response.json.return_value = payload
    monkeypatch.setattr(client.session, "post", Mock(return_value=response))
    with pytest.raises(moodle.MoodleAuthError):
        client.touch_session("key")


def test_timeout_is_extracted_from_login_html():
    assert moodle.MoodleClient.session_timeout('<script>M.cfg = {"sessiontimeout": 7200}</script>') == 7200
    assert moodle.MoodleClient.session_timeout('<html>нет настройки</html>') is None
    assert moodle.MoodleClient.session_timeout('{"sessiontimeout":0}') is None
