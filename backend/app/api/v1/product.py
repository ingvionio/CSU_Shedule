"""ЛК продукта: приём событий от клиента и статистика для /statistic."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.security import optional_student, require_product
from app.schemas.product import EventsIn, ProductUserEventsOut, ProductUsersOut, SummaryOut
from app.services import product_events, product_stats

router = APIRouter()
product_router = APIRouter(prefix="/product", dependencies=[Depends(require_product)])


@router.post("/events", status_code=status.HTTP_204_NO_CONTENT, summary="События для статистики (публичный)")
def post_events(
    data: EventsIn,
    user_id: int | None = Depends(optional_student),
    db: Session = Depends(get_db),
) -> Response:
    """Токен студента необязателен: без него или с недействительным событие пишется без пользователя."""
    product_events.accept_client_events(
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


@product_router.get("/summary", response_model=SummaryOut, summary="Сводка: пользователи, DAU/WAU/MAU, воронка, APK")
def get_summary(days: int = Query(30), db: Session = Depends(get_db)) -> dict:
    try:
        return product_stats.summary(db, days)
    except product_stats.ProductStatsError as error:
        _raise(error)


@product_router.get("/users", response_model=ProductUsersOut, summary="Пользователи и когда заходили")
def get_users(
    q: str | None = Query(None, max_length=100),
    group_id: int | None = None,
    sort: Literal["last_seen", "created"] = "last_seen",
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
) -> dict:
    return product_stats.users(db, q=q, group_id=group_id, sort=sort, limit=limit, offset=offset)


@product_router.get("/users/{user_id}/events", response_model=ProductUserEventsOut, summary="События пользователя")
def get_user_events(
    user_id: int,
    limit: int = Query(100, ge=1, le=500),
    before: int | None = Query(None, ge=1),
    db: Session = Depends(get_db),
) -> dict:
    try:
        return product_stats.user_events(db, user_id, limit=limit, before=before)
    except product_stats.ProductStatsError as error:
        _raise(error)
