"""Modelos ORM. Se añaden tabla a tabla a medida que cada fase los necesita
en código — el esquema completo (todas las tablas de la sección 6) ya existe
en la base de datos desde la migración 0001, sea cual sea la fase en curso.
"""

import uuid
from datetime import date, datetime, time

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Time,
    func,
)
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


class FoodLog(Base):
    __tablename__ = "food_log"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    logged_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    log_date: Mapped[date] = mapped_column(Date, nullable=False)
    meal_type: Mapped[str] = mapped_column(String, nullable=False)
    food_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("foods.id"), nullable=True
    )
    recipe_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    grams: Mapped[object] = mapped_column(Numeric(8, 2), nullable=False)
    entry_source: Mapped[str] = mapped_column(String, nullable=False, default="manual")
    # Snapshot nutricional congelado en el momento del registro (sección 6.5)
    # — si el catálogo cambia después, el histórico del usuario no cambia.
    kcal: Mapped[object] = mapped_column(Numeric(9, 2), nullable=False)
    protein_g: Mapped[object] = mapped_column(Numeric(9, 2), nullable=False)
    fat_g: Mapped[object] = mapped_column(Numeric(9, 2), nullable=False)
    carbs_g: Mapped[object] = mapped_column(Numeric(9, 2), nullable=False)
    micros: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)


class UserFavoriteFood(Base):
    __tablename__ = "user_favorite_foods"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    food_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("foods.id", ondelete="CASCADE"), nullable=True
    )
    # `recipes` no existe todavía como feature de producto (llega en una fase
    # posterior) — la columna ya vive en el esquema (migración 0001) pero los
    # favoritos solo usan food_id por ahora; recipe_id se deja sin exponer en
    # los endpoints/Pydantic models (código muerto intencionado).
    recipe_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    use_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ShoppingListItem(Base):
    __tablename__ = "shopping_list_items"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    food_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("foods.id"), nullable=True
    )
    free_text: Mapped[str | None] = mapped_column(String, nullable=True)
    quantity_g: Mapped[object | None] = mapped_column(Numeric(10, 2), nullable=True)
    category: Mapped[str | None] = mapped_column(String, nullable=True)
    is_checked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Reservado para el futuro feature de planes de comida (Fase 4) — sin uso
    # todavía: esta lista de la compra es manual y autónoma (no se genera a
    # partir de ningún plan).
    plan_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class WaterSettings(Base):
    __tablename__ = "water_settings"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    mode: Mapped[str] = mapped_column(String, nullable=False, default="auto")
    daily_target_ml: Mapped[int] = mapped_column(Integer, nullable=False, default=2500)
    containers: Mapped[list] = mapped_column(
        JSONB,
        nullable=False,
        default=lambda: [{"label": "Vaso", "ml": 200}, {"label": "Botella", "ml": 500}],
    )


class WaterLog(Base):
    __tablename__ = "water_log"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    logged_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    log_date: Mapped[date] = mapped_column(Date, nullable=False)
    ml: Mapped[int] = mapped_column(Integer, nullable=False)


class NotificationRule(Base):
    __tablename__ = "notification_rules"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String, nullable=False)
    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # Forma libre por `kind` (sección 9): para 'water', p.ej.
    # {"times": ["10:00", "13:00", "16:00", "19:00"]}; para 'supplement',
    # {"time": "09:00", "message": "Toca la creatina"}. No se modela como
    # columnas propias porque cada `kind` trae una forma distinta y añadir
    # más tipos de recordatorio no debe tocar el esquema.
    schedule: Mapped[dict] = mapped_column(JSONB, nullable=False)
    quiet_from: Mapped[time] = mapped_column(Time, nullable=False, default=time(23, 0))
    quiet_to: Mapped[time] = mapped_column(Time, nullable=False, default=time(8, 0))


class PushSubscription(Base):
    __tablename__ = "push_subscriptions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    endpoint: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    p256dh: Mapped[str] = mapped_column(String, nullable=False)
    auth: Mapped[str] = mapped_column(String, nullable=False)
    device: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
