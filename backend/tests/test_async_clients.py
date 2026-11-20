import asyncio

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.db import get_db
from app.main import app
from app.models import Group
from tests import asgi_client


async def test_requests_have_independent_async_sessions(db_schema):
    async with app.router.lifespan_context(app):
        first = get_db()
        second = get_db()
        try:
            writer = await anext(first)
            reader = await anext(second)
            assert isinstance(writer, AsyncSession)
            assert isinstance(reader, AsyncSession)
            assert writer is not reader

            query = select(Group).where(Group.name == "Группа для проверки транзакции")
            writer.add(Group(name="Группа для проверки транзакции", course=1))
            await writer.flush()
            assert await writer.scalar(query) is not None
            assert await reader.scalar(query) is None
        finally:
            await first.aclose()
            await second.aclose()

        async with asgi_client(app) as client:
            response = await client.get("/api/v1/groups")
        assert response.status_code == 200
        assert all(group["name"] != "Группа для проверки транзакции" for group in response.json())


async def test_moodle_wait_does_not_block_api_and_client_is_closed(bare_client, test_groups, monkeypatch):
    started = asyncio.Event()
    release = asyncio.Event()
    clients = []
    async_client = httpx.AsyncClient
    monkeypatch.setattr(get_settings(), "moodle_mock", False)

    async def moodle(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/login/index.php" and request.method == "GET":
            started.set()
            await release.wait()
            return httpx.Response(200, text='<input name="logintoken" value="login-token">')
        if path == "/login/index.php":
            assert b"logintoken=login-token" in await request.aread()
            return httpx.Response(303, headers={"Location": "/my/", "Set-Cookie": "MoodleSession=value; Path=/"})
        assert "MoodleSession=value" in request.headers["cookie"]
        if path == "/my/":
            return httpx.Response(200, text='{"sesskey": "key"}')
        if path == "/user/profile.php" and "id" not in request.url.params:
            return httpx.Response(302, headers={"Location": "/user/profile.php?id=123456"})
        if path == "/user/profile.php":
            return httpx.Response(
                200, text='<div class="card-profile"><h3>Иван Иванов</h3></div><dl><dt>Группа</dt><dd>ТЕСТ ПИ 991</dd></dl>',
            )
        assert path == "/lib/ajax/service.php"
        return httpx.Response(200, json=[{"data": {"courses": []}}])

    def moodle_client(*args, **kwargs):
        client = async_client(*args, **kwargs, transport=httpx.MockTransport(moodle))
        clients.append(client)
        return client

    monkeypatch.setattr("app.services.moodle.httpx.AsyncClient", moodle_client)
    login = asyncio.create_task(
        bare_client.post("/api/v1/auth/moodle/login", json={"username": "student", "password": "example-password"})
    )
    try:
        await asyncio.wait_for(started.wait(), timeout=5)
        response = await asyncio.wait_for(bare_client.get("/api/v1/groups"), timeout=5)
        assert response.status_code == 200
        assert not login.done()
    finally:
        release.set()
        result = await login
    assert result.status_code == 200, result.text
    assert result.json()["profile"]["group_id"] == test_groups["ТЕСТ ПИ 991"]
    assert len(clients) == 1 and clients[0].is_closed
