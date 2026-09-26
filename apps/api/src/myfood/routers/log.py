from datetime import date, timedelta
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from myfood.ai.consent import require_ai_processing_consent
from myfood.ai.flows.plate_photo import request_plate_photo
from myfood.ai.flows.smart_log import request_smart_log
from myfood.ai.limits import load_limits
from myfood.ai.quota import QuotaExceeded, check_and_consume_quota, reset_at_iso
from myfood.ai.schemas import AiSessionOut, ai_session_to_out
from myfood.db.models import Food, FoodLog, FoodNutrient, Profile, Recipe, RecipeIngredient
from myfood.deps import get_current_user_id, get_db
from myfood.domain import micronutrients
from myfood.domain.targets import resolve_targets
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
    # `cooked`: `grams` es el peso ya cocinado; se divide por el factor de cocción del alimento y la
    # nutrición se calcula sobre el peso crudo equivalente (sección 21).
    weighed_as: Literal["raw", "cooked"] = "raw"
    # Id generado en el cliente para los registros hechos sin conexión: reenviar el mismo
    # registro (respuesta perdida, reintento de la cola) no lo duplica.
    client_id: UUID | None = None


class LogFoodOut(BaseModel):
    id: UUID
    log_date: date
    meal_type: str
    food_id: UUID | None
    recipe_id: UUID | None = None
    recipe_name: str | None = None
    # Nombre del alimento (solo en el registro de un día): evita una petición por cada línea.
    food_name: str | None = None
    grams: float
    weighed_as: str = "raw"
    entered_grams: float | None = None
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
        recipe_id=entry.recipe_id,
        grams=float(entry.grams),
        weighed_as=entry.weighed_as,
        entered_grams=float(entry.entered_grams) if entry.entered_grams is not None else None,
        entry_source=entry.entry_source,
        # Una entrada estimada por el chat no tiene alimento del catálogo: su nombre es lo
        # único que la identifica.
        food_name=entry.custom_name,
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


