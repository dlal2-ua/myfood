from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field, model_validator
from sqlalchemy.ext.asyncio import AsyncSession

from myfood.db.models import Profile
from myfood.deps import get_current_user_id, get_db
from myfood.domain import formulas
from myfood.domain.targets import (
    age_years,
    latest_measurement,
    require_complete_profile,
    resolve_targets,
)
from myfood.errors import AppError

router = APIRouter(prefix="/calc", tags=["calc"])


class BmrRequest(BaseModel):
    formula: Literal["mifflin", "katch", "cunningham", "harris"] | None = None


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
    profile = await require_complete_profile(session, user_id, action="calcular")
    measurement = await latest_measurement(session, user_id)
    if measurement is None:
        raise AppError(
            "MISSING_MEASUREMENTS",
            "Registra tu peso en Medidas antes de calcular el metabolismo basal.",
            status_code=422,
        )

    formula_used = body.formula or profile.bmr_formula
    weight_kg = float(measurement.weight_kg)
    lean_mass = None
    if formula_used in ("katch", "cunningham"):
        fat_row = await latest_measurement(session, user_id, field_name="body_fat_pct")
        if fat_row is None:
            raise AppError(
                "MISSING_MEASUREMENTS",
                "Este método necesita tu %grasa corporal más reciente en Medidas.",
                status_code=422,
            )
        lean_mass = formulas.lean_mass_kg(weight_kg, float(fat_row.body_fat_pct))
    bmr = formulas.bmr_for(
        formula_used,
        sex=profile.sex,
        weight_kg=weight_kg,
        height_cm=float(profile.height_cm),
        age_years=age_years(profile.birth_date),
        lean_mass=lean_mass,
    )

    return BmrResponse(
        bmr=round(bmr, 1),
        tdee=round(formulas.tdee(bmr, profile.activity_level), 1),
        formula_used=formula_used,
    )


BodyFatMethod = Literal["navy", "jackson3", "jackson7", "durnin", "deurenberg"]

_SKINFOLD_SITES = (
    "chest",
    "abdomen",
    "thigh",
    "triceps",
    "suprailiac",
    "subscapular",
    "midaxillary",
    "biceps",
)


class BodyFatRequest(BaseModel):
    method: BodyFatMethod = "navy"
    sex: Literal["male", "female"] | None = None
    age_years: float | None = Field(default=None, ge=10, le=110)
    height_cm: float | None = Field(default=None, gt=0, le=272)
    weight_kg: float | None = Field(default=None, gt=0, le=500)
    # US Navy: contornos en cm.
    neck_cm: float | None = Field(default=None, gt=0)
    waist_cm: float | None = Field(default=None, gt=0)
    hip_cm: float | None = Field(default=None, gt=0)
    # Pliegues cutáneos en mm (Jackson-Pollock y Durnin-Womersley).
    chest_mm: float | None = Field(default=None, gt=0, le=80)
    abdomen_mm: float | None = Field(default=None, gt=0, le=80)
    thigh_mm: float | None = Field(default=None, gt=0, le=80)
    triceps_mm: float | None = Field(default=None, gt=0, le=80)
    suprailiac_mm: float | None = Field(default=None, gt=0, le=80)
    subscapular_mm: float | None = Field(default=None, gt=0, le=80)
    midaxillary_mm: float | None = Field(default=None, gt=0, le=80)
    biceps_mm: float | None = Field(default=None, gt=0, le=80)

    @model_validator(mode="after")
    def _navy_needs_its_circumferences(self) -> "BodyFatRequest":
        if self.method == "navy" and (self.neck_cm is None or self.waist_cm is None):
            raise ValueError("El método US Navy necesita el contorno de cuello y de cintura.")
        return self

    def skinfolds(self) -> dict[str, float]:
        return {
            site: value
            for site in _SKINFOLD_SITES
            if (value := getattr(self, f"{site}_mm")) is not None
        }


class BodyFatResponse(BaseModel):
    method: BodyFatMethod
    body_fat_pct: float
    lean_mass_kg: float | None
    ffmi: float | None
    # IMC (no distingue grasa de músculo: la interfaz lo dice siempre) y cintura/altura (riesgo si
    # supera 0,5); solo si hay peso o contorno de cintura.
    bmi: float | None = None
    whtr: float | None = None
    warnings: list[str]


_REQUIRED_SITES = {
    "jackson7": formulas.JACKSON7_SITES,
    "durnin": formulas.DURNIN_SITES,
}


def _required_sites(method: str, sex: str) -> tuple[str, ...]:
    if method == "jackson3":
        return formulas.JACKSON3_SITES[sex]
    return _REQUIRED_SITES.get(method, ())


