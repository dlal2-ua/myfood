"""Lista de la compra (sección 6.4). Dos vías para añadir artículos:

1. Manual: el usuario elige un alimento del catálogo o escribe texto libre
   para lo que no está en el catálogo (p. ej. "papel de aluminio").
2. Generada desde un plan de dieta (`POST /from-plan/{plan_id}`, Fase 7):
   suma los gramos de cada alimento en los 7 días del plan y descuenta lo
   que ya hay en la despensa (`pantry_items`) — criterio de aceptación de
   la Fase 7. Los `plan_items` con `recipe_id` (comidas de batch cooking,
   Fase 7) se expanden a sus ingredientes reales (`recipe_ingredients`,
   escalados a los gramos de receta que pida el plan) antes de sumar —
   nunca se guarda un desglose de ingredientes aparte que pudiera
   desincronizarse (R9).
"""

from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from myfood.db.models import (
    DietPlan,
    Food,
    PantryItem,
    PlanDay,
    PlanItem,
    PlanMeal,
    RecipeIngredient,
    ShoppingListItem,
    User,
)
from myfood.deps import get_current_user_id, get_db
from myfood.errors import AppError

router = APIRouter(prefix="/shopping-list", tags=["shopping-list"])


async def _get_item(session: AsyncSession, item_id: UUID) -> ShoppingListItem:
    # Sin comprobar `user_id` a mano: la RLS (migración 0011) ya decide
    # quién puede ver/editar cada fila — lista de la compra compartida de
    # verdad con el resto del hogar, no solo lo propio.
    item = await session.get(ShoppingListItem, item_id)
    if item is None:
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
    owner_name: str
    is_mine: bool


def _to_out(
    item: ShoppingListItem, food_name: str | None, owner_name: str, viewer_id: UUID
) -> ShoppingListItemOut:
    return ShoppingListItemOut(
        id=item.id,
        food_id=item.food_id,
        food_name=food_name,
        free_text=item.free_text,
        quantity_g=float(item.quantity_g) if item.quantity_g is not None else None,
        category=item.category,
        is_checked=item.is_checked,
        owner_name=owner_name,
        is_mine=item.user_id == viewer_id,
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
    owner = await session.get(User, user_id)
    return _to_out(item, food_name, owner.display_name, user_id)


class ShoppingListOut(BaseModel):
    items: list[ShoppingListItemOut]


@router.get("")
async def list_items(
    user_id: UUID = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_db),
) -> ShoppingListOut:
    # Sin filtrar por `user_id` a propósito: la RLS (migración 0011) ya
    # deja ver, además de lo propio, lo de los demás miembros del mismo
    # hogar — lista de la compra compartida de verdad.
    stmt = (
        select(ShoppingListItem, Food.name_es, User.display_name)
        .outerjoin(Food, Food.id == ShoppingListItem.food_id)
        .join(User, User.id == ShoppingListItem.user_id)
        .order_by(
            ShoppingListItem.is_checked,
            ShoppingListItem.category.nulls_last(),
            ShoppingListItem.created_at,
        )
    )
    rows = (await session.execute(stmt)).all()
    return ShoppingListOut(
        items=[
            _to_out(item, food_name, owner_name, user_id)
            for item, food_name, owner_name in rows
        ]
    )


