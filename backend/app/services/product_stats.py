"""Статистика ЛК продукта: пользователи, активность, воронка входа, функции, APK.

Дни считаются по Челябинску. Часовой пояс зафиксирован (UTC+5, без перехода
на летнее время), чтобы не зависеть от TZ контейнера.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Group, Message, ProductEvent, PushSubscription, User
from app.services import product_events as ev

LOCAL_TZ = timezone(timedelta(hours=5), "Челябинск")
MAX_PERIOD_DAYS = 731
DEFAULT_PERIOD_DAYS = 30
# «Заходил в этот день» — любое действие студента. Не считаются события, которые
# происходят без его участия: сообщение ему отправили, push ему доставили.
PASSIVE_EVENTS = (ev.MESSAGE_RECEIVED, ev.PUSH_SENT)
FUNNEL = (ev.LANDING_VIEW, ev.LOGIN_CLICK, ev.LOGIN_SUBMIT, ev.LOGIN_SUCCESS)
# Использование функций: события студентов, по которым строится блок «Функции».
FEATURE_EVENTS = (
    ev.APP_OPEN,
    ev.SCHEDULE_DAY_VIEW,
    ev.SCHEDULE_WEEK_VIEW,
    ev.NOTE_SAVED,
    ev.MAP_OPEN,
    ev.HELP_OPEN,
    ev.MESSAGE_RECEIVED,
    ev.PUSH_SENT,
    ev.PUSH_OPEN,
    ev.MESSAGE_READ,
    ev.MESSAGE_ACK,
    ev.FEEDBACK_SENT,
    ev.PUSH_SUBSCRIBED,
)
RETENTION_WEEKS = (1, 2, 4)
USER_SORTS = ("last_seen", "created", "name", "group")
USER_ORDERS = ("asc", "desc")


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

    @property
    def end_utc(self) -> datetime:
        """Граница «до»: полночь дня после конца периода."""
        return local_midnight_utc(self.end + timedelta(days=1))

    @property
    def days(self) -> int:
        return (self.end - self.start).days + 1

    def dates(self) -> list[date]:
        return [self.start + timedelta(days=offset) for offset in range(self.days)]


def resolve_period(start: date | None, end: date | None, now: datetime) -> Period:
    """Период по датам Челябинска. Без дат — последние 30 дней."""
    today = local_date(now)
    end = end or today
    start = start or end - timedelta(days=DEFAULT_PERIOD_DAYS - 1)
    if start > end:
        raise ProductStatsError("начало периода позже конца", 422)
    if (end - start).days + 1 > MAX_PERIOD_DAYS:
        raise ProductStatsError(f"период не длиннее {MAX_PERIOD_DAYS} дней", 422)
    return Period(start=start, end=end)


def _students():
    return select(User).where(User.role == "student")


def _in_period(period: Period):
    return (ProductEvent.occurred_at >= period.start_utc, ProductEvent.occurred_at < period.end_utc)


def _count(db: Session, name: str, period: Period) -> int:
    return db.scalar(select(func.count(ProductEvent.id)).where(ProductEvent.name == name, *_in_period(period))) or 0


def _active_days(db: Session, since: date, until: date, user_ids: Iterable[int] | None = None) -> dict[int, set[date]]:
    """Дни (по Челябинску), в которые студент что-то делал в приложении.

    Кроме событий учитываются отметки профиля: первый вход, последний вход через
    Moodle и последняя активность общей сессии. Так видна и активность до того,
    как начали собираться события, и заходы, событие которых не дошло.
    """
    low, high = local_midnight_utc(since), local_midnight_utc(until + timedelta(days=1))
    ids = list(user_ids) if user_ids is not None else None
    if ids is not None and not ids:
        return {}
    days: dict[int, set[date]] = defaultdict(set)

    query = select(ProductEvent.user_id, ProductEvent.occurred_at).where(
        ProductEvent.name.not_in(PASSIVE_EVENTS),
        ProductEvent.user_id.is_not(None),
        ProductEvent.occurred_at >= low,
        ProductEvent.occurred_at < high,
    )
    if ids is not None:
        query = query.where(ProductEvent.user_id.in_(ids))
    for user_id, occurred_at in db.execute(query):
        days[user_id].add(local_date(occurred_at))

    profile = select(User.id, User.created_at, User.last_seen_at, User.session_last_active_at).where(User.role == "student")
    if ids is not None:
        profile = profile.where(User.id.in_(ids))
    for user_id, *moments in db.execute(profile):
        for moment in moments:
            if moment is not None and low <= as_utc(moment) < high:
                days[user_id].add(local_date(moment))
    return days


def _funnel(db: Session, period: Period) -> dict:
    """Воронка по устройствам: каждый шаг — только среди тех, кто прошёл предыдущий.

    Отдельно — сколько устройств вошло, не открывая лендинг за период
    (уже были на нём раньше, пришли по прямой ссылке или из уведомления).
    """
    devices: dict[str, set[str]] = defaultdict(set)
    for name, device in db.execute(
        select(ProductEvent.name, ProductEvent.device_hash)
        .where(ProductEvent.name.in_(FUNNEL), ProductEvent.device_hash.is_not(None), *_in_period(period))
        .distinct()
    ):
        devices[name].add(device)
    steps: dict[str, int] = {}
    passed: set[str] | None = None
    for name in FUNNEL:
        passed = devices[name] if passed is None else passed & devices[name]
        steps[name] = len(passed)
    logged_in = devices[ev.LOGIN_SUCCESS]
    return {
        **steps,
        "login_any": len(logged_in),
        "login_without_landing": len(logged_in - devices[ev.LANDING_VIEW]),
    }


def _retention(db: Session, period: Period, today: date) -> list[dict]:
    """Доля новых за период, вернувшихся на N-й неделе после первого входа.

    Учитываются только те, у кого N-я неделя уже закончилась.
    """
    cohort = {
        user_id: local_date(created_at)
        for user_id, created_at in db.execute(
            select(User.id, User.created_at).where(
                User.role == "student", User.created_at >= period.start_utc, User.created_at < period.end_utc
            )
        )
    }
    activity = _active_days(db, period.start, today, cohort) if cohort else {}
    result = []
    for week in RETENTION_WEEKS:
        eligible = returned = 0
        for user_id, first_day in cohort.items():
            window_start = first_day + timedelta(days=7 * week)
            window_end = window_start + timedelta(days=6)
            if window_end > today:
                continue
            eligible += 1
            if any(window_start <= day <= window_end for day in activity.get(user_id, ())):
                returned += 1
        result.append({"week": week, "eligible": eligible, "returned": returned})
    return result


def _groups(db: Session, period: Period, active_users: set[int]) -> list[dict]:
    """Охват групп: сколько студентов каждой группы вошли в приложение. Размер группы нам неизвестен."""
    stats: dict[int, dict] = {
        group.id: {"id": group.id, "name": group.name, "course": group.course, "users": 0, "new": 0, "active": 0}
        for group in db.scalars(select(Group).order_by(Group.course, Group.name))
    }
    for user_id, group_id, created_at in db.execute(
        select(User.id, User.group_id, User.created_at).where(User.role == "student", User.group_id.is_not(None))
    ):
        row = stats.get(group_id)
        if row is None:
            continue
        row["users"] += 1
        if period.start <= local_date(created_at) <= period.end:
            row["new"] += 1
        if user_id in active_users:
            row["active"] += 1
    return list(stats.values())


def summary(db: Session, start: date | None = None, end: date | None = None, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    period = resolve_period(start, end, now)
    today = local_date(now)

    # DAU / WAU / MAU — на последний день периода.
    window_start = min(period.start, period.end - timedelta(days=29))
    activity = _active_days(db, window_start, period.end)
    active_by_day: dict[date, set[int]] = defaultdict(set)
    for user_id, days in activity.items():
        for day in days:
            active_by_day[day].add(user_id)

    def active_between(first: date, last: date) -> set[int]:
        users: set[int] = set()
        for day, ids in active_by_day.items():
            if first <= day <= last:
                users |= ids
        return users

    active_users = active_between(period.start, period.end)

    last_platform: dict[int, tuple[datetime, str | None]] = {}
    for user_id, occurred_at, platform in db.execute(
        select(ProductEvent.user_id, ProductEvent.occurred_at, ProductEvent.platform).where(
            ProductEvent.user_id.is_not(None), ProductEvent.platform.is_not(None), *_in_period(period)
        )
    ):
        moment = as_utc(occurred_at)
        if user_id not in last_platform or moment >= last_platform[user_id][0]:
            last_platform[user_id] = (moment, platform)
    by_platform: dict[str, int] = defaultdict(int)
    for user_id in active_users:
        by_platform[last_platform[user_id][1] if user_id in last_platform else "unknown"] += 1

    new_by_day: dict[date, int] = defaultdict(int)
    for created_at in db.scalars(
        select(User.created_at).where(
            User.role == "student", User.created_at >= period.start_utc, User.created_at < period.end_utc
        )
    ):
        new_by_day[local_date(created_at)] += 1

    landing_by_day: dict[date, set[str]] = defaultdict(set)
    success_by_day: dict[date, int] = defaultdict(int)
    for name, device, occurred_at in db.execute(
        select(ProductEvent.name, ProductEvent.device_hash, ProductEvent.occurred_at).where(
            ProductEvent.name.in_((ev.LANDING_VIEW, ev.LOGIN_SUCCESS)), *_in_period(period)
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
    apk_installs = db.scalar(
        select(func.count())
        .select_from(first_apk)
        .where(first_apk.c.first_at >= period.start_utc, first_apk.c.first_at < period.end_utc)
    ) or 0

    feature_rows = {
        name: (events, users)
        for name, events, users in db.execute(
            select(ProductEvent.name, func.count(ProductEvent.id), func.count(func.distinct(ProductEvent.user_id)))
            .where(ProductEvent.name.in_(FEATURE_EVENTS), *_in_period(period))
            .group_by(ProductEvent.name)
        )
    }

    users_total = db.scalar(select(func.count()).select_from(_students().subquery())) or 0
    users_with_push = db.scalar(select(func.count(func.distinct(PushSubscription.user_id)))) or 0

    return {
        "start_date": period.start,
        "end_date": period.end,
        "days": period.days,
        "users_total": users_total,
        "users_new": sum(new_by_day.values()),
        "active_users": len(active_users),
        "dau": len(active_by_day.get(period.end, ())),
        "wau": len(active_between(period.end - timedelta(days=6), period.end)),
        "mau": len(active_between(period.end - timedelta(days=29), period.end)),
        "users_with_push": users_with_push,
        "funnel": _funnel(db, period),
        "tracking_since": local_date(first_event) if (first_event := db.scalar(select(func.min(ProductEvent.occurred_at)))) else None,
        "login_failures": {
            "auth": _count(db, ev.LOGIN_FAILED_AUTH, period),
            "group": _count(db, ev.LOGIN_FAILED_GROUP, period),
            "other": _count(db, ev.LOGIN_FAILED_OTHER, period),
        },
        "apk_downloads": _count(db, ev.APK_DOWNLOAD, period),
        "apk_installs": apk_installs,
        "apk_installs_total": apk_installs_total,
        "by_platform": dict(by_platform),
        "features": [
            {"name": name, "events": feature_rows.get(name, (0, 0))[0], "users": feature_rows.get(name, (0, 0))[1]}
            for name in FEATURE_EVENTS
        ],
        "retention": _retention(db, period, today),
        "groups": _groups(db, period, active_users),
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


# --- пользователи ---


def _last_event_subquery():
    return (
        select(ProductEvent.user_id, func.max(ProductEvent.occurred_at).label("last_at"))
        .where(ProductEvent.user_id.is_not(None))
        .group_by(ProductEvent.user_id)
        .subquery()
    )


def _user_rows(db: Session, users: list[User], now: datetime) -> list[dict]:
    """Последний заход, активные дни за 30 дней и последняя платформа — для списка и карточки."""
    ids = [user.id for user in users]
    last_seen: dict[int, datetime] = {}
    platforms: dict[int, tuple[datetime, str]] = {}
    today = local_date(now)
    days = _active_days(db, today - timedelta(days=29), today, ids)
    if ids:
        for user_id, moment in db.execute(
            select(ProductEvent.user_id, func.max(ProductEvent.occurred_at))
            .where(ProductEvent.user_id.in_(ids))
            .group_by(ProductEvent.user_id)
        ):
            last_seen[user_id] = as_utc(moment)
        for user_id, moment, platform in db.execute(
            select(ProductEvent.user_id, ProductEvent.occurred_at, ProductEvent.platform).where(
                ProductEvent.user_id.in_(ids),
                ProductEvent.platform.is_not(None),
                ProductEvent.occurred_at >= local_midnight_utc(today - timedelta(days=89)),
            )
        ):
            moment = as_utc(moment)
            if user_id not in platforms or moment >= platforms[user_id][0]:
                platforms[user_id] = (moment, platform)

    rows = []
    for user in users:
        seen = last_seen.get(user.id) or (as_utc(user.last_seen_at) if user.last_seen_at else None)
        rows.append(
            {
                "id": user.id,
                "full_name": user.full_name,
                "group": {"id": user.group.id, "name": user.group.name, "course": user.group.course} if user.group else None,
                "created_at": as_utc(user.created_at),
                "last_seen_at": seen,
                "active_days_30": len(days.get(user.id, ())),
                "last_platform": platforms[user.id][1] if user.id in platforms else None,
            }
        )
    return rows


def users(
    db: Session,
    *,
    q: str | None = None,
    group_id: int | None = None,
    last_seen_from: date | None = None,
    last_seen_to: date | None = None,
    created_from: date | None = None,
    created_to: date | None = None,
    sort: str = "last_seen",
    order: str | None = None,
    limit: int = 50,
    offset: int = 0,
    now: datetime | None = None,
) -> dict:
    """Студенты с фильтрами по ФИО, группе, дате последнего захода и первого входа (даты по Челябинску)."""
    now = now or datetime.now(timezone.utc)
    if sort not in USER_SORTS:
        raise ProductStatsError("неизвестная сортировка", 422)
    # По умолчанию — как ожидают от столбца: даты от новых, текст по алфавиту.
    order = order or ("asc" if sort in ("name", "group") else "desc")
    if order not in USER_ORDERS:
        raise ProductStatsError("порядок сортировки — asc или desc", 422)
    last_event = _last_event_subquery()
    seen = func.coalesce(last_event.c.last_at, User.last_seen_at, User.created_at)
    query = _students().outerjoin(last_event, last_event.c.user_id == User.id)
    if q and q.strip():
        query = query.where(User.full_name.ilike(f"%{q.strip()}%"))
    if group_id is not None:
        query = query.where(User.group_id == group_id)
    if last_seen_from:
        query = query.where(seen >= local_midnight_utc(last_seen_from))
    if last_seen_to:
        query = query.where(seen < local_midnight_utc(last_seen_to + timedelta(days=1)))
    if created_from:
        query = query.where(User.created_at >= local_midnight_utc(created_from))
    if created_to:
        query = query.where(User.created_at < local_midnight_utc(created_to + timedelta(days=1)))

    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    if sort == "group":
        query = query.outerjoin(Group, Group.id == User.group_id)
    column = {"last_seen": seen, "created": User.created_at, "name": User.full_name, "group": Group.name}[sort]
    direction = column.asc() if order == "asc" else column.desc()
    # Пустые значения (нет группы) — всегда в конце; при равенстве — по ФИО.
    ordering = (column.is_(None), direction, User.full_name.asc(), User.id.asc())
    page = list(db.scalars(query.order_by(*ordering).limit(limit).offset(offset)).unique())
    return {"total": total, "items": _user_rows(db, page, now)}


def user_detail(db: Session, user_id: int, now: datetime | None = None) -> dict:
    """Карточка: профиль и сколько раз студент сделал каждое действие за всё время."""
    now = now or datetime.now(timezone.utc)
    user = db.scalar(_students().where(User.id == user_id))
    if user is None:
        raise ProductStatsError("пользователь не найден", 404)
    counts = {
        name: count
        for name, count in db.execute(
            select(ProductEvent.name, func.count(ProductEvent.id))
            .where(ProductEvent.user_id == user_id)
            .group_by(ProductEvent.name)
        )
    }
    has_push = db.scalar(select(func.count(PushSubscription.id)).where(PushSubscription.user_id == user_id)) or 0
    return {"user": _user_rows(db, [user], now)[0], "counts": counts, "push_enabled": has_push > 0}


def user_events(db: Session, user_id: int, *, limit: int, before: int | None) -> dict:
    if db.scalar(_students().where(User.id == user_id)) is None:
        raise ProductStatsError("пользователь не найден", 404)
    query = select(ProductEvent).where(ProductEvent.user_id == user_id)
    if before is not None:
        # Курсор — событие, после которого продолжать: строго раньше по (время, id).
        anchor = db.get(ProductEvent, before)
        if anchor is not None:
            query = query.where(
                (ProductEvent.occurred_at < anchor.occurred_at)
                | ((ProductEvent.occurred_at == anchor.occurred_at) & (ProductEvent.id < anchor.id))
            )
    order = (ProductEvent.occurred_at.desc(), ProductEvent.id.desc())
    rows = list(db.scalars(query.order_by(*order).limit(limit + 1)))
    more = len(rows) > limit
    rows = rows[:limit]

    message_ids = {row.props["message_id"] for row in rows if isinstance(row.props, dict) and row.props.get("message_id")}
    titles = (
        dict(db.execute(select(Message.id, Message.title).where(Message.id.in_(message_ids))).all()) if message_ids else {}
    )
    items = []
    for row in rows:
        message_id = row.props.get("message_id") if isinstance(row.props, dict) else None
        items.append(
            {
                "id": row.id,
                "occurred_at": as_utc(row.occurred_at),
                "name": row.name,
                "platform": row.platform,
                "app_version": row.app_version,
                "detail": titles.get(message_id) if message_id else None,
            }
        )
    return {"items": items, "next_before": rows[-1].id if more and rows else None}