@router.post("/body-fat")
async def calc_body_fat(
    body: BodyFatRequest,
    user_id: UUID = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_db),
) -> BodyFatResponse:
    profile = await session.get(Profile, user_id)
    measurement = await latest_measurement(session, user_id)

    sex = body.sex or (profile.sex if profile else None)
    if sex is None:
        raise AppError(
            "PROFILE_INCOMPLETE", "Indica el sexo o complétalo en tu perfil.", status_code=422
        )
    profile_height = float(profile.height_cm) if profile and profile.height_cm else None
    height_cm = body.height_cm or profile_height
    if height_cm is None:
        raise AppError(
            "PROFILE_INCOMPLETE", "Indica la altura o complétala en tu perfil.", status_code=422
        )
    weight_kg = body.weight_kg or (float(measurement.weight_kg) if measurement else None)
    age = body.age_years or (
        age_years(profile.birth_date) if profile and profile.birth_date else None
    )

    if body.method == "navy":
        if sex == "female" and body.hip_cm is None:
            raise AppError(
                "MISSING_HIP_MEASUREMENT",
                "El método US Navy en mujeres requiere el contorno de cadera.",
                status_code=422,
            )
        pct, warnings = formulas.body_fat_navy(
            sex, height_cm, body.neck_cm, body.waist_cm, body.hip_cm
        )
    else:
        if age is None:
            raise AppError(
                "PROFILE_INCOMPLETE",
                "Este método necesita tu edad: indícala o completa la fecha de nacimiento.",
                status_code=422,
            )
        if body.method == "deurenberg":
            if weight_kg is None:
                raise AppError(
                    "MISSING_MEASUREMENTS",
                    "Este método necesita tu peso: indícalo o regístralo en Medidas.",
                    status_code=422,
                )
            pct, warnings = formulas.body_fat_deurenberg(
                sex, age, formulas.bmi(weight_kg, height_cm)
            )
        else:
            folds = body.skinfolds()
            missing = [s for s in _required_sites(body.method, sex) if s not in folds]
            if missing:
                raise AppError(
                    "MISSING_SKINFOLDS",
                    "Faltan pliegues para este método: " + ", ".join(f"{s}_mm" for s in missing),
                    status_code=422,
                    details={"missing": [f"{s}_mm" for s in missing]},
                )
            calculate = {
                "jackson3": formulas.body_fat_jackson3,
                "jackson7": formulas.body_fat_jackson7,
                "durnin": formulas.body_fat_durnin,
            }[body.method]
            pct, warnings = calculate(sex, age, folds)

    lean_mass_kg = None
    ffmi_value = None
    if weight_kg is not None:
        lean_mass_kg = formulas.lean_mass_kg(weight_kg, pct)
        ffmi_value = formulas.ffmi(lean_mass_kg, height_cm)
    else:
        warnings = [*warnings, "MISSING_WEIGHT_FOR_LEAN_MASS"]

    bmi_value = formulas.bmi(weight_kg, height_cm) if weight_kg is not None else None
    whtr_value = None
    if body.waist_cm is not None:
        whtr_value, whtr_warnings = formulas.whtr(body.waist_cm, height_cm)
        warnings = [*warnings, *whtr_warnings]

    return BodyFatResponse(
        method=body.method,
        body_fat_pct=round(pct, 1),
        lean_mass_kg=round(lean_mass_kg, 1) if lean_mass_kg is not None else None,
        ffmi=round(ffmi_value, 1) if ffmi_value is not None else None,
        bmi=round(bmi_value, 1) if bmi_value is not None else None,
        whtr=round(whtr_value, 2) if whtr_value is not None else None,
        warnings=warnings,
    )


class TargetsResponse(BaseModel):
    kcal: float
    protein_g: float
    fat_g: float
    carbs_g: float
    water_ml: int
    source: Literal["formula", "adaptive_tdee"]
    bmr_formula: str
    warnings: list[str]


@router.get("/targets")
async def get_targets(
    user_id: UUID = Depends(get_current_user_id), session: AsyncSession = Depends(get_db)
) -> TargetsResponse:
    resolved = await resolve_targets(session, user_id)
    return TargetsResponse(
        kcal=round(resolved.kcal, 1),
        protein_g=round(resolved.protein_g, 1),
        fat_g=round(resolved.fat_g, 1),
        carbs_g=round(resolved.carbs_g, 1),
        water_ml=resolved.water_ml,
        source=resolved.source,
        bmr_formula=resolved.bmr_formula,
        warnings=resolved.warnings,
    )
