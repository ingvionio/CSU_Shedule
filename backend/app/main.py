import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.router import api_router
from app.core.config import get_settings

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    from app.services.moodle_sessions import start_worker

    stop, worker = start_worker()
    try:
        yield
    finally:
        stop.set()
        await asyncio.to_thread(worker.join, 15)


app = FastAPI(
    title="Расписание ЧелГУ — API",
    version="0.1.0",
    lifespan=lifespan,
    description="Расписание института информационных технологий: группы, недели, пары.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix=settings.api_prefix)


@app.get("/health", tags=["service"], summary="Проверка живости")
def health() -> dict[str, str]:
    return {"status": "ok"}
