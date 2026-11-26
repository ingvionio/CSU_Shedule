"""Общие квоты на запросы в PostgreSQL и SQLite."""

import hashlib
import hmac
from math import ceil
from time import time

from fastapi import HTTPException, Request
from sqlalchemy import case, delete
from sqlalchemy.dialects.postgresql import insert as postgres_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models import RequestQuota


async def enforce_quota(
    db: AsyncSession, scope: str, window: int, limits: list[tuple[str, int]],
) -> None:
    now = time()
    expires_at = (int(now) // window + 1) * window
    secret = get_settings().jwt_secret.encode()
    insert = postgres_insert if db.get_bind().dialect.name == "postgresql" else sqlite_insert
    for principal, limit in limits:
        key = hmac.digest(secret, f"quota:{scope}:{principal}".encode(), hashlib.sha256).hex()
        expired = RequestQuota.expires_at < expires_at
        statement = insert(RequestQuota).values(key=key, expires_at=expires_at, count=1)
        admitted = await db.scalar(statement.on_conflict_do_update(
            index_elements=[RequestQuota.key],
            set_={"expires_at": expires_at, "count": case((expired, 1), else_=RequestQuota.count + 1)},
            where=expired | ((RequestQuota.expires_at == expires_at) & (RequestQuota.count < limit)),
        ).returning(RequestQuota.count))
        if admitted is None:
            await db.rollback()
            raise HTTPException(429, "Слишком много запросов, попробуйте позже", headers={
                "Retry-After": str(max(1, ceil(expires_at - time()))),
            })
    await db.commit()


async def prune_quotas(db: AsyncSession) -> None:
    await db.execute(delete(RequestQuota).where(RequestQuota.expires_at <= int(time())))
    await db.commit()


async def limit_login(db: AsyncSession, request: Request, scope: str, login: str) -> None:
    settings = get_settings()
    ip = request.client.host if request.client else "unknown"
    normalized = login.strip().casefold()
    await enforce_quota(db, scope, 600, [
        (f"ip:{ip}", settings.login_ip_limit),
        (f"login:{ip}:{normalized}", settings.login_pair_limit),
    ])
