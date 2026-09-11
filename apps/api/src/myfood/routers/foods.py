import re
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from myfood.cache import get_cached_barcode_lookup, set_cached_barcode_lookup
from myfood.db.models import Food, FoodNutrient
from myfood.db.session import get_session
from myfood.deps import get_current_user_id
from myfood.errors import AppError
from myfood.off_client import fetch_product
from myfood.search import search_foods

router = APIRouter(prefix="/foods", tags=["foods"])

# Prioridad de fuentes (documento 2, sección 11): USDA Foundation=1,
# USDA SR=2, CIQUAL=3, BEDCA=4, OFF=5. Las altas manuales del usuario, sin
# ninguna revisión, van al final.
USER_QUALITY_RANK = 6
_EAN_RE = re.compile(r"^\d{8,14}$")


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


def _f(value) -> float | None:
    return float(value) if value is not None else None


def _to_detail(food: Food, nutrients: FoodNutrient) -> FoodDetail:
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
    return _to_detail(food, nutrients)


async def _get_food_by_barcode(session: AsyncSession, ean: str) -> FoodDetail | None:
    food = await session.scalar(select(Food).where(Food.barcode_ean == ean).limit(1))
    if food is None:
        return None
    nutrients = await session.get(FoodNutrient, food.id)
    if nutrients is None:
        return None
    return _to_detail(food, nutrients)


@router.get("/barcode/{ean}")
async def get_by_barcode(
    ean: str,
    _user_id: UUID = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_session),
) -> FoodDetail:
    """Flujo de escaneo (sección 11.2): BD local -> caché de negativos ->
    API en vivo de OFF -> si nada de eso tiene el código, 404 y el frontend
    ofrece el alta manual (`POST /foods/manual`)."""
    if not _EAN_RE.match(ean):
        raise AppError("INVALID_BARCODE", "Código de barras no válido.", status_code=422)

    existing = await _get_food_by_barcode(session, ean)
    if existing is not None:
        return existing

    cached = await get_cached_barcode_lookup(ean)
    if cached is not None and not cached.get("found"):
        raise AppError(
            "FOOD_NOT_FOUND_BY_BARCODE", "No se encontró ese producto.", status_code=404
        )

    product = await fetch_product(ean)
    if product is None:
        await set_cached_barcode_lookup(ean, {"found": False})
        raise AppError(
            "FOOD_NOT_FOUND_BY_BARCODE", "No se encontró ese producto.", status_code=404
        )

    food = Food(
        kind="branded",
        source="off",
        source_id=product.barcode_ean,
        license="ODbL",
        attribution="Open Food Facts",
        barcode_ean=product.barcode_ean,
        name_es=product.name_es,
        name_en=product.name_en,
        brand=product.brand,
        category=product.category,
        serving_size_g=product.serving_size_g,
        serving_label=product.serving_label,
        quality_rank=5,
        nutriscore_grade=product.nutriscore_grade,
        nova_group=product.nova_group,
        ecoscore_grade=product.ecoscore_grade,
    )
    session.add(food)
    await session.flush()
    nutrients = FoodNutrient(
        food_id=food.id,
        kcal_100g=product.kcal_100g,
        protein_100g=product.protein_100g,
        fat_100g=product.fat_100g,
        saturated_100g=product.saturated_100g,
        carbs_100g=product.carbs_100g,
        sugars_100g=product.sugars_100g,
        fiber_100g=product.fiber_100g,
        salt_100g=product.salt_100g,
        micros=product.micros,
    )
    session.add(nutrients)
    await session.commit()
    return _to_detail(food, nutrients)


class ManualFoodIn(BaseModel):
    barcode_ean: str | None = Field(default=None, pattern=r"^\d{8,14}$")
    name_es: str = Field(min_length=1, max_length=200)
    brand: str | None = None
    kcal_100g: float = Field(gt=0, le=900)
    protein_100g: float = Field(default=0, ge=0)
    fat_100g: float = Field(default=0, ge=0)
    carbs_100g: float = Field(default=0, ge=0)
    saturated_100g: float | None = Field(default=None, ge=0)
    sugars_100g: float | None = Field(default=None, ge=0)
    fiber_100g: float | None = Field(default=None, ge=0)
    salt_100g: float | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def _macros_within_100g(self) -> "ManualFoodIn":
        if self.protein_100g + self.fat_100g + self.carbs_100g > 100:
            raise ValueError("La suma de proteína, grasa y carbohidratos no puede superar 100 g.")
        return self


@router.post("/manual", status_code=201)
async def create_manual_food(
    body: ManualFoodIn,
    _user_id: UUID = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_session),
) -> FoodDetail:
    """Último paso del flujo de escaneo (sección 11.2): ni el catálogo local
    ni OFF tenían el código — el usuario da de alta el producto a mano con
    los datos reales de la etiqueta. Nunca se estima nada (R9); esto es dato
    observado por el usuario, no inventado por la IA."""
    if body.barcode_ean:
        existing = await _get_food_by_barcode(session, body.barcode_ean)
        if existing is not None:
            return existing

    food = Food(
        kind="user",
        source="user",
        source_id=body.barcode_ean,
        license="Uso interno",
        attribution=None,
        barcode_ean=body.barcode_ean,
        name_es=body.name_es,
        brand=body.brand,
        quality_rank=USER_QUALITY_RANK,
    )
    session.add(food)
    await session.flush()
    nutrients = FoodNutrient(
        food_id=food.id,
        kcal_100g=body.kcal_100g,
        protein_100g=body.protein_100g,
        fat_100g=body.fat_100g,
        saturated_100g=body.saturated_100g,
        carbs_100g=body.carbs_100g,
        sugars_100g=body.sugars_100g,
        fiber_100g=body.fiber_100g,
        salt_100g=body.salt_100g,
        micros={},
    )
    session.add(nutrients)
    await session.commit()
    return _to_detail(food, nutrients)
