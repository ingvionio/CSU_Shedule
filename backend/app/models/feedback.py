from datetime import datetime

from sqlalchemy import JSON, Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, SmallInteger, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin
from app.models.catalog import Group
from app.models.enums import EmailStatus, FeedbackStatus


class FeedbackRecipient(Base):
    """Адресат обращений: разработчики, методист, деканат.

    Папка в админке определяется `kind`. Адресатов одного вида может стать
    несколько (деканат по людям) — тогда обращение уйдёт первому активному
    по `sort_order`, пока не появится выбор по теме.
    """

    __tablename__ = "feedback_recipients"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String(16), index=True)
    title: Mapped[str] = mapped_column(String(120))
    # Куда дублировать обращения. Пусто — только в админку.
    emails: Mapped[list] = mapped_column(JSON, default=list)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    sort_order: Mapped[int] = mapped_column(SmallInteger, default=0)

    __table_args__ = (
        CheckConstraint("kind IN ('dev','methodist','deanery')", name="ck_feedback_recipients_kind"),
    )


class FeedbackMessage(Base, TimestampMixin):
    """Обращение студента.

    Пока у студента нет входа, автора узнаём по случайному токену устройства:
    храним только его хеш. После входа через Moodle обращения с токеном
    устройства привяжутся к пользователю.
    """

    __tablename__ = "feedback_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String(16))
    recipient_id: Mapped[int | None] = mapped_column(
        ForeignKey("feedback_recipients.id", ondelete="SET NULL"), nullable=True
    )
    text: Mapped[str] = mapped_column(Text)

    group_id: Mapped[int | None] = mapped_column(ForeignKey("groups.id", ondelete="SET NULL"), nullable=True)
    # Необязательные: без них обращение анонимное.
    author_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    contact: Mapped[str | None] = mapped_column(String(200), nullable=True)
    author_token_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    # Хеш IP — только для ограничения частоты.
    ip_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)

    status: Mapped[str] = mapped_column(String(16), default=FeedbackStatus.NEW.value)
    # Заметка для своих, студент её не видит.
    admin_note: Mapped[str | None] = mapped_column(String(1000), nullable=True)

    group: Mapped[Group | None] = relationship(lazy="joined")
    recipient: Mapped[FeedbackRecipient | None] = relationship(lazy="joined")
    replies: Mapped[list["FeedbackReply"]] = relationship(
        lazy="selectin", order_by="FeedbackReply.id", cascade="all, delete-orphan"
    )

    __table_args__ = (
        CheckConstraint("kind IN ('dev','methodist','deanery','unknown')", name="ck_feedback_messages_kind"),
        CheckConstraint(
            "status IN ('new','in_progress','answered','archived')", name="ck_feedback_messages_status"
        ),
        Index("ix_feedback_messages_folder", "kind", "status"),
    )


class FeedbackReply(Base):
    """Сообщение в переписке по обращению.

    Отдельная таблица, а не поле `answer`: так поместятся уточнения студента
    и ответы ссылкой на готовую статью (FAQ).
    """

    __tablename__ = "feedback_replies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    message_id: Mapped[int] = mapped_column(ForeignKey("feedback_messages.id", ondelete="CASCADE"), index=True)
    author_kind: Mapped[str] = mapped_column(String(16))
    author_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    text: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        CheckConstraint("author_kind IN ('staff','student')", name="ck_feedback_replies_author_kind"),
    )


class EmailOutbox(Base):
    """Очередь писем. Обращение сохраняется независимо от того, ушло ли письмо."""

    __tablename__ = "email_outbox"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    message_id: Mapped[int | None] = mapped_column(
        ForeignKey("feedback_messages.id", ondelete="CASCADE"), nullable=True, index=True
    )
    to_address: Mapped[str] = mapped_column(String(200))
    reply_to: Mapped[str | None] = mapped_column(String(200), nullable=True)
    subject: Mapped[str] = mapped_column(String(300))
    body: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), default=EmailStatus.PENDING.value, index=True)
    attempts: Mapped[int] = mapped_column(SmallInteger, default=0)
    last_error: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        CheckConstraint("status IN ('pending','sent','failed','skipped')", name="ck_email_outbox_status"),
    )
