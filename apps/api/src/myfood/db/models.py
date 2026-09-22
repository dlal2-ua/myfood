"""Modelos ORM. Se añaden tabla a tabla a medida que cada fase los necesita
en código — el esquema completo (todas las tablas de la sección 6) ya existe
en la base de datos desde la migración 0001, sea cual sea la fase en curso.
"""

import uuid
from datetime import date, datetime, time

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    LargeBinary,
    Numeric,
    SmallInteger,
    String,
    Time,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
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
    # Tener cuenta y poder gastar la cuota de Claude son dos cosas distintas: esto lo decide
    # el administrador, porque es lo que cuesta dinero (migración 0019).
    ai_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    invited_with: Mapped[str | None] = mapped_column(String, nullable=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # 2FA (Fase 7): secreto TOTP cifrado en reposo (R4-adjacent — es una
    # credencial, mismo criterio que `ai_credentials.token_encrypted`), solo
    # activo cuando `totp_enabled` — permite regenerar el secreto sin
    # activarlo hasta confirmar un código real (`/auth/2fa/confirm`).
    totp_secret: Mapped[str | None] = mapped_column(EncryptedText, nullable=True)
    totp_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
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


HEALTH_FLAG_PREGNANT = "pregnant_or_nursing"
HEALTH_FLAG_CONDITION = "medical_condition"


class Profile(Base):
    __tablename__ = "profiles"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    # Categoría especial RGPD art. 9 (R4) — cifrados en reposo, ver db/types.py.
    sex: Mapped[str | None] = mapped_column(EncryptedText, nullable=True)
    birth_date: Mapped[object | None] = mapped_column(EncryptedDate, nullable=True)
    height_cm: Mapped[object | None] = mapped_column(EncryptedNumeric, nullable=True)
    # Declaraciones de salud (lista separada por comas, cifrada): 'pregnant_or_nursing',
    # 'medical_condition'. Bloquean la sugerencia de suplementos (sección 10.7).
    health_flags: Mapped[str | None] = mapped_column(EncryptedText, nullable=True)

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

    def has_health_flag(self, flag: str) -> bool:
        return flag in (self.health_flags or "").split(",")

    def set_health_flag(self, flag: str, value: bool) -> None:
        flags = {f for f in (self.health_flags or "").split(",") if f}
        flags.add(flag) if value else flags.discard(flag)
        self.health_flags = ",".join(sorted(flags)) or None


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


class Allergen(Base):
    __tablename__ = "allergens"

    code: Mapped[str] = mapped_column(String, primary_key=True)
    name_es: Mapped[str] = mapped_column(String, nullable=False)


class FoodAllergen(Base):
    __tablename__ = "food_allergens"

    food_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("foods.id", ondelete="CASCADE"), primary_key=True
    )
    allergen_code: Mapped[str] = mapped_column(
        String, ForeignKey("allergens.code"), primary_key=True
    )
    # 'declared' | 'trace' (OFF) | 'inferred' (genéricos, por palabras clave) —
    # migración 0012.
    origin: Mapped[str] = mapped_column(String, nullable=False, default="declared")


class FoodImage(Base):
    """Imagen de un alimento (sección 6.3/12). `remote_url` la registra el ETL; la API
    descarga la imagen la primera vez que se pide y rellena `local_path`/`bytes` (caché
    en disco con purga LRU por `last_access_at`, que conserva `remote_url`)."""

    __tablename__ = "food_images"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    food_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("foods.id", ondelete="CASCADE"), nullable=False
    )
    type: Mapped[str] = mapped_column(String, nullable=False)
    remote_url: Mapped[str | None] = mapped_column(String, nullable=True)
    local_path: Mapped[str | None] = mapped_column(String, nullable=True)
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source: Mapped[str] = mapped_column(String, nullable=False)
    license: Mapped[str | None] = mapped_column(String, nullable=True)
    attribution: Mapped[str | None] = mapped_column(String, nullable=True)
    last_access_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class UserRestriction(Base):
    __tablename__ = "user_restrictions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String, nullable=False)
    allergen_code: Mapped[str | None] = mapped_column(
        String, ForeignKey("allergens.code"), nullable=True
    )
    # Sin FK (ver migración 0001): `food_id` puede apuntar a cualquier alimento
    # del catálogo y no se declaró referencia en el esquema — la existencia se
    # valida en la capa de aplicación (routers/restrictions.py) en su lugar.
    food_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    note: Mapped[str | None] = mapped_column(String, nullable=True)


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
    # `grams` es siempre el peso crudo equivalente; `weighed_as` = cómo lo pesó el usuario y
    # `entered_grams` = lo que escribió (solo si lo pesó cocinado). Ver migración 0016.
    weighed_as: Mapped[str] = mapped_column(String, nullable=False, default="raw")
    entered_grams: Mapped[object | None] = mapped_column(Numeric(8, 2), nullable=True)
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
    # NULL en artículos manuales; con valor cuando el artículo viene de
    # `POST /shopping-list/from-plan/{plan_id}` (Fase 7).
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


