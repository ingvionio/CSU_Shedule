"""Схемы профиля студента и авторизации через Moodle."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, BeforeValidator, Field


class StudentRegisterIn(BaseModel):
    full_name: str = Field(min_length=3, max_length=200, description="ФИО — персональные данные")
    group_id: int
    # Случайный ключ устройства (тот же, что у обращений). По нему находится профиль.
    device_key: str = Field(min_length=16, max_length=128)


class MoodleLoginIn(BaseModel):
    """Вход через учетную запись Moodle ИИТ ЧелГУ."""

    username: str = Field(min_length=1, max_length=100, description="Логин в Moodle ЧелГУ")
    password: str = Field(min_length=1, max_length=200, description="Пароль в Moodle ЧелГУ")
    device_key: str | None = Field(default=None, max_length=128, description="Случайный ключ устройства")


class StudentProfileOut(BaseModel):
    id: int
    full_name: str
    group_id: int | None
    group_name: str | None
    moodle_username: str | None = None
    moodle_auth_error: bool = False


class StudentTokenOut(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_at: datetime
    profile: StudentProfileOut


class MeOut(StudentProfileOut):
    unread_count: int


class PushKeysIn(BaseModel):
    p256dh: str = Field(min_length=1, max_length=200)
    auth: str = Field(min_length=1, max_length=100)


class WebPushSubscriptionIn(BaseModel):
    """Ровно то, что отдаёт `PushSubscription.toJSON()` в браузере."""

    platform: Literal["web"] = "web"
    endpoint: str = Field(min_length=10, max_length=2000, pattern=r"^https://")
    keys: PushKeysIn


class FcmPushSubscriptionIn(BaseModel):
    platform: Literal["fcm"]
    token: str = Field(min_length=20, max_length=4096)


def _default_push_platform(value: object) -> object:
    # Старые браузерные клиенты ещё не передают дискриминатор.
    if isinstance(value, dict) and "platform" not in value:
        return {**value, "platform": "web"}
    return value


PushSubscriptionIn = Annotated[
    WebPushSubscriptionIn | FcmPushSubscriptionIn,
    Field(discriminator="platform"), BeforeValidator(_default_push_platform),
]


class PushSubscriptionOut(BaseModel):
    id: int


class PushConfigOut(BaseModel):
    public_key: str | None
    fcm: bool
