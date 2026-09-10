"""Modelos ORM. Se añaden tabla a tabla a medida que cada fase los necesita
en código — el esquema completo (todas las tablas de la sección 6) ya existe
en la base de datos desde la migración 0001, sea cual sea la fase en curso.
"""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, SmallInteger, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from myfood.db.base import Base
from myfood.db.types import EncryptedDate, EncryptedNumeric, EncryptedText


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String, nullable=False)
    display_name: Mapped[str] = mapped_column(String, nullable=False)
    role: Mapped[str] = mapped_column(String, nullable=False, default="user")
    locale: Mapped[str] = mapped_column(String, nullable=False, default="es")
    timezone: Mapped[str] = mapped_column(String, nullable=False, default="Europe/Madrid")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    profile: Mapped["Profile"] = relationship(back_populates="user", uselist=False)


class Consent(Base):
    __tablename__ = "consents"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String, nullable=False)
    version: Mapped[str] = mapped_column(String, nullable=False)
    granted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Profile(Base):
    __tablename__ = "profiles"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    # Categoría especial RGPD art. 9 (R4) — cifrados en reposo, ver db/types.py.
    sex: Mapped[str | None] = mapped_column(EncryptedText, nullable=True)
    birth_date: Mapped[object | None] = mapped_column(EncryptedDate, nullable=True)
    height_cm: Mapped[object | None] = mapped_column(EncryptedNumeric, nullable=True)

    activity_level: Mapped[str] = mapped_column(String, nullable=False, default="moderate")
    goal: Mapped[str] = mapped_column(String, nullable=False, default="maintain")
    bmr_formula: Mapped[str] = mapped_column(String, nullable=False, default="mifflin")
    meals_per_day: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=4)
    diet_style: Mapped[str | None] = mapped_column(String, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    user: Mapped["User"] = relationship(back_populates="profile")
