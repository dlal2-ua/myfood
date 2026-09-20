from datetime import date
from decimal import Decimal
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from myfood.db.models import (
    HEALTH_FLAG_CONDITION,
    HEALTH_FLAG_PREGNANT,
    BodyMeasurement,
    Profile,
)
from myfood.deps import get_current_user_id, get_db
from myfood.routers.consents import require_health_data_consent

router = APIRouter(tags=["profile"])


class ProfileOut(BaseModel):
    sex: Literal["male", "female"] | None
    birth_date: date | None
    height_cm: float | None
    activity_level: str
    goal: str
    goal_rate_kg_week: float | None
    bmr_formula: str
    meals_per_day: int
    budget_eur_week: float | None
    max_cook_minutes: int | None
    diet_style: str | None
    # Declaraciones que desactivan la sugerencia de suplementos con IA.
    is_pregnant_or_nursing: bool = False
    has_medical_condition: bool = False


class ProfileUpdate(BaseModel):
    sex: Literal["male", "female"] | None = None
    birth_date: date | None = None
    height_cm: float | None = Field(default=None, gt=0, le=272)
    activity_level: Literal["sedentary", "light", "moderate", "active", "very_active"] | None = (
        None
    )
    goal: Literal["lose", "maintain", "gain"] | None = None
    goal_rate_kg_week: float | None = Field(default=None, ge=0, le=1.5)
    bmr_formula: Literal["mifflin", "katch", "cunningham", "harris"] | None = None
    meals_per_day: int | None = Field(default=None, ge=1, le=8)
    budget_eur_week: float | None = Field(default=None, ge=0)
    max_cook_minutes: int | None = Field(default=None, ge=0)
    diet_style: str | None = None
    is_pregnant_or_nursing: bool | None = None
    has_medical_condition: bool | None = None


async def _get_or_create_profile(session: AsyncSession, user_id: UUID) -> Profile:
    profile = await session.get(Profile, user_id)
    if profile is None:
        profile = Profile(user_id=user_id)
        session.add(profile)
        await session.flush()
    return profile


def _to_out(profile: Profile) -> ProfileOut:
    return ProfileOut(
        sex=profile.sex,
        birth_date=profile.birth_date,
        height_cm=float(profile.height_cm) if profile.height_cm is not None else None,
        activity_level=profile.activity_level,
        goal=profile.goal,
        goal_rate_kg_week=(
            float(profile.goal_rate_kg_week) if profile.goal_rate_kg_week is not None else None
        ),
        bmr_formula=profile.bmr_formula,
        meals_per_day=profile.meals_per_day,
        budget_eur_week=(
            float(profile.budget_eur_week) if profile.budget_eur_week is not None else None
        ),
        max_cook_minutes=profile.max_cook_minutes,
        diet_style=profile.diet_style,
        is_pregnant_or_nursing=profile.has_health_flag(HEALTH_FLAG_PREGNANT),
        has_medical_condition=profile.has_health_flag(HEALTH_FLAG_CONDITION),
    )


@router.get("/profile")
async def get_profile(
    user_id: UUID = Depends(get_current_user_id), session: AsyncSession = Depends(get_db)
) -> ProfileOut:
    profile = await _get_or_create_profile(session, user_id)
    await session.commit()
    return _to_out(profile)


@router.put("/profile", dependencies=[Depends(require_health_data_consent)])
async def update_profile(
    body: ProfileUpdate,
    user_id: UUID = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_db),
) -> ProfileOut:
    profile = await _get_or_create_profile(session, user_id)
    flag_fields = {
        "is_pregnant_or_nursing": HEALTH_FLAG_PREGNANT,
        "has_medical_condition": HEALTH_FLAG_CONDITION,
    }
    for field, value in body.model_dump(exclude_unset=True).items():
        if field in flag_fields:
            profile.set_health_flag(flag_fields[field], bool(value))
        else:
            setattr(profile, field, value)
    await session.commit()
    await session.refresh(profile)
    return _to_out(profile)


class MeasurementIn(BaseModel):
    measured_on: date
    weight_kg: float | None = Field(default=None, gt=0, le=500)
    body_fat_pct: float | None = Field(default=None, ge=0, le=100)
    bf_method: Literal["navy", "jackson3", "jackson7", "durnin", "bia", "manual"] | None = None
    neck_cm: float | None = Field(default=None, gt=0)
    waist_cm: float | None = Field(default=None, gt=0)
    hip_cm: float | None = Field(default=None, gt=0)
    chest_cm: float | None = Field(default=None, gt=0)
    arm_cm: float | None = Field(default=None, gt=0)
    thigh_cm: float | None = Field(default=None, gt=0)
    source: Literal["manual", "health_connect", "scale"] = "manual"


class MeasurementOut(MeasurementIn):
    id: UUID


def _measurement_to_out(m: BodyMeasurement) -> MeasurementOut:
    def _f(value: Decimal | None) -> float | None:
        return float(value) if value is not None else None

    return MeasurementOut(
        id=m.id,
        measured_on=m.measured_on,
        weight_kg=_f(m.weight_kg),
        body_fat_pct=_f(m.body_fat_pct),
        bf_method=m.bf_method,
        neck_cm=_f(m.neck_cm),
        waist_cm=_f(m.waist_cm),
        hip_cm=_f(m.hip_cm),
        chest_cm=_f(m.chest_cm),
        arm_cm=_f(m.arm_cm),
        thigh_cm=_f(m.thigh_cm),
        source=m.source,
    )


@router.get("/measurements")
async def list_measurements(
    date_from: date | None = None,
    date_to: date | None = None,
    user_id: UUID = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_db),
) -> list[MeasurementOut]:
    stmt = select(BodyMeasurement).where(BodyMeasurement.user_id == user_id)
    if date_from is not None:
        stmt = stmt.where(BodyMeasurement.measured_on >= date_from)
    if date_to is not None:
        stmt = stmt.where(BodyMeasurement.measured_on <= date_to)
    stmt = stmt.order_by(BodyMeasurement.measured_on.desc())
    rows = await session.scalars(stmt)
    return [_measurement_to_out(row) for row in rows]


@router.post(
    "/measurements", status_code=201, dependencies=[Depends(require_health_data_consent)]
)
async def upsert_measurement(
    body: MeasurementIn,
    user_id: UUID = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_db),
) -> MeasurementOut:
    existing = await session.scalar(
        select(BodyMeasurement).where(
            BodyMeasurement.user_id == user_id, BodyMeasurement.measured_on == body.measured_on
        )
    )
    if existing is None:
        existing = BodyMeasurement(user_id=user_id, measured_on=body.measured_on)
        session.add(existing)

    # Fusiona: los campos que no vienen (o vienen a `null`) no se tocan. Antes se
    # sobrescribía TODO, así que apuntar solo la cintura un día en que Health Connect
    # ya había escrito el peso borraba el peso.
    for field, value in body.model_dump(exclude={"measured_on"}, exclude_unset=True).items():
        if value is not None:
            setattr(existing, field, value)

    await session.commit()
    await session.refresh(existing)
    return _measurement_to_out(existing)
