"""Objetivos diarios de un usuario (kcal, macros, agua): una única fuente de verdad.

Antes había cuatro copias (`/calc/targets`, el motor de dietas, iafood y el chat) y solo la primera
usaba el TDEE adaptativo; las demás calculaban siempre con Mifflin-St Jeor y la actividad declarada,
así que el plan generado podía partir de un objetivo distinto del que ve el usuario en su perfil.
Ahora todas pasan por `resolve_targets`, que además respeta la fórmula de metabolismo basal que el
usuario eligió (`profile.bmr_formula`).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from myfood.db.models import BodyMeasurement, Profile
from myfood.domain import formulas, tdee
from myfood.domain.diet_engine import DayTargets
from myfood.errors import AppError


@dataclass
class ResolvedTargets:
    profile: Profile
    weight_kg: float
    bmr: float
    bmr_formula: str
    tdee: float
    source: str  # "formula" | "adaptive_tdee"
    kcal: float
    protein_g: float
    fat_g: float
    carbs_g: float
    water_ml: int
    warnings: list[str] = field(default_factory=list)

    @property
    def safety_floor_kcal(self) -> float:
        """Suelo de seguridad calórico (R6): nunca se propone menos que esto."""
        return max(self.bmr, 1200 if self.profile.sex == "female" else 1500)

    @property
    def min_fat_g(self) -> float:
        """Mínimo hormonal de grasa."""
        return self.weight_kg * 0.5

    def day_targets(self) -> DayTargets:
        return DayTargets(
            kcal=round(self.kcal, 1),
            protein_g=round(self.protein_g, 1),
            fat_g=round(self.fat_g, 1),
            carbs_g=round(self.carbs_g, 1),
        )


def age_years(birth_date: date, today: date | None = None) -> float:
    return ((today or date.today()) - birth_date).days / 365.25


async def require_complete_profile(
    session: AsyncSession, user_id: UUID, *, action: str = "calcular tus objetivos"
) -> Profile:
    profile = await session.get(Profile, user_id)
    if (
        profile is None
        or profile.sex is None
        or profile.birth_date is None
        or profile.height_cm is None
    ):
        raise AppError(
            "PROFILE_INCOMPLETE",
            f"Completa sexo, fecha de nacimiento y altura en tu perfil antes de {action}.",
            status_code=422,
        )
    return profile


async def latest_measurement(
    session: AsyncSession, user_id: UUID, *, field_name: str = "weight_kg"
) -> BodyMeasurement | None:
    """La medida más reciente que tenga informado `field_name`."""
    column = getattr(BodyMeasurement, field_name)
    return await session.scalar(
        select(BodyMeasurement)
        .where(BodyMeasurement.user_id == user_id, column.is_not(None))
        .order_by(BodyMeasurement.measured_on.desc())
        .limit(1)
    )


async def resolve_targets(
    session: AsyncSession, user_id: UUID, *, action: str = "calcular tus objetivos"
) -> ResolvedTargets:
    profile = await require_complete_profile(session, user_id, action=action)
    weight_row = await latest_measurement(session, user_id)
    if weight_row is None:
        raise AppError(
            "MISSING_MEASUREMENTS",
            f"Registra tu peso en Medidas antes de {action}.",
            status_code=422,
        )
    weight_kg = float(weight_row.weight_kg)
    height_cm = float(profile.height_cm)
    age = age_years(profile.birth_date)

    warnings: list[str] = []
    formula = profile.bmr_formula
    lean_mass = None
    if formula in ("katch", "cunningham"):
        fat_row = await latest_measurement(session, user_id, field_name="body_fat_pct")
        if fat_row is None:
            # Sin %grasa no hay masa magra: se calcula con Mifflin en vez de dejar sin objetivos.
            formula = "mifflin"
            warnings.append("BMR_FORMULA_FALLBACK_MIFFLIN")
        else:
            lean_mass = formulas.lean_mass_kg(weight_kg, float(fat_row.body_fat_pct))
    bmr = formulas.bmr_for(
        formula,
        sex=profile.sex,
        weight_kg=weight_kg,
        height_cm=height_cm,
        age_years=age,
        lean_mass=lean_mass,
    )

    estimate = await tdee.get_current_estimate(session, user_id)
    if estimate is not None and estimate.is_reliable:
        tdee_value = float(estimate.estimated_tdee)
        source = "adaptive_tdee"
    else:
        tdee_value = formulas.tdee(bmr, profile.activity_level)
        source = "formula"

    rate = float(profile.goal_rate_kg_week) if profile.goal_rate_kg_week is not None else 0.5
    kcal, kcal_warnings = formulas.calorie_target(tdee_value, profile.goal, rate, bmr, profile.sex)
    protein_g, fat_g, carbs_g, macro_warnings = formulas.macro_targets(
        weight_kg, kcal, profile.goal
    )
    return ResolvedTargets(
        profile=profile,
        weight_kg=weight_kg,
        bmr=bmr,
        bmr_formula=formula,
        tdee=tdee_value,
        source=source,
        kcal=kcal,
        protein_g=protein_g,
        fat_g=fat_g,
        carbs_g=carbs_g,
        water_ml=formulas.water_target_ml(profile.sex, weight_kg),
        warnings=[*warnings, *kcal_warnings, *macro_warnings],
    )
