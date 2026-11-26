"""Локальная проверка на пустой PostgreSQL БД csu_audit. Запуск: python -m tests.manual_security_postgres PORT."""

import asyncio
import base64
import os
import re
import secrets
import socket
import subprocess
import sys
from contextlib import ExitStack

import httpx
import psycopg


def local_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


async def check(clients: list[httpx.AsyncClient], dsn: str) -> None:
    for client in clients:
        for _ in range(120):
            try:
                if (await client.get("/health")).status_code == 200:
                    break
            except httpx.TransportError:
                pass
            await asyncio.sleep(.25)
        else:
            raise RuntimeError("Тестовый FastAPI не запустился")

    async def batch(path: str, bodies: list[dict], headers: dict | None = None) -> list[int]:
        responses = await asyncio.gather(*(clients[i % 2].post(path, json=body, headers=headers)
                                           for i, body in enumerate(bodies)))
        assert all(response.status_code != 429 or int(response.headers["retry-after"]) > 0 for response in responses)
        return sorted(response.status_code for response in responses)

    logins = await asyncio.gather(*(clients[i % 2].post("/api/v1/auth/moodle/login", json={
        "username": f"audit-student-{i}", "password": "synthetic",
    }) for i in range(3)))
    assert all(response.status_code == 200 for response in logins)
    student, other, third = [{"Authorization": "Bearer " + reply.json()["access_token"]} for reply in logins]
    repeated = {"kind": "methodist", "text": "Синтетическое обращение"}
    assert await batch("/api/v1/feedback", [repeated] * 6, student) == [201] + [429] * 5
    different = [{"kind": "methodist", "text": f"Запрос по расписанию {i}"} for i in range(6)]
    assert await batch("/api/v1/feedback", different, student) == [201] + [429] * 5
    assert await batch("/api/v1/feedback", different, other) == [201, 201] + [429] * 4
    assert await batch("/api/v1/feedback", [repeated], third) == [429]
    assert await batch("/api/v1/feedback", [repeated]) == [401]
    assert (await clients[1].get("/api/v1/feedback/mine", headers={"X-Feedback-Token": "legacy-device-token"})).status_code == 401
    assert len((await clients[1].get("/api/v1/feedback/mine", headers=student)).json()) == 2

    moodle = {"username": "audit-student-0", "password": "synthetic"}
    assert await batch("/api/v1/auth/moodle/login", [moodle] * 3) == [200, 429, 429]
    failed_login = {"login": "audit-wrong-user", "password": "synthetic"}
    assert await batch("/api/v1/auth/admin/login", [failed_login] * 6) == [401, 401] + [429] * 4
    assert await batch("/api/v1/auth/product/login", [failed_login] * 6) == [401, 401] + [429] * 4
    events = [{"device_key": f"audit-device-{i}", "events": [{"name": "landing_view"}]} for i in range(8)]
    assert await batch("/api/v1/events", events) == [204, 204, 204] + [429] * 5

    admin = await clients[0].post("/api/v1/auth/admin/login", json={"login": "admin", "password": os.environ["ADMIN_PASSWORD"]})
    assert admin.status_code == 200
    headers = {"Authorization": "Bearer " + admin.json()["access_token"]}
    page_url = "/api/v1/admin/feedback"
    page = await clients[0].get(page_url, params={"limit": 2}, headers=headers)
    assert page.status_code == 200 and len(page.json()) == 2
    remainder = await clients[1].get(page_url, params={"before_id": page.json()[-1]["id"]}, headers=headers)
    assert remainder.status_code == 200 and len(remainder.json()) == 2
    assert len({item["id"] for item in page.json() + remainder.json()}) == 4
    assert (await clients[0].post("/api/v1/auth/admin/logout", headers=headers)).status_code == 204
    assert (await clients[1].get("/api/v1/admin/feedback", headers=headers)).status_code == 401

    with psycopg.connect(dsn) as db:
        assert db.execute("select count(*) from feedback_messages").fetchone() == (4,)
        assert db.execute("select count(*), count(distinct message_id) from email_outbox").fetchone() == (4, 4)
        assert db.execute("select count(*) from product_events where name = 'landing_view'").fetchone() == (3,)
    print("PostgreSQL: 2 FastAPI процесса, 4 обращения и 4 письма без дублей, квоты входа и аналитики, межпроцессный отзыв")


def main() -> None:
    port = int(sys.argv[1])
    database = sys.argv[2] if len(sys.argv) > 2 else "csu_audit"
    if not re.fullmatch(r"csu_audit(?:_[0-9]+)?", database):
        raise ValueError("Нужна отдельная тестовая БД csu_audit")
    dsn = f"postgresql://postgres@127.0.0.1:{port}/{database}"
    with psycopg.connect(dsn) as db:
        assert db.execute("select count(*) from pg_tables where schemaname = 'public'").fetchone() == (0,)
    env = {
        "DATABASE_URL": dsn.replace("postgresql:", "postgresql+psycopg:"),
        "JWT_SECRET": secrets.token_urlsafe(48), "ADMIN_LOGIN": "admin", "ADMIN_PASSWORD": secrets.token_urlsafe(24),
        "MOODLE_ENCRYPTION_KEY": base64.b64encode(secrets.token_bytes(32)).decode(), "MOODLE_MOCK": "true",
        "FEEDBACK_RATE_LIMIT_PER_HOUR": "2", "FEEDBACK_IP_RATE_LIMIT_PER_HOUR": "4", "LOGIN_PAIR_LIMIT": "2",
        "PRODUCT_EVENTS_IP_LIMIT": "3", "SMTP_USER": "", "PRODUCT_PASSWORD": "", "PYTHONHASHSEED": "42",
    }
    os.environ.update(env)
    subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], check=True)
    with psycopg.connect(dsn) as db:
        db.execute("insert into groups (name, course) values ('АУДИТ 101', 1)")
        db.execute("""insert into feedback_recipients (kind, title, emails, is_active, sort_order)
                    values ('methodist', 'Аудит', '["audit@example.invalid"]', true, 0)""")

    with ExitStack() as cleanup:
        clients = []
        for _ in range(2):
            api_port = local_port()
            server = """import asyncio, sys, uvicorn
config = uvicorn.Config('app.main:app', host='127.0.0.1', port=int(sys.argv[1]), access_log=False, proxy_headers=False)
asyncio.run(uvicorn.Server(config).serve(), loop_factory=asyncio.SelectorEventLoop)
"""
            process = subprocess.Popen([sys.executable, "-c", server, str(api_port)], stdout=subprocess.DEVNULL)
            cleanup.callback(process.wait, 10)
            cleanup.callback(process.terminate)
            clients.append(httpx.AsyncClient(base_url=f"http://127.0.0.1:{api_port}", trust_env=False))

        async def run() -> None:
            async with clients[0], clients[1]:
                await check(clients, dsn)

        asyncio.run(run())


if __name__ == "__main__":
    main()
