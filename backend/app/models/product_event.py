from datetime import datetime
from typing import Any

from sqlalchemy import JSON, BigInteger, DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class ProductEvent(Base):
    """Событие для статистики ЛК продукта: что и когда сделал пользователь или устройство.

    Содержимое (тексты, логины, пароли) сюда не пишется — только имя события.
    """

    __tablename__ = "product_events"
    __table_args__ = (
        Index("ix_product_events_name_occurred_at", "name", "occurred_at"),
        Index("ix_product_events_user_id_occurred_at", "user_id", "occurred_at"),
    )

    # BigInteger в SQLite не автоинкрементится — там обычный Integer.
    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    name: Mapped[str] = mapped_column(String(64))
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    device_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    platform: Mapped[str | None] = mapped_column(String(8), nullable=True)
    app_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    props: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
