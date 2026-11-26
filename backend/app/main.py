import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.v1.router import api_router
from app.core.config import get_settings
from app.core.db import engine
from app.core.http_security import ApiSecurityMiddleware

settings = get_settings()


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    from app.services.moodle_sessions import run_worker

    worker = asyncio.create_task(run_worker(), name="moodle-sessions")
    try:
        yield
    finally:
        worker.cancel()
        try:
            await worker
        except asyncio.CancelledError:
            pass
        finally:
            await engine.dispose()


app = FastAPI(
    title="Расписание ЧелГУ — API",
    version="0.1.0",
    description="Расписание института информационных технологий: группы, недели, пары.",
    lifespan=lifespan,
    openapi_url="/openapi.json" if settings.api_docs_enabled else None,
)

app.add_middleware(ApiSecurityMiddleware, prefix=settings.api_prefix)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix=settings.api_prefix)


@app.exception_handler(RequestValidationError)
async def validation_error(_: Request, error: RequestValidationError) -> JSONResponse:
    detail = [
        {"type": item["type"], "loc": item["loc"], "msg": item["msg"]}
        for item in error.errors()
    ]
    return JSONResponse({"detail": detail}, status_code=422)


@app.get("/health", tags=["service"], summary="Проверка живости")
async def health() -> dict[str, str]:
    return {"status": "ok"}
