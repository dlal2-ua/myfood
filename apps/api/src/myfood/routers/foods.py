from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from myfood.db.models import Food, FoodNutrient
from myfood.db.session import get_session
from myfood.deps import get_current_user_id
from myfood.errors import AppError
from myfood.search import search_foods

router = APIRouter(prefix="/foods", tags=["foods"])


class FoodSearchItem(BaseModel):
    id: str
    name_es: str
    brand: str | None
    kcal_100g: float | None
    protein_100g: float | None
    image_url: str | None
    source: str


class FoodSearchResponse(BaseModel):
    items: list[FoodSearchItem]
    total: int


@router.get("/search")
async def search(
    q: str = Query(min_length=1),
    kind: Literal["generic", "branded", "recipe", "user"] | None = None,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    _user_id: UUID = Depends(get_current_user_id),
) -> FoodSearchResponse:
    hits, total = await search_foods(q, kind, limit, offset)
    items = [
        FoodSearchItem(
            id=hit["id"],
            name_es=hit["name_es"],
            brand=hit.get("brand"),
            kcal_100g=hit.get("kcal_100g"),
            protein_100g=hit.get("protein_100g"),
            image_url=_image_url(hit),
            source=hit["source"],
        )
        for hit in hits
    ]
    return FoodSearchResponse(items=items, total=total)


def _image_url(hit: dict) -> str | None:
    if not hit.get("has_image"):
        return None
    return f"/api/foods/{hit['id']}/image?type=front&size=200"


class FoodDetail(BaseModel):
    id: str
    kind: str
    source: str
    license: str
    attribution: str | None
    barcode_ean: str | None
    name_es: str
    name_en: str | None
    brand: str | None
    category: str | None
    serving_size_g: float | None
    serving_label: str | None
    quality_rank: int
    nutriscore_grade: str | None
    nova_group: int | None
    ecoscore_grade: str | None
    kcal_100g: float
    protein_100g: float
    fat_100g: float
    saturated_100g: float | None
    carbs_100g: float
    sugars_100g: float | None
    fiber_100g: float | None
    salt_100g: float | None
    micros: dict


@router.get("/{food_id}")
async def get_food(
    food_id: UUID,
    _user_id: UUID = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_session),
) -> FoodDetail:
    food = await session.get(Food, food_id)
    if food is None:
        raise AppError("FOOD_NOT_FOUND", "No existe ese alimento.", status_code=404)
    nutrients = await session.get(FoodNutrient, food_id)
    if nutrients is None:
        raise AppError("FOOD_NOT_FOUND", "No existe ese alimento.", status_code=404)

    def _f(value) -> float | None:
        return float(value) if value is not None else None

    return FoodDetail(
        id=str(food.id),
        kind=food.kind,
        source=food.source,
        license=food.license,
        attribution=food.attribution,
        barcode_ean=food.barcode_ean,
        name_es=food.name_es,
        name_en=food.name_en,
        brand=food.brand,
        category=food.category,
        serving_size_g=_f(food.serving_size_g),
        serving_label=food.serving_label,
        quality_rank=food.quality_rank,
        nutriscore_grade=food.nutriscore_grade,
        nova_group=food.nova_group,
        ecoscore_grade=food.ecoscore_grade,
        kcal_100g=_f(nutrients.kcal_100g),
        protein_100g=_f(nutrients.protein_100g),
        fat_100g=_f(nutrients.fat_100g),
        saturated_100g=_f(nutrients.saturated_100g),
        carbs_100g=_f(nutrients.carbs_100g),
        sugars_100g=_f(nutrients.sugars_100g),
        fiber_100g=_f(nutrients.fiber_100g),
        salt_100g=_f(nutrients.salt_100g),
        micros=nutrients.micros,
    )
