"""Обращения подписываются ФИО и группой из профиля Moodle; старые — по устройству."""

import pytest
from sqlalchemy import delete, select

from app.core.db import SessionLocal
from app.models import EmailOutbox, FeedbackMessage
from app.services.feedback import fill_authors_from_devices, secret_hash
from tests.moodle_helpers import login_student

TEXT = {"kind": "methodist", "text": "Когда будет пересдача?"}


@pytest.fixture(autouse=True)
async def _clean(db_schema):
    yield
    async with SessionLocal() as session:
        await session.execute(delete(EmailOutbox))
        await session.execute(delete(FeedbackMessage))
        await session.commit()


async def _student(client, group_id: int, name: str, device: str) -> dict[str, str]:
    response = await login_student(client, group_id, name, device)
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


async def _stored() -> list[FeedbackMessage]:
    async with SessionLocal() as session:
        return list(await session.scalars(select(FeedbackMessage).order_by(FeedbackMessage.id)))


async def test_signed_in_student_is_signed_from_profile(bare_client, test_groups):
    own, other = test_groups["ТЕСТ ПИ 991"], test_groups["ТЕСТ БИ 991"]
    headers = await _student(bare_client, own, "Андреева Аня", "device-author-0001")
    response = await bare_client.post(
        "/api/v1/feedback",
        json={**TEXT, "author_name": "Кто-то другой", "group_id": other, "contact": "anya@example.com"},
        headers={**headers, "X-Feedback-Token": "device-author-0001"},
    )
    assert response.status_code == 201, response.text
    [message] = await _stored()
    assert (message.author_name, message.group_id, message.contact) == ("Андреева Аня", own, "anya@example.com")


@pytest.mark.parametrize("headers", [
    {},
    {"X-Feedback-Token": "guest-device-0001"},
    {"Authorization": "Bearer invalid", "X-Feedback-Token": "guest-device-0001"},
])
async def test_feedback_requires_moodle_session(bare_client, headers):
    response = await bare_client.post(
        "/api/v1/feedback", json={**TEXT, "author_name": "Гость"}, headers=headers,
    )
    assert response.status_code == 401
    assert await _stored() == []


async def test_revoked_moodle_session_cannot_send_feedback(bare_client, test_groups):
    headers = await _student(bare_client, test_groups["ТЕСТ ПИ 991"], "Андреева Аня", "device-author-0001")
    assert (await bare_client.post("/api/v1/auth/moodle/forget", headers=headers)).status_code == 200
    response = await bare_client.post("/api/v1/feedback", json=TEXT, headers=headers)
    assert response.status_code == 401
    assert await _stored() == []


async def test_old_feedback_signed_by_device(bare_client, test_groups):
    group = test_groups["ТЕСТ ПИ 991"]
    # До входа через Moodle: обращения без имени и с именем, с разных устройств.
    async with SessionLocal() as session:
        for token, author_name in (
            ("device-old-00001", None),
            ("device-old-00001", "Подписался сам"),
            ("device-old-00002", None),
            ("device-nobody-001", None),
        ):
            session.add(FeedbackMessage(**TEXT, author_token_hash=secret_hash(token), author_name=author_name))
        await session.commit()
    await _student(bare_client, group, "Борисов Борис", "device-old-00001")
    # Два профиля с одним устройством — неоднозначно, не подписываем.
    await _student(bare_client, group, "Волкова Вера", "device-old-00002")
    await login_student(bare_client, group, "Громов Глеб", "device-old-00002", username="gleb-second-profile")

    first, signed, ambiguous, nobody = await _stored()
    async with SessionLocal() as session:
        preview = await fill_authors_from_devices(session, apply=False)
    assert preview == [(first.id, "Борисов Борис")]
    assert (await _stored())[0].author_name is None  # без --apply ничего не меняется

    async with SessionLocal() as session:
        await fill_authors_from_devices(session, apply=True)
    after = await _stored()
    assert [m.author_name for m in after] == ["Борисов Борис", "Подписался сам", None, None]
    assert after[0].group_id == group
