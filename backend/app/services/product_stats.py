"""Статистика ЛК продукта: пользователи, активность, воронка входа, APK.

Дни считаются по Челябинску. Часовой пояс зафиксирован (UTC+5, без перехода
на летнее время), чтобы не зависеть от TZ контейнера.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import ProductEvent, User
from app.services import product_events as ev

LOCAL_TZ = timezone(timedelta(hours=5), "Челябинск")
PERIODS = (1, 7, 30, 90)
# Что считается «заходил в этот день».
ACTIVE_EVENTS = (ev.APP_OPEN, ev.LOGIN_SUCCESS)
FUNNEL = (ev.LANDING_VIEW, ev.LOGIN_CLICK, ev.LOGIN_SUBMIT, ev.LOGIN_SUCCESS)


class ProductStatsError(Exception):
    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


def as_utc(value: datetime) -> datetime:
    """SQLite отдаёт время без пояса; в базе оно всегда UTC."""
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def local_date(value: datetime) -> date:
    return as_utc(value).astimezone(LOCAL_TZ).date()


def local_midnight_utc(day: date) -> datetime:
    return datetime.combine(day, time.min, LOCAL_TZ).astimezone(timezone.utc)


@dataclass(frozen=True)
class Period:
    start: date
    end: date

    @property
    def start_utc(self) -> datetime:
        return local_midnight_utc(self.start)

    def dates(self) -> list[date]:
        return [self.start + timedelta(days=offset) for offset in range((self.end - self.start).days + 1)]


def period_of(days: int, now: datetime) -> Period:
    today = local_date(now)
    return Period(start=today - timedelta(days=days - 1), end=today)


def _students():
    return select(User).where(User.role == "student")


def _distinct_devices(db: Session, name: str, since: datetime) -> int:
    return db.scalar(
        select(func.count(func.distinct(ProductEvent.device_hash))).where(
            ProductEvent.name == name, ProductEvent.occurred_at >= since, ProductEvent.device_hash.is_not(None)
        )
    ) or 0


def _count(db: Session, name: str, since: datetime) -> int:
    return db.scalar(
        select(func.count(ProductEvent.id)).where(ProductEvent.name == name, ProductEvent.occurred_at >= since)
    ) or 0


def summary(db: Session, days: int, now: datetime | None = None) -> dict:
    if days not in PERIODS:
        raise ProductStatsError(f"период — одно из значений: {', '.join(map(str, PERIODS))} дней", 422)
    now = now or datetime.now(timezone.utc)
    period = period_of(days, now)
    since = period.start_utc
    today = period.end
    # Окно активности: и для MAU (30 дней), и для выбранного периода.
    window_start = min(period.start, today - timedelta(days=29))

    active_by_day: dict[date, set[int]] = defaultdict(set)
    last_platform: dict[int, tuple[datetime, str | None]] = {}
    rows = db.execute(
        select(ProductEvent.user_id, ProductEvent.occurred_at, ProductEvent.platform).where(
            ProductEvent.name.in_(ACTIVE_EVENTS),
            ProductEvent.user_id.is_not(None),
            ProductEvent.occurred_at >= local_midnight_utc(window_start),
        )
    ).all()
    for user_id, occurred_at, platform in rows:
        day = local_date(occurred_at)
        active_by_day[day].add(user_id)
        if day >= period.start:
            moment = as_utc(occurred_at)
            if user_id not in last_platform or moment >= last_platform[user_id][0]:
                last_platform[user_id] = (moment, platform)

    def active_since(first: date) -> int:
        users: set[int] = set()
        for day, ids in active_by_day.items():
            if day >= first:
                users |= ids
        return len(users)

    by_platform: dict[str, int] = defaultdict(int)
    for _, platform in last_platform.values():
        by_platform[platform or "unknown"] += 1

    new_by_day: dict[date, int] = defaultdict(int)
    for created_at in db.scalars(select(User.created_at).where(User.role == "student", User.created_at >= since)):
        new_by_day[local_date(created_at)] += 1

    landing_by_day: dict[date, set[str]] = defaultdict(set)
    success_by_day: dict[date, int] = defaultdict(int)
    for name, device, occurred_at in db.execute(
        select(ProductEvent.name, ProductEvent.device_hash, ProductEvent.occurred_at).where(
            ProductEvent.name.in_((ev.LANDING_VIEW, ev.LOGIN_SUCCESS)), ProductEvent.occurred_at >= since
        )
    ):
        day = local_date(occurred_at)
        if name == ev.LANDING_VIEW and device:
            landing_by_day[day].add(device)
        elif name == ev.LOGIN_SUCCESS:
            success_by_day[day] += 1

    first_apk = (
        select(func.min(ProductEvent.occurred_at).label("first_at"))
        .where(ProductEvent.platform == "apk", ProductEvent.device_hash.is_not(None))
        .group_by(ProductEvent.device_hash)
        .subquery()
    )
    apk_installs_total = db.scalar(select(func.count()).select_from(first_apk)) or 0
    apk_installs = db.scalar(select(func.count()).select_from(first_apk).where(first_apk.c.first_at >= since)) or 0

    return {
        "days": days,
        "start_date": period.start,
        "end_date": period.end,
        "users_total": db.scalar(select(func.count()).select_from(_students().subquery())) or 0,
        "users_new": sum(new_by_day.values()),
        "dau": active_since(today),
        "wau": active_since(today - timedelta(days=6)),
        "mau": active_since(today - timedelta(days=29)),
        "funnel": {name: _distinct_devices(db, name, since) for name in FUNNEL},
        "login_failures": {
            "auth": _count(db, ev.LOGIN_FAILED_AUTH, since),
            "group": _count(db, ev.LOGIN_FAILED_GROUP, since),
            "other": _count(db, ev.LOGIN_FAILED_OTHER, since),
        },
        "apk_downloads": _count(db, ev.APK_DOWNLOAD, since),
        "apk_installs": apk_installs,
        "apk_installs_total": apk_installs_total,
        "by_platform": dict(by_platform),
        "daily": [
            {
                "date": day,
                "dau": len(active_by_day.get(day, ())),
                "new_users": new_by_day.get(day, 0),
                "landing_devices": len(landing_by_day.get(day, ())),
                "login_success": success_by_day.get(day, 0),
            }
            for day in period.dates()
        ],
    }


def _user_details(db: Session, users: list[User], now: datetime) -> list[dict]:
    """Последний заход, активные дни за 30 дней и последняя платформа — для страницы списка."""
    ids = [user.id for user in users]
    last_seen: dict[int, datetime] = {}
    platforms: dict[int, tuple[datetime, str]] = {}
    days: dict[int, set[date]] = defaultdict(set)
    if ids:
        for user_id, moment in db.execute(
            select(ProductEvent.user_id, func.max(ProductEvent.occurred_at))
            .where(ProductEvent.user_id.in_(ids))
            .group_by(ProductEvent.user_id)
        ):
            last_seen[user_id] = as_utc(moment)
        month_start = local_midnight_utc(local_date(now) - timedelta(days=29))
        for user_id, moment, name, platform in db.execute(
            select(ProductEvent.user_id, ProductEvent.occurred_at, ProductEvent.name, ProductEvent.platform).where(
                ProductEvent.user_id.in_(ids), ProductEvent.occurred_at >= month_start
            )
        ):
            if name in ACTIVE_EVENTS:
                days[user_id].add(local_date(moment))
            moment = as_utc(moment)
            if platform and (user_id not in platforms or moment >= platforms[user_id][0]):
                platforms[user_id] = (moment, platform)

    result = []
    for user in users:
        seen = last_seen.get(user.id) or (as_utc(user.last_seen_at) if user.last_seen_at else None)
        result.append(
            {
                "id": user.id,
                "full_name": user.full_name,
                "group": {"name": user.group.name, "course": user.group.course} if user.group else None,
                "created_at": as_utc(user.created_at),
                "last_seen_at": seen,
                "active_days_30": len(days.get(user.id, ())),
                "last_platform": platforms[user.id][1] if user.id in platforms else None,
            }
        )
    return result


def users(
    db: Session,
    *,
    q: str | None,
    group_id: int | None,
    sort: str,
    limit: int,
    offset: int,
    now: datetime | None = None,
) -> dict:
    now = now or datetime.now(timezone.utc)
    last_event = (
        select(ProductEvent.user_id, func.max(ProductEvent.occurred_at).label("last_at"))
        .where(ProductEvent.user_id.is_not(None))
        .group_by(ProductEvent.user_id)
        .subquery()
    )
    query = _students().outerjoin(last_event, last_event.c.user_id == User.id)
    if q and q.strip():
        query = query.where(User.full_name.ilike(f"%{q.strip()}%"))
    if group_id is not None:
        query = query.where(User.group_id == group_id)

    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    if sort == "created":
        query = query.order_by(User.created_at.desc(), User.id.desc())
    else:
        seen = func.coalesce(last_event.c.last_at, User.last_seen_at, User.created_at)
        query = query.order_by(seen.desc(), User.id.desc())
    page = list(db.scalars(query.limit(limit).offset(offset)).unique())
    return {"total": total, "items": _user_details(db, page, now)}


def user_events(db: Session, user_id: int, *, limit: int, before: int | None, now: datetime | None = None) -> dict:
    user = db.scalar(_students().where(User.id == user_id))
    if user is None:
        raise ProductStatsError("пользователь не найден", 404)
    query = select(ProductEvent).where(ProductEvent.user_id == user_id)
    if before is not None:
        query = query.where(ProductEvent.id < before)
    rows = list(db.scalars(query.order_by(ProductEvent.id.desc()).limit(limit + 1)))
    more = len(rows) > limit
    rows = rows[:limit]
    return {
        "user": _user_details(db, [user], now or datetime.now(timezone.utc))[0],
        "items": [
            {
                "id": row.id,
                "occurred_at": as_utc(row.occurred_at),
                "name": row.name,
                "platform": row.platform,
                "app_version": row.app_version,
            }
            for row in rows
        ],
        "next_before": rows[-1].id if more and rows else None,
    }

