import asyncio
import re
from datetime import datetime, timedelta, timezone

import jwt
import pytest

from app.core.config import Settings, get_settings
from app.main import app
from tests.moodle_helpers import login_student


async def test_body_limit_also_applies_without_content_length(bare_client):
    async def chunks():
        yield b" " * (40 * 1024)
        yield b" " * (40 * 1024)

    response = await bare_client.post(
        "/api/v1/feedback", content=chunks(), headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 413


async def test_import_rejects_guest_before_reading_upload(bare_client):
    async def body():
        assert False, "Импорт не должен читать тело гостевого запроса"
        yield b""

    response = await bare_client.post("/api/v1/admin/imports/weekly", content=body(), headers={
        "Content-Type": "multipart/form-data; boundary=synthetic",
    })
    assert response.status_code == 401


async def test_login_validation_does_not_echo_secret(bare_client):
    password = "synthetic-value-" * 25
    response = await bare_client.post("/api/v1/auth/moodle/login", json={"username": "synthetic", "password": password})
    assert response.status_code == 422
    assert password not in response.text
    assert response.headers["cache-control"] == "no-store"


async def test_login_quota_is_shared_by_concurrent_requests(bare_client, monkeypatch):
    monkeypatch.setattr(get_settings(), "login_pair_limit", 2)

    async def submit():
        return await bare_client.post(
            "/api/v1/auth/admin/login", json={"login": "synthetic-audit-login", "password": "synthetic"},
        )

    responses = await asyncio.gather(submit(), submit(), submit())
    assert sorted(response.status_code for response in responses) == [401, 401, 429]
    assert int(next(response for response in responses if response.status_code == 429).headers["retry-after"]) > 0


@pytest.mark.parametrize("path", ["/docs", "/redoc", "/openapi.json", "/docs/oauth2-redirect"])
async def test_api_documentation_disabled_by_default(bare_client, path):
    assert (await bare_client.get(path)).status_code == 404


async def test_protected_route_families_reject_missing_and_student_roles(bare_client, test_groups):
    login = await login_student(bare_client, test_groups["ТЕСТ ПИ 991"], "Тест аудита", "device-audit-access")
    assert login.status_code == 200
    student = {"Authorization": f"Bearer {login.json()['access_token']}"}
    paths = app.openapi()["paths"]
    families = ("/api/v1/admin/", "/api/v1/product/")
    for template, methods in paths.items():
        if not template.startswith(families):
            continue
        path = re.sub(r"\{\w+\}", "1", template)
        for method in methods:
            guest = await bare_client.request(method, path)
            assert guest.status_code == 401, (method, path, guest.status_code)
            response = await bare_client.request(method, path, headers=student)
            assert response.status_code == 403, (method, path, response.status_code)


@pytest.mark.parametrize("valid_signature", [False, True])
async def test_admin_api_rejects_invalid_signature_or_expired_jwt(bare_client, valid_signature):
    key = get_settings().jwt_secret if valid_signature else "independent-synthetic-test-key-0123456789"
    ttl = timedelta(hours=-1 if valid_signature else 1)
    token = jwt.encode({
        "sub": get_settings().admin_login, "role": "admin", "exp": datetime.now(timezone.utc) + ttl,
    }, key, algorithm="HS256")
    response = await bare_client.get("/api/v1/admin/feedback", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401


def test_default_and_weak_jwt_keys_are_rejected(monkeypatch):
    monkeypatch.delenv("JWT_SECRET", raising=False)
    with pytest.raises(ValueError, match="jwt_secret"):
        Settings()
    with pytest.raises(ValueError, match="JWT_SECRET") as caught:
        Settings(jwt_secret="synthetic-placeholder")
    assert "synthetic-placeholder" not in str(caught.value)
    assert len(get_settings().jwt_secret.encode()) >= 32
