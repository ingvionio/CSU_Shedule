from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient


def asgi_client(app: FastAPI) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver")
