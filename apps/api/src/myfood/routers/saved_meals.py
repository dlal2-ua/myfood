"""Comidas guardadas: un combo con nombre que se apunta de un toque (migración 0024).

Se guarda desde una comida ya apuntada, no rellenando un formulario: lo que se quiere repetir
es lo que ya te comiste, y así el snapshot nutricional que se guarda es exactamente el que se
registró (sección 6.5). Repetir una comida guardada dentro de un año tiene que apuntar lo
mismo aunque el catálogo haya cambiado de por medio.

Es también la respuesta a los platos compuestos que no están en el catálogo: «bocadillo de
sobrasada» no existe como alimento, pero guardado una vez pasa a ser una sola línea con sus
calorías y sus macros.
"""

from datetime import date
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from myfood.db.models import Food, FoodLog, SavedMeal, SavedMealItem
from myfood.deps import get_current_user_id, get_db
from myfood.errors import AppError

router = APIRouter(prefix="/saved-meals", tags=["saved-meals"])

MealType = Literal[
    "breakfast", "morning_snack", "lunch", "afternoon_snack", "dinner", "supper"
]

# Una comida con más líneas que esto no es una comida guardada: es un plan.
MAX_ITEMS = 30


class SavedMealItemOut(BaseModel):
    id: UUID
    food_id: UUID | None
    name: str
    grams: float
    kcal: float
    protein_g: float
    fat_g: float
    carbs_g: float
    # `True` cuando la línea no es un alimento del catálogo y sus números los puso el modelo.
    estimated: bool


class SavedMealOut(BaseModel):
    id: UUID
    name: str
    meal_type: str | None
    use_count: int
    items: list[SavedMealItemOut]
    totals: dict[str, float]


def _totals(items: list[SavedMealItemOut]) -> dict[str, float]:
    return {
        "kcal": round(sum(i.kcal for i in items), 1),
        "protein_g": round(sum(i.protein_g for i in items), 1),
        "fat_g": round(sum(i.fat_g for i in items), 1),
        "carbs_g": round(sum(i.carbs_g for i in items), 1),
    }


async def _to_out(session: AsyncSession, meal: SavedMeal) -> SavedMealOut:
    rows = (
        await session.scalars(
            select(SavedMealItem).where(SavedMealItem.saved_meal_id == meal.id)
        )
    ).all()
    # Los nombres del catálogo se leen en un solo viaje, no uno por línea.
    food_ids = [r.food_id for r in rows if r.food_id]
    names: dict[UUID, str] = {}
    if food_ids:
        names = {
            # El nombre corto, como en el diario: es una lista.
            f.id: f.name_short or f.name_es
            for f in await session.scalars(select(Food).where(Food.id.in_(food_ids)))
        }
    items = [
        SavedMealItemOut(
            id=r.id,
            food_id=r.food_id,
            name=(names.get(r.food_id) if r.food_id else r.custom_name) or "Alimento",
            grams=float(r.grams),
            kcal=float(r.kcal),
            protein_g=float(r.protein_g),
            fat_g=float(r.fat_g),
            carbs_g=float(r.carbs_g),
            estimated=r.food_id is None,
        )
        for r in rows
    ]
    return SavedMealOut(
        id=meal.id,
        name=meal.name,
        meal_type=meal.meal_type,
        use_count=meal.use_count,
        items=items,
        totals=_totals(items),
    )


class SaveFromDayIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    log_date: date
    meal_type: MealType