@router.post("/from-plan/{plan_id}", status_code=201)
async def generate_from_plan(
    plan_id: UUID,
    user_id: UUID = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_db),
) -> ShoppingListOut:
    plan = await session.get(DietPlan, plan_id)
    if plan is None or plan.user_id != user_id:
        raise AppError("DIET_PLAN_NOT_FOUND", "No existe ese plan.", status_code=404)

    needed: dict[UUID, float] = {}
    for food_id, total_grams in await session.execute(
        select(PlanItem.food_id, func.sum(PlanItem.grams))
        .join(PlanMeal, PlanMeal.id == PlanItem.plan_meal_id)
        .join(PlanDay, PlanDay.id == PlanMeal.plan_day_id)
        .where(PlanDay.plan_id == plan_id, PlanItem.food_id.is_not(None))
        .group_by(PlanItem.food_id)
    ):
        needed[food_id] = needed.get(food_id, 0.0) + float(total_grams)

    recipe_rows = (
        await session.execute(
            select(PlanItem.recipe_id, func.sum(PlanItem.grams))
            .join(PlanMeal, PlanMeal.id == PlanItem.plan_meal_id)
            .join(PlanDay, PlanDay.id == PlanMeal.plan_day_id)
            .where(PlanDay.plan_id == plan_id, PlanItem.recipe_id.is_not(None))
            .group_by(PlanItem.recipe_id)
        )
    ).all()
    for recipe_id, recipe_grams_needed in recipe_rows:
        ingredients = list(
            await session.scalars(
                select(RecipeIngredient).where(RecipeIngredient.recipe_id == recipe_id)
            )
        )
        total_ingredient_weight = sum(float(i.grams) for i in ingredients)
        if total_ingredient_weight <= 0:
            continue
        scale = float(recipe_grams_needed) / total_ingredient_weight
        for ingredient in ingredients:
            needed[ingredient.food_id] = needed.get(ingredient.food_id, 0.0) + float(
                ingredient.grams
            ) * scale

    needed_rows = needed.items()

    # Sin filtrar por `user_id`: si hay modo familia, se descuenta la
    # despensa compartida del hogar entero (RLS, migración 0011), no solo
    # lo que tenga el dueño del plan — no tiene sentido comprar otra vez
    # lo que ya tiene cualquier miembro en casa.
    pantry_rows = await session.execute(
        select(PantryItem.food_id, PantryItem.quantity_g)
    )
    in_pantry: dict[UUID, float] = {}
    for food_id, quantity_g in pantry_rows:
        in_pantry[food_id] = in_pantry.get(food_id, 0.0) + float(quantity_g)

    # Regenerar en limpio: una llamada repetida para el mismo plan no debe
    # ir acumulando artículos duplicados.
    await session.execute(delete(ShoppingListItem).where(ShoppingListItem.plan_id == plan_id))

    created: list[ShoppingListItem] = []
    for food_id, total_needed in needed_rows:
        remaining = float(total_needed) - in_pantry.get(food_id, 0.0)
        if remaining <= 0:
            continue  # la despensa ya cubre este alimento entero
        food = await session.get(Food, food_id)
        item = ShoppingListItem(
            user_id=user_id,
            food_id=food_id,
            quantity_g=round(remaining, 2),
            category=food.category if food else None,
            plan_id=plan_id,
        )
        session.add(item)
        created.append(item)

    await session.commit()

    owner = await session.get(User, user_id)
    out: list[ShoppingListItemOut] = []
    for item in created:
        food = await session.get(Food, item.food_id)
        await session.refresh(item)
        out.append(_to_out(item, food.name_es if food else None, owner.display_name, user_id))
    return ShoppingListOut(items=out)


@router.delete("/checked", status_code=204)
async def clear_checked(
    session: AsyncSession = Depends(get_db),
) -> None:
    # Sin filtrar por `user_id`: limpia lo marcado de todo el hogar visible
    # (RLS, migración 0011) — después de la compra, cualquiera termina de
    # limpiar la lista, no solo quien añadió cada artículo.
    items = list(
        await session.scalars(
            select(ShoppingListItem).where(ShoppingListItem.is_checked.is_(True))
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
    item = await _get_item(session, item_id)
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
    owner = await session.get(User, item.user_id)
    return _to_out(item, food_name, owner.display_name if owner else "", user_id)


@router.delete("/{item_id}", status_code=204)
async def delete_item(
    item_id: UUID,
    user_id: UUID = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_db),
) -> None:
    item = await _get_item(session, item_id)
    await session.delete(item)
    await session.commit()