class Supplement(Base):
    __tablename__ = "supplements"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String, nullable=False)
    type: Mapped[str] = mapped_column(String, nullable=False)
    dose_amount: Mapped[object] = mapped_column(Numeric(8, 2), nullable=False)
    dose_unit: Mapped[str] = mapped_column(String, nullable=False)
    doses_per_container: Mapped[int | None] = mapped_column(Integer, nullable=True)
    price_per_container: Mapped[object | None] = mapped_column(Numeric(10, 2), nullable=True)
    image_path: Mapped[str | None] = mapped_column(String, nullable=True)
    notes: Mapped[str | None] = mapped_column(String, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # Opcional (sección "Suplementación") — solo para el caso en que el
    # suplemento (p. ej. proteína en polvo) corresponda a un alimento real del
    # catálogo. Sin integración de macros en esta fase: se acepta y persiste,
    # nada más.
    food_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("foods.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SupplementSchedule(Base):
    __tablename__ = "supplement_schedules"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    supplement_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("supplements.id", ondelete="CASCADE"), nullable=False
    )
    time_of_day: Mapped[time] = mapped_column(Time, nullable=False)
    days_of_week: Mapped[list[int]] = mapped_column(
        ARRAY(SmallInteger), nullable=False, default=lambda: [1, 2, 3, 4, 5, 6, 7]
    )
    with_food: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class SupplementLog(Base):
    __tablename__ = "supplement_log"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    supplement_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("supplements.id", ondelete="CASCADE"), nullable=False
    )
    taken_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    log_date: Mapped[date] = mapped_column(Date, nullable=False)
    skipped: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class SupplementStock(Base):
    __tablename__ = "supplement_stock"

    supplement_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("supplements.id", ondelete="CASCADE"), primary_key=True
    )
    doses_remaining: Mapped[object] = mapped_column(Numeric(8, 2), nullable=False, default=0)
    last_restock_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class DietPlan(Base):
    __tablename__ = "diet_plans"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String, nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String, nullable=False, default="draft")
    target_kcal: Mapped[object] = mapped_column(Numeric(7, 1), nullable=False)
    target_protein_g: Mapped[object] = mapped_column(Numeric(7, 1), nullable=False)
    target_fat_g: Mapped[object] = mapped_column(Numeric(7, 1), nullable=False)
    target_carbs_g: Mapped[object] = mapped_column(Numeric(7, 1), nullable=False)
    generated_by: Mapped[str] = mapped_column(String, nullable=False, default="manual")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    days: Mapped[list["PlanDay"]] = relationship(
        back_populates="plan", order_by="PlanDay.day_index", cascade="all, delete-orphan"
    )


class PlanDay(Base):
    __tablename__ = "plan_days"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    plan_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("diet_plans.id", ondelete="CASCADE"), nullable=False
    )
    day_index: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    warning: Mapped[str | None] = mapped_column(String, nullable=True)
    is_optimal: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    plan: Mapped["DietPlan"] = relationship(back_populates="days")
    meals: Mapped[list["PlanMeal"]] = relationship(
        back_populates="plan_day", order_by="PlanMeal.sort_order", cascade="all, delete-orphan"
    )