def _raw_grams(food: Food, grams: float, weighed_as: str) -> tuple[float, float | None]:
    """(peso crudo equivalente, lo que escribió el usuario si lo pesó cocinado)."""
    if weighed_as == "raw":
        return grams, None
    factor = float(food.cooking_yield_factor) if food.cooking_yield_factor else None
    if not factor:
        raise AppError(
            "NO_COOKING_YIELD",
            "Este alimento no tiene factor de cocción: indica el peso en crudo.",
            status_code=422,
        )
    return round(grams / factor, 2), grams


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
    food, nutrients = await _get_food_with_nutrients(session, body.food_id)
    raw_grams, entered_grams = _raw_grams(food, body.grams, body.weighed_as)

    entry = FoodLog(
        **({"id": body.client_id} if body.client_id is not None else {}),
        user_id=user_id,
        log_date=body.log_date,
        meal_type=body.meal_type,
        food_id=body.food_id,
        grams=raw_grams,
        weighed_as=body.weighed_as,
        entered_grams=entered_grams,
        kcal=_scale(nutrients.kcal_100g, raw_grams),
        protein_g=_scale(nutrients.protein_100g, raw_grams),
        fat_g=_scale(nutrients.fat_100g, raw_grams),
        carbs_g=_scale(nutrients.carbs_100g, raw_grams),
        micros=_scale_micros(nutrients.micros, raw_grams),
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
        food, nutrients = await _get_food_with_nutrients(session, entry.food_id)
        # Un registro pesado cocinado se sigue editando en cocinado.
        raw_grams, entered_grams = _raw_grams(food, body.grams, entry.weighed_as)
        entry.grams = raw_grams
        entry.entered_grams = entered_grams
        entry.kcal = _scale(nutrients.kcal_100g, raw_grams)
        entry.protein_g = _scale(nutrients.protein_100g, raw_grams)
        entry.fat_g = _scale(nutrients.fat_100g, raw_grams)
        entry.carbs_g = _scale(nutrients.carbs_100g, raw_grams)
        entry.micros = _scale_micros(nutrients.micros, raw_grams)

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


class LogRecipeIn(BaseModel):
    log_date: date
    meal_type: MealType
    recipe_id: UUID
    servings: float = Field(gt=0, le=20)
    client_id: UUID | None = None


@router.post("/recipe", status_code=201)
async def log_recipe(
    body: LogRecipeIn,
    user_id: UUID = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_db),
) -> LogFoodOut:
    """Registra raciones de una receta propia: el snapshot se calcula ahora, sumando sus
    ingredientes (R9), y no cambia si luego se edita la receta."""
    if body.client_id is not None:
        existing = await session.get(FoodLog, body.client_id)
        if existing is not None and existing.user_id == user_id:
            return _to_out(existing)
    recipe = await session.get(Recipe, body.recipe_id)
    if recipe is None or recipe.user_id != user_id:
        raise AppError("RECIPE_NOT_FOUND", "No existe esa receta.", status_code=404)

    rows = (
        await session.execute(
            select(RecipeIngredient.grams, FoodNutrient)
            .join(FoodNutrient, FoodNutrient.food_id == RecipeIngredient.food_id)
            .where(RecipeIngredient.recipe_id == recipe.id)
        )
    ).all()
    if not rows:
        raise AppError(
            "RECIPE_HAS_NO_INGREDIENTS", "Esa receta no tiene ingredientes.", status_code=422
        )
    share = body.servings / max(recipe.servings, 1)
    total_grams = sum(float(g) for g, _ in rows)
    micros: dict[str, float] = {}
    for grams, nutrients in rows:
        for key, value in _scale_micros(nutrients.micros, float(grams) * share).items():
            micros[key] = round(micros.get(key, 0.0) + value, 4)

    entry = FoodLog(
        **({"id": body.client_id} if body.client_id is not None else {}),
        user_id=user_id,
        log_date=body.log_date,
        meal_type=body.meal_type,
        recipe_id=recipe.id,
        grams=round(total_grams * share, 2),
        entry_source="recipe",
        kcal=round(sum(_scale(n.kcal_100g, float(g)) for g, n in rows) * share, 2),
        protein_g=round(sum(_scale(n.protein_100g, float(g)) for g, n in rows) * share, 2),
        fat_g=round(sum(_scale(n.fat_100g, float(g)) for g, n in rows) * share, 2),
        carbs_g=round(sum(_scale(n.carbs_100g, float(g)) for g, n in rows) * share, 2),
        micros=micros,
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
    out = _to_out(entry)
    out.recipe_name = recipe.name
    return out


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
    recipe_ids = {e.recipe_id for e in entries if e.recipe_id is not None}
    recipe_names: dict[UUID, str] = {}
    if recipe_ids:
        recipe_names = {
            r.id: r.name
            for r in await session.scalars(select(Recipe).where(Recipe.id.in_(recipe_ids)))
        }
    food_ids = {e.food_id for e in entries if e.food_id is not None}
    food_names: dict[UUID, str] = {}
    if food_ids:
        food_names = {
            # En una lista manda el nombre corto: «Huevo, entero, crudo, congelado, sal…» se
            # lee truncado y no dice nada. El de la fuente sigue en la ficha del alimento.
            f.id: f.name_short or f.name_es
            for f in await session.scalars(select(Food).where(Food.id.in_(food_ids)))
        }
    out = []
    for entry in entries:
        item = _to_out(entry)
        item.recipe_name = recipe_names.get(entry.recipe_id) if entry.recipe_id else None
        item.food_name = (
            food_names.get(entry.food_id) if entry.food_id else entry.custom_name
        )
        out.append(item)
    return LogDayOut(date=date, food=out, totals=totals)


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



class WeekDayOut(BaseModel):
    date: date
    kcal: float
    # `False` en los días que todavía no han llegado: no es lo mismo no haber comido que no
    # haber llegado a ese día.
    is_past: bool


class WeekOut(BaseModel):
    start: date
    end: date
    days: list[WeekDayOut]
    total_kcal: float
    # `None` mientras no haya perfil completo: la semana se puede mirar igual, solo que sin
    # nada contra lo que compararla.
    target_kcal: float | None
    remaining_kcal: float | None


@router.get("/week")
async def get_week_log(
    date_: date = Query(alias="date"),
    user_id: UUID = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_db),
) -> WeekOut:
    """La semana (lunes a domingo) que contiene esa fecha, con el objetivo de los siete días.

    Un objetivo diario convierte cada día en un aprobado o un suspenso, y eso es justo lo que
    R10 dice que no se haga: la investigación sobre apps de dieta encuentra que competir
    consigo mismo día a día empuja a comer cada vez menos. En una semana, un domingo alto se
    compensa con el lunes y no hay nada que suspender.
    """
    start = date_ - timedelta(days=date_.weekday())
    end = start + timedelta(days=6)
    rows = (
        await session.execute(
            select(FoodLog.log_date, func.sum(FoodLog.kcal))
            .where(
                FoodLog.user_id == user_id,
                FoodLog.log_date >= start,
                FoodLog.log_date <= end,
            )
            .group_by(FoodLog.log_date)
        )
    ).all()
    by_day = {row[0]: float(row[1] or 0) for row in rows}
    today = date.today()
    days = [
        WeekDayOut(
            date=start + timedelta(days=i),
            kcal=round(by_day.get(start + timedelta(days=i), 0.0), 1),
            is_past=start + timedelta(days=i) <= today,
        )
        for i in range(7)
    ]
    total = round(sum(d.kcal for d in days), 1)

    try:
        targets = await resolve_targets(session, user_id)
    except AppError:
        # Sin perfil completo no hay objetivo, pero el total de la semana sigue valiendo.
        return WeekOut(
            start=start, end=end, days=days, total_kcal=total,
            target_kcal=None, remaining_kcal=None,
        )
    weekly = round(float(targets.day_targets().kcal) * 7, 1)
    return WeekOut(
        start=start,
        end=end,
        days=days,
        total_kcal=total,
        target_kcal=weekly,
        remaining_kcal=round(weekly - total, 1),
    )

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
    text: str = Field(min_length=1, max_length=1000)
    # Dónde acabaría lo que se apunte. Hace falta para la propuesta del respaldo web, que
    # se aprueba entera: sin esto se apuntaría en «hoy, comida» aunque el usuario estuviera
    # registrando la cena de ayer.
    log_date: date | None = None
    meal_type: MealType | None = None


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

    ai_session = await request_smart_log(
        session,
        user_id,
        text=body.text,
        log_date=(body.log_date or date.today()).isoformat(),
        meal_type=body.meal_type or "lunch",
    )
    return ai_session_to_out(ai_session)


