from datetime import datetime

from sqlalchemy import JSON, CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base
from app.models.user import User


class Message(Base):
    """Сообщение методиста студентам.

    Адресация (`target`) хранится как есть, а получатели материализуются
    в `message_recipients` в момент отправки. Удаление мягкое: отметки
    «Ознакомлен» — подтверждение, их нельзя терять вместе с сообщением.
    """

    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text)
    importance: Mapped[str] = mapped_column(String(8), default="normal")
    # {"type": "all" | "course" | "direction" | "group" | "students", "courses": [...], ...}
    target: Mapped[dict] = mapped_column(JSON)
    # Логин админа: админ живёт в настройках, а не в таблице users.
    created_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    last_reminded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        CheckConstraint("importance IN ('low','normal','high')", name="ck_messages_importance"),
    )


class MessageRecipient(Base):
    """Получатель сообщения: снимок на момент отправки и отметки прочтения.

    Прочитано (`read_at`) и ознакомлен (`acknowledged_at`) — разные события:
    второе — явное нажатие кнопки у важных сообщений.
    """

    __tablename__ = "message_recipients"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    message_id: Mapped[int] = mapped_column(ForeignKey("messages.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    # Группа студента на момент отправки.
    group_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reminded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    message: Mapped[Message] = relationship(lazy="joined")
    user: Mapped[User] = relationship(lazy="joined")

    __table_args__ = (
        UniqueConstraint("message_id", "user_id", name="uq_message_recipients_message_user"),
        Index("ix_message_recipients_user_read", "user_id", "read_at"),
    )