class PlanMeal(Base):
    __tablename__ = "plan_meals"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    plan_day_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("plan_days.id", ondelete="CASCADE"), nullable=False
    )
    meal_type: Mapped[str] = mapped_column(String, nullable=False)
    sort_order: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)

    plan_day: Mapped["PlanDay"] = relationship(back_populates="meals")
    items: Mapped[list["PlanItem"]] = relationship(
        back_populates="plan_meal", cascade="all, delete-orphan"
    )


class PlanItem(Base):
    __tablename__ = "plan_items"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    plan_meal_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("plan_meals.id", ondelete="CASCADE"), nullable=False
    )
    food_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("foods.id"), nullable=True
    )
    # ON DELETE CASCADE (migración 0010): el CHECK food_id/recipe_id XOR no
    # deja poner NULL aquí si se borra la receta — el plan_item entero
    # desaparece con ella (batch cooking, Fase 7).
    recipe_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("recipes.id", ondelete="CASCADE"), nullable=True
    )
    grams: Mapped[object] = mapped_column(Numeric(8, 2), nullable=False)
    is_substitutable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    plan_meal: Mapped["PlanMeal"] = relationship(back_populates="items")
    alternatives: Mapped[list["PlanItemAlternative"]] = relationship(
        back_populates="plan_item",
        order_by="PlanItemAlternative.rank",
        cascade="all, delete-orphan",
    )


class PlanItemAlternative(Base):
    __tablename__ = "plan_item_alternatives"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    plan_item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("plan_items.id", ondelete="CASCADE"), nullable=False
    )
    food_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("foods.id"), nullable=False
    )
    grams: Mapped[object] = mapped_column(Numeric(8, 2), nullable=False)
    rank: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    distance: Mapped[object] = mapped_column(Numeric(8, 4), nullable=False)

    plan_item: Mapped["PlanItem"] = relationship(back_populates="alternatives")


class AiCredential(Base):
    """Fila única (`id=1`) con la credencial de iafood, cifrada con `ENCRYPTION_KEY`
    (sección 6.7/10.1). Sin `user_id`: no lleva RLS, se gestiona solo desde `/admin/*`
    con el rol de conexión `myfood_admin`."""

    __tablename__ = "ai_credentials"

    id: Mapped[int] = mapped_column(SmallInteger, primary_key=True, default=1)
    provider: Mapped[str] = mapped_column(String, nullable=False, default="anthropic")
    token_encrypted: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AiSession(Base):
    """Una llamada al Claude Agent SDK (sección 6.7/10). `request_payload` es
    el JSON YA anonimizado (R5) que se envió; nunca contiene datos
    identificativos. RLS propia (sección 22, tiene `user_id`)."""

    __tablename__ = "ai_sessions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="running")
    request_payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    response_payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    validation_errors: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    attempts: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1)
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AiProposal(Base):
    """Cambio propuesto por iafood pendiente de aprobación (R1/sección 10.6
    — nada se aplica solo). `payload` lleva todo lo necesario para
    materializar la propuesta si se aprueba (p. ej. `diet_plan_id` +
    estructura de un día para `scope='meal'`)."""

    __tablename__ = "ai_proposals"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    ai_session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ai_sessions.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    scope: Mapped[str] = mapped_column(String, nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    rationale: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String, nullable=False, default="pending")
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class FastingWindow(Base):
    """Ventana de ayuno intermitente (sección 6.6): abierta mientras `ended_at` es NULL."""

    __tablename__ = "fasting_windows"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    target_hours: Mapped[object] = mapped_column(Numeric(4, 1), nullable=False, default=16)


class TdeeEstimate(Base):
    """TDEE adaptativo semanal (sección 6.7 / Fase 7, `domain/tdee.py`).

    Una fila por `(user_id, week_start)` — se recalcula (upsert) cada vez que
    se pide dentro de la misma semana, no hay worker dedicado."""

    __tablename__ = "tdee_estimates"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    week_start: Mapped[date] = mapped_column(Date, nullable=False)
    weight_trend_kg: Mapped[object] = mapped_column(Numeric(6, 3), nullable=False)
    weight_change_kg: Mapped[object] = mapped_column(Numeric(6, 3), nullable=False)
    avg_intake_kcal: Mapped[object] = mapped_column(Numeric(8, 2), nullable=False)
    estimated_tdee: Mapped[object] = mapped_column(Numeric(8, 2), nullable=False)
    logging_days: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    is_reliable: Mapped[bool] = mapped_column(Boolean, nullable=False)


