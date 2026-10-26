"""Схемы профиля студента."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class StudentRegisterIn(BaseModel):
    full_name: str = Field(min_length=3, max_length=200, description="ФИО — персональные данные")
    group_id: int
    # Случайный ключ устройства (тот же, что у обращений). По нему находится профиль.
    device_key: str = Field(min_length=16, max_length=128)


class StudentProfileOut(BaseModel):
    id: int
    full_name: str
    group_id: int | None
    group_name: str | None


class StudentTokenOut(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_at: datetime
    profile: StudentProfileOut


class MeOut(StudentProfileOut):
    unread_count: int
