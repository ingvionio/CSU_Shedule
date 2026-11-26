"""Размер запроса и заголовки API на уровне ASGI."""

from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from fastapi.security.utils import get_authorization_scheme_param
from starlette.datastructures import Headers, MutableHeaders
from starlette.formparsers import MultiPartException
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.db import SessionLocal
from app.core.security import admin_session

MIB = 1024 * 1024
BODY_LIMIT = 64 * 1024
UPLOAD_LIMITS = {
    "/admin/imports/weekly": 52 * MIB,
    "/admin/imports/semester": 21 * MIB,
    "/admin/exams/import": 21 * MIB,
}
PRIVATE_PREFIXES = ("/auth/", "/admin", "/me", "/product", "/feedback")
TOO_LARGE = "Превышен допустимый размер запроса"


class ApiSecurityMiddleware:
    def __init__(self, app: ASGIApp, prefix: str) -> None:
        self.app = app
        self.prefix = prefix.rstrip("/")

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not scope["path"].startswith(f"{self.prefix}/"):
            await self.app(scope, receive, send)
            return

        request_headers = Headers(scope=scope)
        route = scope["path"][len(self.prefix):].rstrip("/")
        multipart = request_headers.get("content-type", "").lower().startswith("multipart/form-data")
        limit = UPLOAD_LIMITS.get(route, BODY_LIMIT) if multipart else BODY_LIMIT
        length = request_headers.get("content-length", "")
        oversized = length.isascii() and length.isdecimal() and (len(length) > 10 or int(length) > limit)
        consumed = 0

        async def limited_receive() -> Message:
            nonlocal consumed, oversized
            message = await receive()
            if message["type"] == "http.request":
                consumed += len(message.get("body", b""))
                if consumed > limit:
                    oversized = True
                    if multipart:
                        # Starlette закрывает временные файлы только при MultiPartException.
                        raise MultiPartException(TOO_LARGE)
                    raise HTTPException(413, TOO_LARGE)
            return message

        async def secured_send(message: Message) -> None:
            if message["type"] == "http.response.start":
                if oversized:
                    message["status"] = 413
                headers = MutableHeaders(scope=message)
                headers["X-Content-Type-Options"] = "nosniff"
                if "authorization" in request_headers or route.startswith(PRIVATE_PREFIXES):
                    headers["Cache-Control"] = "no-store"
            await send(message)

        if oversized:
            await JSONResponse({"detail": TOO_LARGE}, 413)(scope, receive, secured_send)
            return

        if route in UPLOAD_LIMITS and scope["method"] == "POST":
            # FastAPI разбирает multipart до зависимостей маршрута.
            scheme, value = get_authorization_scheme_param(request_headers.get("authorization"))
            credentials = None
            if scheme.lower() == "bearer" and value:
                credentials = HTTPAuthorizationCredentials(scheme=scheme, credentials=value)
            try:
                async with SessionLocal() as db:
                    await admin_session(credentials, db)
            except HTTPException as error:
                response = JSONResponse({"detail": error.detail}, error.status_code, headers=error.headers)
                await response(scope, receive, secured_send)
                return
        await self.app(scope, limited_receive, secured_send)