class Recipe(Base):
    """Sección 6.4 / 20. Sin columnas de nutrición propias a propósito: el
    desglose nutricional siempre sale de sumar `food_nutrients` de sus
    `RecipeIngredient` (R9 — nunca un valor guardado que pueda desincronizarse
    si cambian los ingredientes)."""

    __tablename__ = "recipes"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String, nullable=False)
    servings: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1)
    prep_minutes: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    instructions: Mapped[str | None] = mapped_column(String, nullable=True)
    food_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("foods.id", ondelete="SET NULL"), nullable=True
    )
    internal_ean: Mapped[str | None] = mapped_column(String, unique=True, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    ingredients: Mapped[list["RecipeIngredient"]] = relationship(
        back_populates="recipe", cascade="all, delete-orphan"
    )


class RecipeIngredient(Base):
    __tablename__ = "recipe_ingredients"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    recipe_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("recipes.id", ondelete="CASCADE"), nullable=False
    )
    food_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("foods.id"), nullable=False
    )
    grams: Mapped[object] = mapped_column(Numeric(8, 2), nullable=False)

    recipe: Mapped["Recipe"] = relationship(back_populates="ingredients")


class PantryItem(Base):
    """Despensa del usuario (sección 6.4 / Fase 7): lo que dice tener en
    casa. La lista de la compra generada desde un plan (`shopping_list.py`,
    `POST /shopping-list/from-plan/{plan_id}`) descuenta estas cantidades
    antes de proponer qué comprar."""

    __tablename__ = "pantry_items"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    food_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("foods.id"), nullable=False
    )
    quantity_g: Mapped[object] = mapped_column(Numeric(10, 2), nullable=False)
    expires_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Household(Base):
    """Hogar (Fase 7, "modo familia"): despensa y lista de la compra
    compartidas y visibles entre sus miembros (RLS ampliada, migración
    0011) — cada uno sigue siendo dueño solo de lo que añade él mismo."""

    __tablename__ = "households"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String, nullable=False)
    invite_code: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    created_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class HouseholdMember(Base):
    __tablename__ = "household_members"

    household_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("households.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ChatMessage(Base):
    """Historial del chat conversacional (Fase 8, sección 6.10). La tabla y
    su política RLS ya existen desde las migraciones 0001/0002 (se
    reservaron de antemano, igual que el valor `'chat_edit'` de
    `ai_sessions.kind`) — este modelo es lo único que faltaba. El audio de
    las notas de voz nunca se guarda (R2, sección 24): solo `content`, ya
    transcrito; `source='voice'` es metadato informativo, no una
    referencia a ningún fichero."""

    __tablename__ = "chat_messages"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[str] = mapped_column(String, nullable=False)
    content: Mapped[str] = mapped_column(String, nullable=False)
    source: Mapped[str] = mapped_column(String, nullable=False, default="text")
    ai_session_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ai_sessions.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class UserAchievement(Base):
    """Logro ya conseguido por un usuario (migración 0018). El cálculo sigue siendo
    determinista en `domain/gamification.py`; esta tabla solo recuerda CUÁNDO se consiguió,
    que es lo único que no se puede deducir de los datos, y si ya se avisó."""

    __tablename__ = "user_achievements"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    key: Mapped[str] = mapped_column(String, nullable=False)
    earned_on: Mapped[date] = mapped_column(Date, nullable=False)
    notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Invite(Base):
    """Código de invitación de un solo uso (migración 0019).

    La app está abierta a internet: registrarse exige un código que genera el administrador,
    mismo mecanismo que openGym. `used_by` lo quema — un código no sirve dos veces — y
    `revoked_at` lo anula antes de que nadie lo use."""

    __tablename__ = "invites"

    code: Mapped[str] = mapped_column(String, primary_key=True)
    note: Mapped[str | None] = mapped_column(String, nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    used_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
