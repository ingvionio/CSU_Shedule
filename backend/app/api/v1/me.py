"""Эндпоинты студента с профилем: /me. Требуют студенческий токен."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.auth import profile_out
from app.core.db import get_db
from app.core.security import require_student
from app.models import User
from app.schemas.student import MeOut, PushSubscriptionIn, PushSubscriptionOut
from app.services import messages as messages_service
from app.services import product_events
from app.services import push as push_service
from app.services import students as students_service

router = APIRouter(prefix="/me")


async def current_student(user_id: int = Depends(require_student), db: AsyncSession = Depends(get_db, scope="function")) -> User:
    try:
        return await students_service.get_student(db, user_id)
    except students_service.StudentError as error:
        raise HTTPException(error.status_code, str(error)) from error


@router.get("", response_model=MeOut, summary="Профиль и число непрочитанных")
async def me(user: User = Depends(current_student), db: AsyncSession = Depends(get_db, scope="function")) -> MeOut:
    return MeOut(**profile_out(user).model_dump(), unread_count=await messages_service.unread_count(db, user.id))


@router.post(
    "/push-subscriptions",
    response_model=PushSubscriptionOut,
    status_code=status.HTTP_201_CREATED,
    summary="Подписать это устройство на push",
)
async def subscribe_push(
    data: PushSubscriptionIn,
    user_agent: str | None = Header(default=None),
    user: User = Depends(current_student),
    db: AsyncSession = Depends(get_db, scope="function"),
) -> PushSubscriptionOut:
    subscription = await push_service.subscribe(db, user.id, data.endpoint, data.keys.p256dh, data.keys.auth, user_agent)
    await product_events.record_server_event(db, product_events.PUSH_SUBSCRIBED, user_id=user.id)
    return PushSubscriptionOut(id=subscription.id)


@router.delete("/push-subscriptions/{subscription_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Отписаться")
async def unsubscribe_push(subscription_id: int, user: User = Depends(current_student), db: AsyncSession = Depends(get_db, scope="function")) -> None:
    if not await push_service.unsubscribe(db, user.id, subscription_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "подписка не найдена")