@router.post("", status_code=201)
async def save_meal_from_day(
    body: SaveFromDayIn,
    user_id: UUID = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_db),
) -> SavedMealOut:
    """Guarda una comida ya apuntada con un nombre, para repetirla luego.

    Copia el snapshot de cada entrada tal cual en vez de recalcularlo desde el catálogo: lo que
    se guarda es lo que el usuario comió y confirmó, no lo que el catálogo diga hoy."""
    entries = (
        await session.scalars(
            select(FoodLog).where(
                FoodLog.user_id == user_id,
                FoodLog.log_date == body.log_date,
                FoodLog.meal_type == body.meal_type,
            )
        )
    ).all()
    if not entries:
        raise AppError("EMPTY_MEAL", "Esa comida no tiene nada apuntado.", status_code=422)
    if len(entries) > MAX_ITEMS:
        raise AppError("TOO_MANY_ITEMS", "Son demasiadas líneas para una comida.", 422)

    name = " ".join(body.name.split())
    # Guardar con un nombre que ya existe lo reemplaza: dos «Mi desayuno» solo confunden.
    existing = await session.scalar(
        select(SavedMeal).where(
            SavedMeal.user_id == user_id, func.lower(SavedMeal.name) == name.lower()
        )
    )
    if existing is not None:
        await session.execute(
            delete(SavedMealItem).where(SavedMealItem.saved_meal_id == existing.id)
        )
        meal = existing
        meal.meal_type = body.meal_type
    else:
        meal = SavedMeal(user_id=user_id, name=name, meal_type=body.meal_type)
        session.add(meal)
        await session.flush()

    for entry in entries:
        session.add(
            SavedMealItem(
                saved_meal_id=meal.id,
                food_id=entry.food_id,
                custom_name=None if entry.food_id else (entry.custom_name or "Alimento"),
                grams=entry.grams,
                kcal=entry.kcal,
                protein_g=entry.protein_g,
                fat_g=entry.fat_g,
                carbs_g=entry.carbs_g,
                micros=entry.micros or {},
            )
        )
    await session.commit()
    await session.refresh(meal)
    return await _to_out(session, meal)


class SavedMealListOut(BaseModel):
    items: list[SavedMealOut]


@router.get("")
async def list_saved_meals(
    limit: int = 30,
    user_id: UUID = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_db),
) -> SavedMealListOut:
    """Lo que más repites, primero — es lo que se quiere tener a un toque."""
    meals = (
        await session.scalars(
            select(SavedMeal)
            .where(SavedMeal.user_id == user_id)
            .order_by(SavedMeal.use_count.desc(), SavedMeal.last_used_at.desc().nullslast())
            .limit(min(max(limit, 1), 100))
        )
    ).all()
    return SavedMealListOut(items=[await _to_out(session, m) for m in meals])


class LogSavedMealIn(BaseModel):
    log_date: date
    meal_type: MealType


@router.post("/{meal_id}/log", status_code=201)
async def log_saved_meal(
    meal_id: UUID,
    body: LogSavedMealIn,
    user_id: UUID = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_db),
) -> dict:
    """Apunta la comida guardada entera en el día y la comida que se pidan."""
    meal = await session.get(SavedMeal, meal_id)
    if meal is None or meal.user_id != user_id:
        raise AppError("SAVED_MEAL_NOT_FOUND", "No existe esa comida guardada.", status_code=404)

    items = (
        await session.scalars(
            select(SavedMealItem).where(SavedMealItem.saved_meal_id == meal.id)
        )
    ).all()
    for item in items:
        session.add(
            FoodLog(
                user_id=user_id,
                log_date=body.log_date,
                meal_type=body.meal_type,
                food_id=item.food_id,
                custom_name=item.custom_name if item.food_id is None else None,
                grams=item.grams,
                # `saved_meal` y no `manual`: en el histórico se distingue lo repetido de lo
                # buscado a mano, que es la mitad de la razón de tener esta función.
                entry_source="saved_meal",
                kcal=item.kcal,
                protein_g=item.protein_g,
                fat_g=item.fat_g,
                carbs_g=item.carbs_g,
                micros=item.micros or {},
            )
        )
    meal.use_count += 1
    meal.last_used_at = func.now()
    await session.commit()
    return {"logged": len(items)}


@router.delete("/{meal_id}", status_code=204)
async def delete_saved_meal(
    meal_id: UUID,
    user_id: UUID = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_db),
) -> None:
    meal = await session.get(SavedMeal, meal_id)
    if meal is None or meal.user_id != user_id:
        raise AppError("SAVED_MEAL_NOT_FOUND", "No existe esa comida guardada.", status_code=404)
    await session.delete(meal)
    await session.commit()
