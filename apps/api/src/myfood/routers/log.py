from datetime import date
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from myfood.ai.consent import require_ai_processing_consent
from myfood.ai.flows.smart_log import request_smart_log
from myfood.ai.quota import QuotaExceeded, check_and_consume_quota, reset_at_iso
from myfood.ai.schemas import AiSessionOut, ai_session_to_out
from myfood.db.models import Food, FoodLog, FoodNutrient, Profile
from myfood.deps import get_current_user_id, get_db
from myfood.domain import micronutrients
from myfood.errors import AppError

router = APIRouter(prefix="/log", tags=["log"])

MealType = Literal[
    "breakfast", "morning_snack", "lunch", "afternoon_snack", "dinner", "supper"
]


def _scale(nutrient_100g, grams: float):
    return round(float(nutrient_100g or 0) * grams / 100, 2)


def _scale_micros(micros: dict, grams: float) -> dict:
    return {key: round(value * grams / 100, 4) for key, value in micros.items()}


class LogFoodIn(BaseModel):
    log_date: date
    meal_type: MealType
    food_id: UUID
    grams: float = Field(gt=0, le=5000)
    # Id generado en el cliente para los registros hechos sin conexión: reenviar el mismo
    # registro (respuesta perdida, reintento de la cola) no lo duplica.
    client_id: UUID | None = None


class LogFoodOut(BaseModel):
    id: UUID
    log_date: date
    meal_type: str
    food_id: UUID | None
    grams: float
    entry_source: str
    kcal: float
    protein_g: float
    fat_g: float
    carbs_g: float


def _to_out(entry: FoodLog) -> LogFoodOut:
    return LogFoodOut(
        id=entry.id,
        log_date=entry.log_date,
        meal_type=entry.meal_type,
        food_id=entry.food_id,
        grams=float(entry.grams),
        entry_source=entry.entry_source,
        kcal=float(entry.kcal),
        protein_g=float(entry.protein_g),
        fat_g=float(entry.fat_g),
        carbs_g=float(entry.carbs_g),
    )


async def _get_food_with_nutrients(
    session: AsyncSession, food_id: UUID
) -> tuple[Food, FoodNutrient]:
    food = await session.get(Food, food_id)
    nutrients = await session.get(FoodNutrient, food_id) if food else None
    if food is None or nutrients is None:
        raise AppError("FOOD_NOT_FOUND", "No existe ese alimento.", status_code=404)
    return food, nutrients


@router.post("/food", status_code=201)
async def log_food(
    body: LogFoodIn,
    user_id: UUID = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_db),
) -> LogFoodOut:
    if body.client_id is not None:
        existing = await session.get(FoodLog, body.client_id)
        if existing is not None and existing.user_id == user_id:
            return _to_out(existing)
    _food, nutrients = await _get_food_with_nutrients(session, body.food_id)

    entry = FoodLog(
        **({"id": body.client_id} if body.client_id is not None else {}),
        user_id=user_id,
        log_date=body.log_date,
        meal_type=body.meal_type,
        food_id=body.food_id,
        grams=body.grams,
        kcal=_scale(nutrients.kcal_100g, body.grams),
        protein_g=_scale(nutrients.protein_100g, body.grams),
        fat_g=_scale(nutrients.fat_100g, body.grams),
        carbs_g=_scale(nutrients.carbs_100g, body.grams),
        micros=_scale_micros(nutrients.micros, body.grams),
    )
    session.add(entry)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise AppError(
            "CLIENT_ID_CONFLICT", "Ese identificador de registro ya está en uso.", status_code=409
        ) from exc
    await session.refresh(entry)
    return _to_out(entry)


class LogFoodPatch(BaseModel):
    meal_type: MealType | None = None
    grams: float | None = Field(default=None, gt=0, le=5000)


@router.patch("/food/{entry_id}")
async def update_log_food(
    entry_id: UUID,
    body: LogFoodPatch,
    user_id: UUID = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_db),
) -> LogFoodOut:
    entry = await session.get(FoodLog, entry_id)
    if entry is None or entry.user_id != user_id:
        raise AppError("LOG_ENTRY_NOT_FOUND", "No existe ese registro.", status_code=404)

    if body.meal_type is not None:
        entry.meal_type = body.meal_type

    if body.grams is not None and entry.food_id is not None:
        _food, nutrients = await _get_food_with_nutrients(session, entry.food_id)
        entry.grams = body.grams
        entry.kcal = _scale(nutrients.kcal_100g, body.grams)
        entry.protein_g = _scale(nutrients.protein_100g, body.grams)
        entry.fat_g = _scale(nutrients.fat_100g, body.grams)
        entry.carbs_g = _scale(nutrients.carbs_100g, body.grams)
        entry.micros = _scale_micros(nutrients.micros, body.grams)

    await session.commit()
    await session.refresh(entry)
    return _to_out(entry)


