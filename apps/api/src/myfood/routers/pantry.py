"""Despensa del usuario (sección 6.4, Fase 7): lo que dice tener en casa.

CRUD simple, mismo estilo que `shopping_list.py`. La lista de la compra
generada desde un plan (`POST /shopping-list/from-plan/{plan_id}`) lee esta
tabla para descontar lo que ya hay antes de proponer qué comprar.
"""

from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from myfood.db.models import Food, PantryItem, User
from myfood.deps import get_current_user_id, get_db
from myfood.errors import AppError

router = APIRouter(prefix="/pantry", tags=["pantry"])


async def _get_item(session: AsyncSession, user_id: UUID, item_id: UUID) -> PantryItem:
    item = await session.get(PantryItem, item_id)
    if item is None or item.user_id != user_id:
        raise AppError("PANTRY_ITEM_NOT_FOUND", "No existe ese artículo de la despensa.", 404)
    return item


class PantryItemIn(BaseModel):
    food_id: UUID
    quantity_g: float = Field(gt=0, le=100000)
    expires_on: date | None = None


class PantryItemPatch(BaseModel):
    quantity_g: float | None = Field(default=None, gt=0, le=100000)
    expires_on: date | None = None


class PantryItemOut(BaseModel):
    id: UUID
    food_id: UUID
    food_name: str
    quantity_g: float
    expires_on: str | None
    owner_name: str
    is_mine: bool


def _to_out(item: PantryItem, food_name: str, owner_name: str, viewer_id: UUID) -> PantryItemOut:
    return PantryItemOut(
        id=item.id,
        food_id=item.food_id,
        food_name=food_name,
        quantity_g=float(item.quantity_g),
        expires_on=item.expires_on.isoformat() if item.expires_on else None,
        owner_name=owner_name,
        is_mine=item.user_id == viewer_id,
    )


@router.get("")
async def list_pantry(
    user_id: UUID = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_db),
) -> list[PantryItemOut]:
    # Sin filtrar por `user_id` a propósito: la RLS (migración 0011) ya
    # deja ver, además de lo propio, lo de los demás miembros del mismo
    # hogar ("modo familia") — la despensa compartida es justo el punto.
    rows = (
        await session.execute(
            select(PantryItem, Food.name_es, User.display_name)
            .join(Food, Food.id == PantryItem.food_id)
            .join(User, User.id == PantryItem.user_id)
            .order_by(Food.name_es)
        )
    ).all()
    return [_to_out(item, food_name, owner_name, user_id) for item, food_name, owner_name in rows]


@router.post("", status_code=201)
async def add_pantry_item(
    body: PantryItemIn,
    user_id: UUID = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_db),
) -> PantryItemOut:
    food = await session.get(Food, body.food_id)
    if food is None:
        raise AppError("FOOD_NOT_FOUND", "No existe ese alimento.", status_code=404)

    # Un alimento ya presente en la despensa se actualiza (suma cantidad) en
    # vez de duplicar la fila — mismo criterio que "añadir de nuevo lo que
    # ya tienes en casa" en la vida real.
    existing = await session.scalar(
        select(PantryItem).where(
            PantryItem.user_id == user_id, PantryItem.food_id == body.food_id
        )
    )
    if existing is not None:
        existing.quantity_g = float(existing.quantity_g) + body.quantity_g
        if body.expires_on is not None:
            existing.expires_on = body.expires_on
        item = existing
    else:
        item = PantryItem(
            user_id=user_id,
            food_id=body.food_id,
            quantity_g=body.quantity_g,
            expires_on=body.expires_on,
        )
        session.add(item)

    await session.commit()
    await session.refresh(item)
    owner = await session.get(User, user_id)
    return _to_out(item, food.name_es, owner.display_name, user_id)


@router.patch("/{item_id}")
async def update_pantry_item(
    item_id: UUID,
    body: PantryItemPatch,
    user_id: UUID = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_db),
) -> PantryItemOut:
    item = await _get_item(session, user_id, item_id)
    fields_set = body.model_fields_set

    if "quantity_g" in fields_set and body.quantity_g is not None:
        item.quantity_g = body.quantity_g
    if "expires_on" in fields_set:
        item.expires_on = body.expires_on

    await session.commit()
    await session.refresh(item)

    food = await session.get(Food, item.food_id)
    owner = await session.get(User, user_id)
    return _to_out(item, food.name_es if food else "", owner.display_name, user_id)


@router.delete("/{item_id}", status_code=204)
async def delete_pantry_item(
    item_id: UUID,
    user_id: UUID = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_db),
) -> None:
    item = await _get_item(session, user_id, item_id)
    await session.delete(item)
    await session.commit()