@router.post("/photo", status_code=202)
async def create_plate_photo_request(
    image: UploadFile = File(...),
    log_date: date = Form(...),
    meal_type: MealType = Form(...),
    user_id: UUID = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_db),
) -> AiSessionOut:
    """Foto del plato → alimentos propuestos. Hermano de `/smart`: no guarda nada, el
    resultado llega por `GET /ai/sessions/{id}` (mismo polling que el resto de iafood) y el
    usuario revisa las cantidades y confirma con `POST /log/food` normal, uno a uno.

    La foto se procesa (sin EXIF, a 1024 px) antes de tocar el disco y se borra en cuanto el
    worker termina con ella: lo que se ha pedido es registrar una comida, no guardar una foto.
    """
    await require_ai_processing_consent(session, user_id)
    limits = load_limits()
    try:
        await check_and_consume_quota(
            user_id,
            scope="plate_photo",
            per_profile_limit=limits.plate_photo_per_profile_daily,
        )
    except QuotaExceeded as exc:
        raise AppError(
            exc.code, exc.message, status_code=429, details={"reset_at": reset_at_iso()}
        ) from exc

    image_bytes = await image.read()
    ai_session = await request_plate_photo(
        session,
        user_id,
        image_bytes=image_bytes,
        content_type=image.content_type or "",
        log_date=log_date.isoformat(),
        meal_type=meal_type,
    )
    return ai_session_to_out(ai_session)
