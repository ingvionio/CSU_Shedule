"""Настоящий API-вход с подменой только внешней авторизации Moodle."""

from datetime import datetime, timedelta, timezone
import hashlib
from unittest.mock import patch

from app.models import Group
from app.services.moodle import MoodleError, MoodleSessionData


async def login_student(client, group_id, name="Иванов Иван", device="device-key-0123456789", *, username=None):
    username = username or hashlib.sha256(device.encode()).hexdigest()[:32]

    async def authenticate(db, **_):
        group = await db.get(Group, group_id)
        if group is None:
            raise MoodleError("группа не найдена", 404)
        return MoodleSessionData(
            moodle_id=username, moodle_username=username, full_name=" ".join(name.split()), group=group,
            cookies={"MoodleSession": "test-cookie"}, sesskey="test-sesskey",
            expires_at=datetime.now(timezone.utc) + timedelta(hours=2), timeout_seconds=7200,
        )

    with patch("app.services.moodle.authenticate_and_detect_student", side_effect=authenticate):
        return await client.post("/api/v1/auth/moodle/login", json={
            "username": username, "password": "test-password", "device_key": device,
        })