@router.delete("/food/{entry_id}", status_code=204)
async def delete_log_food(
    entry_id: UUID,
    user_id: UUID = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_db),
) -> None:
    entry = await session.get(FoodLog, entry_id)
    if entry is None or entry.user_id != user_id:
        raise AppError("LOG_ENTRY_NOT_FOUND", "No existe ese registro.", status_code=404)
    await session.delete(entry)
    await session.commit()


class DayTotals(BaseModel):
    kcal: float
    protein_g: float
    fat_g: float
    carbs_g: float


class LogDayOut(BaseModel):
    date: date
    food: list[LogFoodOut]
    totals: DayTotals


@router.get("")
async def get_day_log(
    date: date,
    user_id: UUID = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_db),
) -> LogDayOut:
    entries = list(
        await session.scalars(
            select(FoodLog)
            .where(FoodLog.user_id == user_id, FoodLog.log_date == date)
            .order_by(FoodLog.logged_at)
        )
    )
    totals = DayTotals(
        kcal=round(sum(float(e.kcal) for e in entries), 2),
        protein_g=round(sum(float(e.protein_g) for e in entries), 2),
        fat_g=round(sum(float(e.fat_g) for e in entries), 2),
        carbs_g=round(sum(float(e.carbs_g) for e in entries), 2),
    )
    return LogDayOut(date=date, food=[_to_out(e) for e in entries], totals=totals)


class MicronutrientOut(BaseModel):
    key: str
    label: str
    amount: float
    unit: str
    reference: float
    pct_of_reference: float


class MicronutrientsDayOut(BaseModel):
    date: date
    nutrients: list[MicronutrientOut]


@router.get("/micronutrients")
async def get_day_micronutrients(
    date: date,
    user_id: UUID = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_db),
) -> MicronutrientsDayOut:
    """Seguimiento completo de micronutrientes (Fase 7, no solo macros):
    suma lo que ya llevan registrado los `food_log` del día (snapshot
    congelado al registrar, R9) y lo compara contra valores de referencia
    poblacionales (EFSA), ajustados por sexo cuando el perfil lo tiene."""
    entries = await session.scalars(
        select(FoodLog).where(FoodLog.user_id == user_id, FoodLog.log_date == date)
    )
    totals = micronutrients.sum_micros([e.micros for e in entries])

    profile = await session.get(Profile, user_id)
    reference = micronutrients.reference_for_sex(profile.sex if profile else None)

    nutrients = [
        MicronutrientOut(
            key=key,
            label=micronutrients.NUTRIENT_LABELS.get(key, key),
            amount=totals.get(key, 0.0),
            unit=key.rsplit("_", 1)[-1],
            reference=ref_value,
            pct_of_reference=round((totals.get(key, 0.0) / ref_value) * 100, 1)
            if ref_value
            else 0.0,
        )
        for key, ref_value in reference.items()
    ]
    return MicronutrientsDayOut(date=date, nutrients=nutrients)


@router.post("/copy-day", status_code=201)
async def copy_day(
    from_date: date,
    to_date: date,
    user_id: UUID = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_db),
) -> list[LogFoodOut]:
    if from_date == to_date:
        raise AppError(
            "SAME_DATE", "El día de origen y el de destino son el mismo.", status_code=422
        )
    source_entries = list(
        await session.scalars(
            select(FoodLog).where(FoodLog.user_id == user_id, FoodLog.log_date == from_date)
        )
    )
    copies = [
        FoodLog(
            user_id=user_id,
            log_date=to_date,
            meal_type=e.meal_type,
            food_id=e.food_id,
            recipe_id=e.recipe_id,
            grams=e.grams,
            entry_source="manual",
            kcal=e.kcal,
            protein_g=e.protein_g,
            fat_g=e.fat_g,
            carbs_g=e.carbs_g,
            micros=e.micros,
        )
        for e in source_entries
    ]
    session.add_all(copies)
    await session.commit()
    for c in copies:
        await session.refresh(c)
    return [_to_out(c) for c in copies]


class SmartLogIn(BaseModel):
    text: str = Field(min_length=1, max_length=500)


@router.post("/smart", status_code=202)
async def create_smart_log_request(
    body: SmartLogIn,
    user_id: UUID = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_db),
) -> AiSessionOut:
    """Registro por lenguaje natural, "Smart Log" (sección 10.8). No guarda
    nada todavía — el resultado (vía `GET /ai/sessions/{id}`, mismo patrón
    de polling que el resto de iafood) es una lista de alimentos
    propuestos; el usuario los revisa, ajusta gramos y confirma llamando a
    `POST /log/food` normal por cada uno."""
    await require_ai_processing_consent(session, user_id)
    try:
        await check_and_consume_quota(user_id, scope="smart_log")
    except QuotaExceeded as exc:
        raise AppError(
            exc.code, exc.message, status_code=429, details={"reset_at": reset_at_iso()}
        ) from exc

    ai_session = await request_smart_log(session, user_id, text=body.text)
    return ai_session_to_out(ai_session)
