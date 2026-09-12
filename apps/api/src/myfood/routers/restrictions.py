"""Restricciones alimentarias del usuario (sección 6.1): alérgenos,
intolerancias y alimentos que no le gustan o tiene prohibidos. Las usa el
motor de dietas (Fase 4, en paralelo) y el endpoint de alimentos similares
(`GET /foods/{food_id}/similar`, en este mismo PR) para no proponer nunca
algo que el usuario no puede o no quiere comer.

`GET /allergens` expone los 14 alérgenos regulados por el Reglamento UE
1169/2011 (Anexo II), sembrados en la migración 0005 — es dato de catálogo
público (no de usuario, sin RLS) pero sigue exigiendo sesión iniciada,
como cualquier otro endpoint de esta app.

Validación por `kind` (coherente con el CHECK de `user_restrictions` en la
migración 0001):
- `allergen`: siempre referencia uno de los 14 alérgenos regulados ->
  requiere `allergen_code`, nunca `food_id`.
- `intolerance`: una intolerancia puede ser a una sustancia de la propia
  lista de alérgenos (p. ej. la lactosa, dentro de "lacteos") o a un
  alimento concreto que no pertenece a ninguna categoría regulada (p. ej.
  intolerancia a la fructosa de una fruta en concreto) -> se admite
  EXACTAMENTE uno de `allergen_code` o `food_id`, nunca ambos ni ninguno.
- `disliked_food` / `banned_food`: siempre sobre un alimento concreto del
  catálogo -> requieren `food_id`, nunca `allergen_code`.
"""

from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from myfood.db.models import Allergen, Food, UserRestriction
from myfood.deps import get_current_user_id, get_db
from myfood.errors import AppError

router = APIRouter(tags=["restrictions"])


class AllergenOut(BaseModel):
    code: str
    name_es: str


class AllergenListOut(BaseModel):
    items: list[AllergenOut]


@router.get("/allergens")
async def list_allergens(
    _user_id: UUID = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_db),
) -> AllergenListOut:
    rows = (await session.scalars(select(Allergen).order_by(Allergen.name_es))).all()
    return AllergenListOut(items=[AllergenOut(code=a.code, name_es=a.name_es) for a in rows])


class RestrictionIn(BaseModel):
    kind: Literal["allergen", "intolerance", "disliked_food", "banned_food"]
    allergen_code: str | None = None
    food_id: UUID | None = None
    note: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def _validate_fields_for_kind(self) -> "RestrictionIn":
        if self.kind == "allergen":
            if self.allergen_code is None or self.food_id is not None:
                raise ValueError(
                    "kind='allergen' requiere allergen_code y no admite food_id."
                )
        elif self.kind == "intolerance":
            if (self.allergen_code is None) == (self.food_id is None):
                raise ValueError(
                    "kind='intolerance' requiere exactamente uno de allergen_code o food_id."
                )
        else:  # disliked_food, banned_food
            if self.food_id is None or self.allergen_code is not None:
                raise ValueError(
                    f"kind='{self.kind}' requiere food_id y no admite allergen_code."
                )
        return self


class RestrictionOut(BaseModel):
    id: UUID
    kind: str
    allergen_code: str | None
    allergen_name: str | None
    food_id: UUID | None
    food_name: str | None
    note: str | None


def _to_out(
    restriction: UserRestriction, allergen_name: str | None, food_name: str | None
) -> RestrictionOut:
    return RestrictionOut(
        id=restriction.id,
        kind=restriction.kind,
        allergen_code=restriction.allergen_code,
        allergen_name=allergen_name,
        food_id=restriction.food_id,
        food_name=food_name,
        note=restriction.note,
    )


@router.post("/restrictions", status_code=201)
async def create_restriction(
    body: RestrictionIn,
    user_id: UUID = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_db),
) -> RestrictionOut:
    allergen: Allergen | None = None
    food: Food | None = None

    if body.allergen_code is not None:
        allergen = await session.get(Allergen, body.allergen_code)
        if allergen is None:
            raise AppError("ALLERGEN_NOT_FOUND", "No existe ese alérgeno.", status_code=404)

    if body.food_id is not None:
        food = await session.get(Food, body.food_id)
        if food is None:
            raise AppError("FOOD_NOT_FOUND", "No existe ese alimento.", status_code=404)

    restriction = UserRestriction(
        user_id=user_id,
        kind=body.kind,
        allergen_code=body.allergen_code,
        food_id=body.food_id,
        note=body.note,
    )
    session.add(restriction)
    await session.commit()
    await session.refresh(restriction)

    return _to_out(
        restriction,
        allergen.name_es if allergen else None,
        food.name_es if food else None,
    )


class RestrictionListOut(BaseModel):
    items: list[RestrictionOut]


@router.get("/restrictions")
async def list_restrictions(
    user_id: UUID = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_db),
) -> RestrictionListOut:
    stmt = (
        select(UserRestriction, Allergen.name_es, Food.name_es)
        .outerjoin(Allergen, Allergen.code == UserRestriction.allergen_code)
        .outerjoin(Food, Food.id == UserRestriction.food_id)
        .where(UserRestriction.user_id == user_id)
        .order_by(UserRestriction.kind)
    )
    rows = (await session.execute(stmt)).all()
    return RestrictionListOut(
        items=[
            _to_out(restriction, allergen_name, food_name)
            for restriction, allergen_name, food_name in rows
        ]
    )


async def _get_restriction(
    session: AsyncSession, user_id: UUID, restriction_id: UUID
) -> UserRestriction:
    restriction = await session.get(UserRestriction, restriction_id)
    # R3: filtrado explícito en código, además de la política RLS de la
    # migración 0002 (segunda capa, independiente — sección 22).
    if restriction is None or restriction.user_id != user_id:
        raise AppError("RESTRICTION_NOT_FOUND", "No existe esa restricción.", status_code=404)
    return restriction


@router.delete("/restrictions/{restriction_id}", status_code=204)
async def delete_restriction(
    restriction_id: UUID,
    user_id: UUID = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_db),
) -> None:
    restriction = await _get_restriction(session, user_id, restriction_id)
    await session.delete(restriction)
    await session.commit()
