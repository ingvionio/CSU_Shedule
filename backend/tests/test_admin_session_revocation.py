import asyncio
from datetime import datetime, timedelta, timezone

import jwt

from app.core.config import get_settings
from app.core.db import SessionLocal
from app.core.security import issue_token, revoke_admin_sessions


async def test_logout_revokes_only_current_admin_token(bare_client):
    async def login():
        response = await bare_client.post("/api/v1/auth/admin/login", json={"login": "admin", "password": "secret"})
        assert response.status_code == 200
        return {"Authorization": f"Bearer {response.json()['access_token']}"}

    first, second = await asyncio.gather(login(), login())
    assert first != second
    assert (await bare_client.post("/api/v1/auth/admin/logout", headers=first)).status_code == 204
    assert (await bare_client.get("/api/v1/admin/feedback", headers=first)).status_code == 401
    assert (await bare_client.post("/api/v1/admin/imports/weekly", headers=first)).status_code == 401
    assert (await bare_client.get("/api/v1/admin/feedback", headers=second)).status_code == 200


async def test_global_revocation_preserves_tokens_issued_after_cutoff(bare_client, monkeypatch):
    from app.core import security

    class Clock(datetime):
        offset = -2

        @classmethod
        def now(cls, tz=None):
            return datetime.fromtimestamp(datetime.now(timezone.utc).timestamp() + cls.offset, tz)

    monkeypatch.setattr(security, "datetime", Clock)
    old, _ = issue_token("admin", "admin", 1)
    legacy = jwt.encode({"sub": "admin", "role": "admin", "exp": datetime.now(timezone.utc) + timedelta(hours=1)},
                        get_settings().jwt_secret, algorithm="HS256")
    legacy_headers = {"Authorization": f"Bearer {legacy}"}
    assert (await bare_client.get("/api/v1/admin/feedback", headers=legacy_headers)).status_code == 200
    async with SessionLocal() as db:
        await revoke_admin_sessions(db)
    try:
        headers = {"Authorization": f"Bearer {old}"}
        assert (await bare_client.get("/api/v1/admin/feedback", headers=headers)).status_code == 401
        assert (await bare_client.get("/api/v1/admin/feedback", headers=legacy_headers)).status_code == 401
        Clock.offset = 0
        new, _ = issue_token("admin", "admin", 1)
        response = await bare_client.get("/api/v1/admin/feedback", headers={"Authorization": f"Bearer {new}"})
        assert response.status_code == 200
    finally:
        from app.models import AdminRevocation
        async with SessionLocal() as db:
            marker = await db.get(AdminRevocation, "all")
            await db.delete(marker)
            await db.commit()
