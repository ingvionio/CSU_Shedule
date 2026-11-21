"""ЛК продукта: приём событий от клиента и статистика для /statistic."""

from __future__ import annotations

from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.security import optional_student, require_product
from app.schemas.product import EventsIn, ProductUserDetailOut, ProductUserEventsOut, ProductUsersOut, SummaryOut
from app.services import product_events, product_stats

router = APIRouter()
product_router = APIRouter(prefix="/product", dependencies=[Depends(require_product)])


@router.post("/events", status_code=status.HTTP_204_NO_CONTENT, summary="События для статистики (публичный)")
async def post_events(
    data: EventsIn,
    user_id: int | None = Depends(optional_student),
    db: AsyncSession = Depends(get_db, scope="function"),
) -> Response:
    """Токен студента необязателен: без него или с недействительным событие пишется без пользователя."""
    await product_events.accept_client_events(
        db,
        names=[event.name for event in data.events],
        device_key=data.device_key,
        user_id=user_id,
        platform=data.platform,
        app_version=data.app_version,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _raise(error: product_stats.ProductStatsError) -> None:
    raise HTTPException(error.status_code, str(error)) from error


@product_router.get("/summary", response_model=SummaryOut, summary="Сводка за период: пользователи, воронка, функции, APK")
async def get_summary(
    start: date | None = Query(None, description="первый день периода по Челябинску; по умолчанию — 30 дней до end"),
    end: date | None = Query(None, description="последний день периода; по умолчанию — сегодня"),
    db: AsyncSession = Depends(get_db, scope="function"),
) -> dict:
    try:
        return await product_stats.summary(db, start, end)
    except product_stats.ProductStatsError as error:
        _raise(error)


@product_router.get("/users", response_model=ProductUsersOut, summary="Пользователи с фильтрами")
async def get_users(
    q: str | None = Query(None, max_length=100),
    group_id: int | None = None,
    last_seen_from: date | None = None,
    last_seen_to: date | None = None,
    created_from: date | None = Query(None, description="первый вход не раньше"),
    created_to: date | None = Query(None, description="первый вход не позже"),
    platform: Literal["web", "pwa", "apk", "unknown"] | None = Query(None, description="последняя платформа; unknown — не определена"),
    sort: Literal["last_seen", "created", "name", "group", "active_days", "platform"] = "last_seen",
    order: Literal["asc", "desc"] | None = Query(None, description="по умолчанию: даты и дни — desc, ФИО, группа и платформа — asc"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db, scope="function"),
) -> dict:
    return await product_stats.users(
        db,
        q=q,
        group_id=group_id,
        last_seen_from=last_seen_from,
        last_seen_to=last_seen_to,
        created_from=created_from,
        created_to=created_to,
        platform=platform,
        sort=sort,
        order=order,
        limit=limit,
        offset=offset,
    )


@product_router.get("/users/{user_id}", response_model=ProductUserDetailOut, summary="Карточка пользователя")
async def get_user(user_id: int, db: AsyncSession = Depends(get_db, scope="function")) -> dict:
    try:
        return await product_stats.user_detail(db, user_id)
    except product_stats.ProductStatsError as error:
        _raise(error)


@product_router.get("/users/{user_id}/events", response_model=ProductUserEventsOut, summary="Действия пользователя")
async def get_user_events(
    user_id: int,
    limit: int = Query(100, ge=1, le=500),
    before: int | None = Query(None, ge=1),
    db: AsyncSession = Depends(get_db, scope="function"),
) -> dict:
    try:
        return await product_stats.user_events(db, user_id, limit=limit, before=before)
    except product_stats.ProductStatsError as error:
        _raise(error)
