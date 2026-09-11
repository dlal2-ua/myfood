"""Lista de la compra manual (sección 6.4) — el usuario añade artículos a
mano, eligiendo un alimento del catálogo o escribiendo texto libre para lo
que no está en el catálogo (p. ej. "papel de aluminio"). No se genera a
partir de ningún plan de comidas: `plan_id` existe en el esquema para un
feature futuro (Fase 4) y se deja sin usar aquí.
"""

from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from myfood.db.models import Food, ShoppingListItem
from myfood.deps import get_current_user_id, get_db
from myfood.errors import AppError

router = APIRouter(prefix="/shopping-list", tags=["shopping-list"])


async def _get_item(session: AsyncSession, user_id: UUID, item_id: UUID) -> ShoppingListItem:
    item = await session.get(ShoppingListItem, item_id)
    if item is None or item.user_id != user_id:
        raise AppError("SHOPPING_ITEM_NOT_FOUND", "No existe ese artículo.", status_code=404)
    return item


class ShoppingListItemIn(BaseModel):
    food_id: UUID | None = None
    free_text: str | None = Field(default=None, min_length=1, max_length=200)
    quantity_g: float | None = Field(default=None, gt=0, le=100000)
    category: str | None = None

    @model_validator(mode="after")
    def _exactly_one_of_food_or_text(self) -> "ShoppingListItemIn":
        # La migración 0001 no tiene un CHECK para shopping_list_items como sí
        # lo tiene user_favorite_foods — se valida aquí en su lugar: sin uno
        # de los dos no hay nada que mostrar en la lista.
        if (self.food_id is None) == (self.free_text is None):
            raise ValueError("Indica food_id o free_text, pero no ambos ni ninguno.")
        return self


class ShoppingListItemOut(BaseModel):
    id: UUID
    food_id: UUID | None
    food_name: str | None
    free_text: str | None
    quantity_g: float | None
    category: str | None
    is_checked: bool


def _to_out(item: ShoppingListItem, food_name: str | None) -> ShoppingListItemOut:
    return ShoppingListItemOut(
        id=item.id,
        food_id=item.food_id,
        food_name=food_name,
        free_text=item.free_text,
        quantity_g=float(item.quantity_g) if item.quantity_g is not None else None,
        category=item.category,
        is_checked=item.is_checked,
    )


@router.post("", status_code=201)
async def add_item(
    body: ShoppingListItemIn,
    user_id: UUID = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_db),
) -> ShoppingListItemOut:
    food_name = None
    if body.food_id is not None:
        food = await session.get(Food, body.food_id)
        if food is None:
            raise AppError("FOOD_NOT_FOUND", "No existe ese alimento.", status_code=404)
        food_name = food.name_es

    item = ShoppingListItem(
        user_id=user_id,
        food_id=body.food_id,
        free_text=body.free_text,
        quantity_g=body.quantity_g,
        category=body.category,
    )
    session.add(item)
    await session.commit()
    await session.refresh(item)
    return _to_out(item, food_name)


class ShoppingListOut(BaseModel):
    items: list[ShoppingListItemOut]


@router.get("")
async def list_items(
    user_id: UUID = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_db),
) -> ShoppingListOut:
    stmt = (
        select(ShoppingListItem, Food.name_es)
        .outerjoin(Food, Food.id == ShoppingListItem.food_id)
        .where(ShoppingListItem.user_id == user_id)
        .order_by(
            ShoppingListItem.is_checked,
            ShoppingListItem.category.nulls_last(),
            ShoppingListItem.created_at,
        )
    )
    rows = (await session.execute(stmt)).all()
    return ShoppingListOut(items=[_to_out(item, food_name) for item, food_name in rows])


@router.delete("/checked", status_code=204)
async def clear_checked(
    user_id: UUID = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_db),
) -> None:
    items = list(
        await session.scalars(
            select(ShoppingListItem).where(
                ShoppingListItem.user_id == user_id, ShoppingListItem.is_checked.is_(True)
            )
        )
    )
    for item in items:
        await session.delete(item)
    await session.commit()


class ShoppingListItemPatch(BaseModel):
    is_checked: bool | None = None
    quantity_g: float | None = Field(default=None, gt=0, le=100000)
    category: str | None = None


@router.patch("/{item_id}")
async def update_item(
    item_id: UUID,
    body: ShoppingListItemPatch,
    user_id: UUID = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_db),
) -> ShoppingListItemOut:
    item = await _get_item(session, user_id, item_id)
    fields_set = body.model_fields_set

    if "is_checked" in fields_set and body.is_checked is not None:
        item.is_checked = body.is_checked
    if "quantity_g" in fields_set:
        item.quantity_g = body.quantity_g
    if "category" in fields_set:
        item.category = body.category

    await session.commit()
    await session.refresh(item)

    food_name = None
    if item.food_id is not None:
        food = await session.get(Food, item.food_id)
        food_name = food.name_es if food else None
    return _to_out(item, food_name)


@router.delete("/{item_id}", status_code=204)
async def delete_item(
    item_id: UUID,
    user_id: UUID = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_db),
) -> None:
    item = await _get_item(session, user_id, item_id)
    await session.delete(item)
    await session.commit()
