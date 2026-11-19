import asyncio
import json
from pathlib import Path

import httpx
import pytest
import uvicorn
from fastapi import FastAPI, Request


@pytest.mark.parametrize(
    ("trusted", "peer", "expected"),
    [
        (None, "127.0.0.1", "198.51.100.42"),
        (None, "203.0.113.7", "203.0.113.7"),
        ("172.18.0.1", "172.18.0.1", "198.51.100.42"),
        ("172.18.0.1", "127.0.0.1", "127.0.0.1"),
        ("*", "172.18.0.1", "198.51.100.42"),
    ],
)
def test_uvicorn_proxy_headers(
    monkeypatch: pytest.MonkeyPatch, trusted: str | None, peer: str, expected: str
) -> None:
    if trusted is None:
        monkeypatch.delenv("FORWARDED_ALLOW_IPS", raising=False)
    else:
        monkeypatch.setenv("FORWARDED_ALLOW_IPS", trusted)

    dockerfile = Path(__file__).resolve().parents[1] / "Dockerfile"
    command = next(line[4:] for line in dockerfile.read_text().splitlines() if line.startswith("CMD "))
    args = json.loads(command)
    assert "--proxy-headers" in args
    assert "--forwarded-allow-ips" not in args

    app = FastAPI()

    @app.get("/")
    def client_host(request: Request) -> dict[str, str]:
        assert request.client is not None
        return {"host": request.client.host}

    config = uvicorn.Config(
        app,
        host=args[args.index("--host") + 1],
        port=int(args[args.index("--port") + 1]),
        proxy_headers="--proxy-headers" in args,
    )
    config.load()

    async def request() -> None:
        transport = httpx.ASGITransport(app=config.loaded_app, client=(peer, 12345))
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/", headers={"X-Forwarded-For": "198.51.100.42"})
        assert response.json() == {"host": expected}

    asyncio.run(request())
