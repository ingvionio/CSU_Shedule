"""Контракт ЛК продукта: приём событий и статистика."""

from datetime import date, datetime

from pydantic import BaseModel, Field


class EventIn(BaseModel):
    name: str = Field(max_length=64)


class EventsIn(BaseModel):
    device_key: str = Field(min_length=8, max_length=128, description="Случайный ключ устройства (тот же, что у обращений)")
    platform: str | None = Field(default=None, max_length=16, description="web / pwa / apk")
    app_version: str | None = Field(default=None, max_length=64)
    events: list[EventIn] = Field(min_length=1, max_length=20)


class FunnelOut(BaseModel):
    """Уникальные устройства на каждом шаге за период."""

    landing_view: int
    login_click: int
    login_submit: int
    login_success: int


class LoginFailuresOut(BaseModel):
    """Неудачные входы за период (число попыток)."""

    auth: int = Field(description="неверный логин или пароль")
    group: int = Field(description="не удалось определить группу")
    other: int = Field(description="Moodle недоступен и прочие ошибки")


class DailyOut(BaseModel):
    date: date
    dau: int
    new_users: int
    landing_devices: int
    login_success: int


class SummaryOut(BaseModel):
    days: int
    start_date: date
    end_date: date
    users_total: int
    users_new: int
    dau: int
    wau: int
    mau: int
    funnel: FunnelOut
    login_failures: LoginFailuresOut
    apk_downloads: int
    apk_installs: int
    apk_installs_total: int
    by_platform: dict[str, int] = Field(description="активные за период по последней платформе: web / pwa / apk / unknown")
    daily: list[DailyOut]


class ProductGroupOut(BaseModel):
    name: str
    course: int


class ProductUserOut(BaseModel):
    id: int
    full_name: str
    group: ProductGroupOut | None
    created_at: datetime
    last_seen_at: datetime | None
    active_days_30: int
    last_platform: str | None


class ProductUsersOut(BaseModel):
    total: int
    items: list[ProductUserOut]


class ProductEventOut(BaseModel):
    id: int
    occurred_at: datetime
    name: str
    platform: str | None
    app_version: str | None


class ProductUserEventsOut(BaseModel):
    user: ProductUserOut
    items: list[ProductEventOut]
    next_before: int | None = Field(description="передать в before, чтобы получить события старше; null — больше нет")
