from sqlalchemy import BigInteger, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class AdminRevocation(Base):
    __tablename__ = "admin_revocations"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    revoked_at: Mapped[int] = mapped_column(BigInteger)
    expires_at: Mapped[int | None] = mapped_column(BigInteger, index=True)
