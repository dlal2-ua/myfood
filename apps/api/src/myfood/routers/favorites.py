"""Favoritos y quick-add (sección 6.8) — accesos directos a alimentos que el
usuario registra a menudo.

Diseño de `use_count` (documentado también en la PR): representa cuántas
veces un favorito se ha *usado* de verdad para registrar comida, no cuántas
veces se ha marcado con la estrella. Marcar/desmarcar (`POST`/`DELETE`
`/favorites`) es idempotente y no toca el contador — así un doble clic en la
estrella no infla el ranking de "más usados". El contador solo avanza a
través de `POST /favorites/{food_id}/use`, que el frontend llama justo antes
de usar el favorito para el quick-add al registro diario (`/log/food`). Esto
mantiene este router desacoplado de `routers/log.py`, que en paralelo está
siendo modificado por el trabajo de escaneo de código de barras.
"""

from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from myfood.db.models import Food, FoodNutrient, UserFavoriteFood
from myfood.deps import get_current_user_id, get_db
from myfood.errors import AppError

router = APIRouter(prefix="/favorites", tags=["favorites"])


async def _get_food(session: AsyncSession, food_id: UUID) -> Food:
    food = await session.get(Food, food_id)
    if food is None:
        raise AppError("FOOD_NOT_FOUND", "No existe ese alimento.", status_code=404)
    return food


async def _get_favorite(session: AsyncSession, user_id: UUID, food_id: UUID) -> UserFavoriteFood:
    stmt = select(UserFavoriteFood).where(
        UserFavoriteFood.user_id == user_id, UserFavoriteFood.food_id == food_id
    )
    favorite = await session.scalar(stmt)
    if favorite is None:
        raise AppError(
            "FAVORITE_NOT_FOUND", "Ese alimento no está en tus favoritos.", status_code=404
        )
    return favorite


class FavoriteIn(BaseModel):
    food_id: UUID


class FavoriteOut(BaseModel):
    id: UUID
    food_id: UUID
    name_es: str
    brand: str | None
    kcal_100g: float | None
    use_count: int
    last_used_at: str | None


def _to_out(favorite: UserFavoriteFood, name_es: str, brand: str | None, kcal_100g) -> FavoriteOut:
    return FavoriteOut(
        id=favorite.id,
        food_id=favorite.food_id,
        name_es=name_es,
        brand=brand,
        kcal_100g=float(kcal_100g) if kcal_100g is not None else None,
        use_count=favorite.use_count,
        last_used_at=favorite.last_used_at.isoformat() if favorite.last_used_at else None,
    )


@router.post("", status_code=201)
async def add_favorite(
    body: FavoriteIn,
    user_id: UUID = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_db),
) -> FavoriteOut:
    food = await _get_food(session, body.food_id)

    # Idempotente frente a la restricción UNIQUE (user_id, food_id, recipe_id):
    # si ya estaba en favoritos, no es un error — simplemente se devuelve tal
    # cual (marcar la estrella dos veces no debe inflar use_count, ver
    # docstring del módulo).
    existing = await session.scalar(
        select(UserFavoriteFood).where(
            UserFavoriteFood.user_id == user_id, UserFavoriteFood.food_id == body.food_id
        )
    )
    if existing is not None:
        nutrients = await session.get(FoodNutrient, body.food_id)
        kcal_100g = nutrients.kcal_100g if nutrients else None
        return _to_out(existing, food.name_es, food.brand, kcal_100g)

    favorite = UserFavoriteFood(user_id=user_id, food_id=body.food_id)
    session.add(favorite)
    try:
        await session.commit()
    except IntegrityError:
        # Carrera con otra petición concurrente que creó el mismo favorito
        # entre el SELECT y el INSERT — se recupera la fila ya existente.
        await session.rollback()
        favorite = await _get_favorite(session, user_id, body.food_id)
    else:
        await session.refresh(favorite)

    nutrients = await session.get(FoodNutrient, body.food_id)
    return _to_out(favorite, food.name_es, food.brand, nutrients.kcal_100g if nutrients else None)


@router.delete("/{food_id}", status_code=204)
async def remove_favorite(
    food_id: UUID,
    user_id: UUID = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_db),
) -> None:
    favorite = await _get_favorite(session, user_id, food_id)
    await session.delete(favorite)
    await session.commit()


class FavoriteListOut(BaseModel):
    items: list[FavoriteOut]


@router.get("")
async def list_favorites(
    limit: int = Query(default=10, ge=1, le=100),
    user_id: UUID = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_db),
) -> FavoriteListOut:
    stmt = (
        select(UserFavoriteFood, Food.name_es, Food.brand, FoodNutrient.kcal_100g)
        .join(Food, Food.id == UserFavoriteFood.food_id)
        .outerjoin(FoodNutrient, FoodNutrient.food_id == Food.id)
        .where(UserFavoriteFood.user_id == user_id)
        .order_by(UserFavoriteFood.use_count.desc(), UserFavoriteFood.created_at.desc())
        .limit(limit)
    )
    rows = (await session.execute(stmt)).all()
    return FavoriteListOut(
        items=[
            _to_out(favorite, name_es, brand, kcal_100g)
            for favorite, name_es, brand, kcal_100g in rows
        ]
    )


@router.post("/{food_id}/use", status_code=200)
async def use_favorite(
    food_id: UUID,
    user_id: UUID = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_db),
) -> FavoriteOut:
    """Registra que el favorito se ha usado (p. ej. justo antes del quick-add
    al registro diario) — incrementa `use_count` y actualiza `last_used_at`."""
    favorite = await _get_favorite(session, user_id, food_id)
    favorite.use_count += 1
    favorite.last_used_at = datetime.now(UTC)
    await session.commit()
    await session.refresh(favorite)

    food = await _get_food(session, food_id)
    nutrients = await session.get(FoodNutrient, food_id)
    return _to_out(favorite, food.name_es, food.brand, nutrients.kcal_100g if nutrients else None)
