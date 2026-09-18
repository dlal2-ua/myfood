from datetime import date
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from myfood.db.models import BodyMeasurement, Profile
from myfood.deps import get_current_user_id, get_db
from myfood.domain import formulas, tdee
from myfood.errors import AppError

router = APIRouter(prefix="/calc", tags=["calc"])


def _age_years(birth_date: date) -> float:
    today = date.today()
    days = (today - birth_date).days
    return days / 365.25


async def _require_complete_profile(session: AsyncSession, user_id: UUID) -> Profile:
    profile = await session.get(Profile, user_id)
    incomplete = (
        profile is None
        or profile.sex is None
        or profile.birth_date is None
        or profile.height_cm is None
    )
    if incomplete:
        raise AppError(
            "PROFILE_INCOMPLETE",
            "Completa sexo, fecha de nacimiento y altura en tu perfil antes de calcular.",
            status_code=422,
        )
    return profile


async def _latest_measurement(session: AsyncSession, user_id: UUID) -> BodyMeasurement | None:
    stmt = (
        select(BodyMeasurement)
        .where(BodyMeasurement.user_id == user_id)
        .order_by(BodyMeasurement.measured_on.desc())
        .limit(1)
    )
    return await session.scalar(stmt)


class BmrRequest(BaseModel):
    formula: Literal["mifflin", "katch", "cunningham"] | None = None


class BmrResponse(BaseModel):
    bmr: float
    tdee: float
    formula_used: str


@router.post("/bmr")
async def calc_bmr(
    body: BmrRequest,
    user_id: UUID = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_db),
) -> BmrResponse:
    profile = await _require_complete_profile(session, user_id)
    measurement = await _latest_measurement(session, user_id)
    if measurement is None or measurement.weight_kg is None:
        raise AppError(
            "MISSING_MEASUREMENTS",
            "Registra tu peso en Medidas antes de calcular el metabolismo basal.",
            status_code=422,
        )

    formula_used = body.formula or profile.bmr_formula
    weight_kg = float(measurement.weight_kg)
    height_cm = float(profile.height_cm)
    age_years = _age_years(profile.birth_date)

    if formula_used == "mifflin":
        bmr = formulas.bmr_mifflin(profile.sex, weight_kg, height_cm, age_years)
    else:
        if measurement.body_fat_pct is None:
            raise AppError(
                "MISSING_MEASUREMENTS",
                "Este método necesita tu %grasa corporal más reciente en Medidas.",
                status_code=422,
            )
        lean = formulas.lean_mass_kg(weight_kg, float(measurement.body_fat_pct))
        bmr = (
            formulas.bmr_katch(lean) if formula_used == "katch" else formulas.bmr_cunningham(lean)
        )

    return BmrResponse(
        bmr=round(bmr, 1),
        tdee=round(formulas.tdee(bmr, profile.activity_level), 1),
        formula_used=formula_used,
    )


class BodyFatRequest(BaseModel):
    method: Literal["navy"] = "navy"
    sex: Literal["male", "female"] | None = None
    height_cm: float = Field(gt=0, le=272)
    neck_cm: float = Field(gt=0)
    waist_cm: float = Field(gt=0)
    hip_cm: float | None = Field(default=None, gt=0)
    weight_kg: float | None = Field(default=None, gt=0, le=500)


class BodyFatResponse(BaseModel):
    body_fat_pct: float
    lean_mass_kg: float | None
    ffmi: float | None
    warnings: list[str]


@router.post("/body-fat")
async def calc_body_fat(
    body: BodyFatRequest,
    user_id: UUID = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_db),
) -> BodyFatResponse:
    sex = body.sex
    weight_kg = body.weight_kg
    if sex is None or weight_kg is None:
        profile = await session.get(Profile, user_id)
        measurement = await _latest_measurement(session, user_id)
        sex = sex or (profile.sex if profile else None)
        weight_kg = weight_kg or (
            float(measurement.weight_kg) if measurement and measurement.weight_kg else None
        )

    if sex is None:
        raise AppError(
            "PROFILE_INCOMPLETE", "Indica el sexo o complétalo en tu perfil.", status_code=422
        )
    if sex == "female" and body.hip_cm is None:
        raise AppError(
            "MISSING_HIP_MEASUREMENT",
            "El método US Navy en mujeres requiere el contorno de cadera.",
            status_code=422,
        )

    pct, warnings = formulas.body_fat_navy(
        sex, body.height_cm, body.neck_cm, body.waist_cm, body.hip_cm
    )

    lean_mass_kg = None
    ffmi_value = None
    if weight_kg is not None:
        lean_mass_kg = formulas.lean_mass_kg(weight_kg, pct)
        ffmi_value = formulas.ffmi(lean_mass_kg, body.height_cm)
    else:
        warnings = [*warnings, "MISSING_WEIGHT_FOR_LEAN_MASS"]

    return BodyFatResponse(
        body_fat_pct=round(pct, 1),
        lean_mass_kg=round(lean_mass_kg, 1) if lean_mass_kg is not None else None,
        ffmi=round(ffmi_value, 1) if ffmi_value is not None else None,
        warnings=warnings,
    )


class TargetsResponse(BaseModel):
    kcal: float
    protein_g: float
    fat_g: float
    carbs_g: float
    water_ml: int
    source: Literal["formula", "adaptive_tdee"]
    warnings: list[str]


@router.get("/targets")
async def get_targets(
    user_id: UUID = Depends(get_current_user_id), session: AsyncSession = Depends(get_db)
) -> TargetsResponse:
    profile = await _require_complete_profile(session, user_id)
    measurement = await _latest_measurement(session, user_id)
    if measurement is None or measurement.weight_kg is None:
        raise AppError(
            "MISSING_MEASUREMENTS",
            "Registra tu peso en Medidas antes de calcular tus objetivos.",
            status_code=422,
        )

    weight_kg = float(measurement.weight_kg)
    height_cm = float(profile.height_cm)
    age_years = _age_years(profile.birth_date)

    bmr = formulas.bmr_mifflin(profile.sex, weight_kg, height_cm, age_years)

    estimate = await tdee.get_current_estimate(session, user_id)
    if estimate is not None and estimate.is_reliable:
        tdee_value = float(estimate.estimated_tdee)
        source: Literal["formula", "adaptive_tdee"] = "adaptive_tdee"
    else:
        tdee_value = formulas.tdee(bmr, profile.activity_level)
        source = "formula"

    rate = float(profile.goal_rate_kg_week) if profile.goal_rate_kg_week is not None else 0.5
    kcal, kcal_warnings = formulas.calorie_target(tdee_value, profile.goal, rate, bmr, profile.sex)
    protein_g, fat_g, carbs_g, macro_warnings = formulas.macro_targets(
        weight_kg, kcal, profile.goal
    )
    water_ml = formulas.water_target_ml(profile.sex, weight_kg)

    return TargetsResponse(
        kcal=round(kcal, 1),
        protein_g=round(protein_g, 1),
        fat_g=round(fat_g, 1),
        carbs_g=round(carbs_g, 1),
        water_ml=water_ml,
        source=source,
        warnings=[*kcal_warnings, *macro_warnings],
    )
