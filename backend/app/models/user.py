from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base
from app.models.catalog import Group


class User(Base):
    """Студент: профиль с авторизацией через Moodle ИИТ ЧелГУ.

    Студент идентифицируется по учетной записи Moodle (moodle_id и moodle_username).
    Все устройства студента (телефон, ноутбук) объединяются под одним пользователем.
    Пароль хранится в зашифрованном виде (AES-256-GCM) для прозрачного автопродления
    MoodleSession и синхронизации дедлайнов.
    """

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    full_name: Mapped[str] = mapped_column(String(200))
    group_id: Mapped[int | None] = mapped_column(ForeignKey("groups.id", ondelete="SET NULL"), nullable=True, index=True)
    role: Mapped[str] = mapped_column(String(16), default="student")
    device_key_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)

    # Moodle интеграция
    moodle_id: Mapped[str | None] = mapped_column(String(64), nullable=True, unique=True, index=True)
    moodle_username: Mapped[str | None] = mapped_column(String(100), nullable=True, unique=True, index=True)
    moodle_encrypted_password: Mapped[str | None] = mapped_column(Text, nullable=True)
    moodle_session_cookie: Mapped[str | None] = mapped_column(Text, nullable=True)
    moodle_sesskey: Mapped[str | None] = mapped_column(String(64), nullable=True)
    moodle_session_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    moodle_auth_error: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")

    # Хеш IP при первой регистрации — для защиты от спама
    ip_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    group: Mapped[Group | None] = relationship(lazy="joined")

    __table_args__ = (CheckConstraint("role IN ('student')", name="ck_users_role"),)
