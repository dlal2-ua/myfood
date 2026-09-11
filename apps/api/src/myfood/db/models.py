"""Modelos ORM. Se añaden tabla a tabla a medida que cada fase los necesita
en código — el esquema completo (todas las tablas de la sección 6) ya existe
en la base de datos desde la migración 0001, sea cual sea la fase en curso.
"""

import uuid
from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Numeric, SmallInteger, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
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
    goal_rate_kg_week: Mapped[object | None] = mapped_column(Numeric(3, 2), default=0.5)
    bmr_formula: Mapped[str] = mapped_column(String, nullable=False, default="mifflin")
    meals_per_day: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=4)
    budget_eur_week: Mapped[object | None] = mapped_column(Numeric(10, 2), nullable=True)
    max_cook_minutes: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    diet_style: Mapped[str | None] = mapped_column(String, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    user: Mapped["User"] = relationship(back_populates="profile")


class BodyMeasurement(Base):
    __tablename__ = "body_measurements"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    measured_on: Mapped[date] = mapped_column(Date, nullable=False)
    # Datos de salud (R4) — cifrados en reposo, ver db/types.py.
    weight_kg: Mapped[object | None] = mapped_column(EncryptedNumeric, nullable=True)
    body_fat_pct: Mapped[object | None] = mapped_column(EncryptedNumeric, nullable=True)
    neck_cm: Mapped[object | None] = mapped_column(EncryptedNumeric, nullable=True)
    waist_cm: Mapped[object | None] = mapped_column(EncryptedNumeric, nullable=True)
    hip_cm: Mapped[object | None] = mapped_column(EncryptedNumeric, nullable=True)
    chest_cm: Mapped[object | None] = mapped_column(EncryptedNumeric, nullable=True)
    arm_cm: Mapped[object | None] = mapped_column(EncryptedNumeric, nullable=True)
    thigh_cm: Mapped[object | None] = mapped_column(EncryptedNumeric, nullable=True)
    bf_method: Mapped[str | None] = mapped_column(String, nullable=True)
    source: Mapped[str] = mapped_column(String, nullable=False, default="manual")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Food(Base):
    __tablename__ = "foods"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    kind: Mapped[str] = mapped_column(String, nullable=False)
    source: Mapped[str] = mapped_column(String, nullable=False)
    source_id: Mapped[str | None] = mapped_column(String, nullable=True)
    license: Mapped[str] = mapped_column(String, nullable=False)
    attribution: Mapped[str | None] = mapped_column(String, nullable=True)
    barcode_ean: Mapped[str | None] = mapped_column(String, nullable=True)
    name_es: Mapped[str] = mapped_column(String, nullable=False)
    name_en: Mapped[str | None] = mapped_column(String, nullable=True)
    brand: Mapped[str | None] = mapped_column(String, nullable=True)
    category: Mapped[str | None] = mapped_column(String, nullable=True)
    serving_size_g: Mapped[object | None] = mapped_column(Numeric(8, 2), nullable=True)
    serving_label: Mapped[str | None] = mapped_column(String, nullable=True)
    quality_rank: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    nutriscore_grade: Mapped[str | None] = mapped_column(String, nullable=True)
    nova_group: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    ecoscore_grade: Mapped[str | None] = mapped_column(String, nullable=True)
    cooking_yield_factor: Mapped[object | None] = mapped_column(Numeric(4, 2), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    nutrients: Mapped["FoodNutrient"] = relationship(back_populates="food", uselist=False)


class FoodNutrient(Base):
    __tablename__ = "food_nutrients"

    food_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("foods.id", ondelete="CASCADE"), primary_key=True
    )
    kcal_100g: Mapped[object] = mapped_column(Numeric(10, 3), nullable=False)
    protein_100g: Mapped[object] = mapped_column(Numeric(10, 3), nullable=False, default=0)
    fat_100g: Mapped[object] = mapped_column(Numeric(10, 3), nullable=False, default=0)
    saturated_100g: Mapped[object | None] = mapped_column(Numeric(10, 3), nullable=True)
    carbs_100g: Mapped[object] = mapped_column(Numeric(10, 3), nullable=False, default=0)
    sugars_100g: Mapped[object | None] = mapped_column(Numeric(10, 3), nullable=True)
    fiber_100g: Mapped[object | None] = mapped_column(Numeric(10, 3), nullable=True)
    salt_100g: Mapped[object | None] = mapped_column(Numeric(10, 3), nullable=True)
    micros: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    food: Mapped["Food"] = relationship(back_populates="nutrients")
