from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base
from app.models.catalog import Group


class User(Base):
    """Студент с лёгким профилем: ФИО и группа, без пароля.

    Пользователь привязан к устройству: при регистрации фронт присылает
    случайный ключ устройства, бэкенд хранит его хеш. Повторная регистрация
    с тем же ключом находит того же пользователя (история прочтений
    сохраняется), а по одному ФИО чужой профиль получить нельзя.

    ПЕРСОНАЛЬНЫЕ ДАННЫЕ: `full_name` и `group_id`. Собираем только их.
    """

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    full_name: Mapped[str] = mapped_column(String(200))
    group_id: Mapped[int | None] = mapped_column(ForeignKey("groups.id", ondelete="SET NULL"), nullable=True, index=True)
    role: Mapped[str] = mapped_column(String(16), default="student")
    device_key_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, unique=True)
    # На будущее: вход через Moodle.
    moodle_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Хеш IP при регистрации — только для ограничения частоты.
    ip_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    group: Mapped[Group | None] = relationship(lazy="joined")

    __table_args__ = (CheckConstraint("role IN ('student')", name="ck_users_role"),)
