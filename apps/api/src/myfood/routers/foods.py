import re
from datetime import date
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from myfood.cache import get_cached_barcode_lookup, set_cached_barcode_lookup
from myfood.db.models import Food, FoodNutrient
from myfood.db.session import get_session
from myfood.deps import get_current_user_id, get_db
from myfood.domain import portions as portions_calc
from myfood.domain.food_candidates import find_alternatives
from myfood.domain.food_suggestions import SuggestedFood, build_suggestions
from myfood.domain.food_taxonomy import (
    FOOD_TYPE_LABELS,
    NUTRITION_TAGS,
    SUPERMARKET_LABELS,
    SUPERMARKETS,
)
from myfood.errors import AppError
from myfood.off_client import fetch_product
from myfood.search import FoodFilters, search_foods_filtered
from myfood.services.images import ALLOWED_SIZES, IMAGE_TYPES, resolve_image

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
    fat_100g: float | None = None
    carbs_100g: float | None = None
    image_url: str | None
    source: str
    # Puntuaciones de Open Food Facts (solo productos de marca): el badge solo se pinta si hay dato.
    nutriscore_grade: str | None = None
    nova_group: int | None = None
    ecoscore_grade: str | None = None
    # Nombres para mostrar (no códigos): supermercado y tipo de alimento, si se conocen.
    supermarket: str | None = None
    food_type: str | None = None


class FacetOption(BaseModel):
    code: str
    label: str
    # Alimentos que quedarían con esta opción, dados los demás filtros elegidos.
    count: int
    description: str | None = None


class FoodFacets(BaseModel):
    supermarket: list[FacetOption]
    food_type: list[FacetOption]
    nutrition: list[FacetOption]


class FoodSearchResponse(BaseModel):
    items: list[FoodSearchItem]
    total: int
    facets: FoodFacets | None = None


def _validated(values: list[str], allowed: set[str], name: str) -> tuple[str, ...]:
    unknown = sorted(set(values) - allowed)
    if unknown:
        raise AppError(
            "INVALID_FILTER",
            f"Filtro no válido ({name}): {', '.join(unknown)}.",
            status_code=422,
            details={"filter": name, "values": unknown},
        )
    return tuple(dict.fromkeys(values))


def _facets(distribution: dict[str, dict[str, int]]) -> FoodFacets:
    supermarkets = [
        FacetOption(code=s.code, label=s.label, count=distribution["supermarket"].get(s.code, 0))
        for s in SUPERMARKETS
    ]
    food_types = [
        FacetOption(code=code, label=label, count=distribution["food_group"].get(code, 0))
        for code, label in FOOD_TYPE_LABELS.items()
    ]
    nutrition = [
        FacetOption(
            code=t.code,
            label=t.label,
            description=t.description,
            count=distribution["nutrition_tags"].get(t.code, 0),
        )
        for t in NUTRITION_TAGS
    ]
    supermarkets.sort(key=lambda o: -o.count)
    food_types.sort(key=lambda o: -o.count)
    return FoodFacets(supermarket=supermarkets, food_type=food_types, nutrition=nutrition)


@router.get("/search")
async def search(
    q: str = Query(default="", max_length=200),
    kind: Literal["generic", "branded", "recipe", "user"] | None = None,
    supermarket: list[str] = Query(default=[]),
    food_type: list[str] = Query(default=[]),
    nutrition: list[str] = Query(default=[]),
    sort: Literal["relevance", "kcal_asc", "protein_desc"] = "relevance",
    facets: bool = False,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    _user_id: UUID = Depends(get_current_user_id),
) -> FoodSearchResponse:
    """Búsqueda y exploración del catálogo. Sin texto y sin filtros no hay nada que buscar: para
    eso están las sugerencias (`/foods/suggestions`). Dentro de un mismo filtro las opciones
    se suman (Lidl o Aldi); las de nutrición se exigen todas. Con `facets=true` devuelve además
    cuántos alimentos tiene cada opción para pintar los filtros."""
    filters = FoodFilters(
        kind=kind,
        supermarkets=_validated(supermarket, set(SUPERMARKET_LABELS), "supermercado"),
        food_types=_validated(food_type, set(FOOD_TYPE_LABELS), "tipo de alimento"),
        nutrition=_validated(nutrition, {t.code for t in NUTRITION_TAGS}, "nutrición"),
    )
    result = await search_foods_filtered(
        q, filters, sort=sort, limit=limit, offset=offset, with_facets=facets
    )
    items = [
        FoodSearchItem(
            id=hit["id"],
            name_es=hit["name_es"],
            brand=hit.get("brand"),
            kcal_100g=hit.get("kcal_100g"),
            protein_100g=hit.get("protein_100g"),
            fat_100g=hit.get("fat_100g"),
            carbs_100g=hit.get("carbs_100g"),
            image_url=_image_url(hit),
            source=hit["source"],
            nutriscore_grade=hit.get("nutriscore_grade"),
            nova_group=hit.get("nova_group"),
            ecoscore_grade=hit.get("ecoscore_grade"),
            supermarket=SUPERMARKET_LABELS.get(hit.get("supermarket") or ""),
            food_type=FOOD_TYPE_LABELS.get(hit.get("food_group") or ""),
        )
        for hit in result.hits
    ]
    return FoodSearchResponse(
        items=items, total=result.total, facets=_facets(result.facets) if facets else None
    )


class SuggestionSectionOut(BaseModel):
    key: str
    title: str
    subtitle: str | None
    items: list[FoodSearchItem]


class SuggestionsResponse(BaseModel):
    sections: list[SuggestionSectionOut]


def _suggested_item(food: SuggestedFood) -> FoodSearchItem:
    return FoodSearchItem(
        id=food.id,
        name_es=food.name_es,
        brand=food.brand,
        kcal_100g=food.kcal_100g,
        protein_100g=food.protein_100g,
        fat_100g=food.fat_100g,
        carbs_100g=food.carbs_100g,
        image_url=f"/api/foods/{food.id}/image?type=front&size=100",
        source=food.source,
        nutriscore_grade=food.nutriscore_grade,
        nova_group=food.nova_group,
        ecoscore_grade=food.ecoscore_grade,
    )


@router.get("/suggestions")
async def get_suggestions(
    meal_type: Literal[
        "breakfast", "morning_snack", "lunch", "afternoon_snack", "dinner", "supper"
    ]
    | None = None,
    day: date | None = Query(default=None, alias="date"),
    user_id: UUID = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_db),
) -> SuggestionsResponse:
    """Qué mostrar al entrar en «Alimentos»: favoritos, habituales, recientes, alimentos ricos en
    proteína si hoy falta, básicos para la comida que toca y la despensa. `date` es el día local
    del usuario (el servidor no conoce su zona horaria). Lo que se propone de fuera del historial
    respeta sus alergias, intolerancias y vetos."""
    sections = await build_suggestions(
        session, user_id, day=day or date.today(), meal_type=meal_type
    )
    return SuggestionsResponse(
        sections=[
            SuggestionSectionOut(
                key=section.key,
                title=section.title,
                subtitle=section.subtitle,
                items=[_suggested_item(food) for food in section.items],
            )
            for section in sections
        ]
    )


def _image_url(hit: dict) -> str | None:
    # Siempre hay URL: `/foods/{id}/image` sirve el placeholder de la categoría cuando el
    # producto no tiene imagen (sección 12: nunca un hueco roto).
    return f"/api/foods/{hit['id']}/image?type=front&size=100"


class FoodAllergenOut(BaseModel):
    code: str
    name_es: str
    # 'declared' (etiqueta del fabricante), 'trace' ("puede contener") o
    # 'inferred' (genérico clasificado por palabras clave: orientativo).
    origin: str


class PortionOut(BaseModel):
    key: str
    label: str
    grams: float


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
    # gramos cocido / gramos crudo; si lo tiene, el registro admite pesar el plato ya cocinado.
    cooking_yield_factor: float | None = None
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
    allergens: list[FoodAllergenOut] = []
    # Atribución obligatoria de las imágenes de OFF (CC BY-SA), si el alimento tiene una.
    image_credit: str | None = None
    # Medidas caseras con las que registrarlo («1 huevo», «1 vaso», «100 g»). Los gramos de
    # cada una los pone el servidor (R1): la pantalla solo multiplica por la cantidad.
    portions: list[PortionOut] = []
    # Cantidad propuesta al abrir el formulario, en gramos.
    default_grams: float = 100.0


def _f(value) -> float | None:
    return float(value) if value is not None else None


async def _load_image_credit(session: AsyncSession, food_id: UUID) -> str | None:
    row = (
        await session.execute(
            text(
                "SELECT attribution, license FROM food_images "
                "WHERE food_id = :id AND attribution IS NOT NULL ORDER BY type LIMIT 1"
            ),
            {"id": str(food_id)},
        )
    ).first()
    if row is None:
        return None
    return f"{row.attribution} ({row.license})" if row.license else row.attribution


async def _load_allergens(session: AsyncSession, food_id: UUID) -> list[FoodAllergenOut]:
    rows = (
        await session.execute(
            text(
                "SELECT fa.allergen_code, a.name_es, fa.origin FROM food_allergens fa "
                "JOIN allergens a ON a.code = fa.allergen_code "
                "WHERE fa.food_id = :food_id ORDER BY a.name_es"
            ),
            {"food_id": str(food_id)},
        )
    ).all()
    return [FoodAllergenOut(code=r.allergen_code, name_es=r.name_es, origin=r.origin) for r in rows]


def _to_detail(
    food: Food,
    nutrients: FoodNutrient,
    allergens: list[FoodAllergenOut] | None = None,
    image_credit: str | None = None,
) -> FoodDetail:
    portion_list = portions_calc.build_portions(
        name_es=food.name_es,
        category=food.category,
        serving_size_g=_f(food.serving_size_g),
        serving_label=food.serving_label,
    )
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
        portions=[PortionOut(**p.__dict__) for p in portion_list],
        default_grams=portions_calc.default_grams(portion_list),
        cooking_yield_factor=_f(food.cooking_yield_factor),
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
        allergens=allergens or [],
        image_credit=image_credit,
    )


@router.get("/{food_id}/image")
async def get_food_image(
    food_id: UUID,
    type: str = Query(default="front"),
    size: str = Query(default="200"),
    _user_id: UUID = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_session),
):
    """Imagen de un producto desde la caché local; la descarga de OFF la primera vez
    (sección 12). Sin imagen o si falla la descarga: placeholder de su categoría con
    200 OK, nunca un 404 que rompa la interfaz."""
    if type not in IMAGE_TYPES:
        raise AppError("INVALID_IMAGE_TYPE", "Tipo de imagen no válido.", status_code=422)
    if size not in {str(s) for s in ALLOWED_SIZES}:
        raise AppError("INVALID_IMAGE_SIZE", "Tamaño de imagen no válido.", status_code=422)
    food = await session.get(Food, food_id)
    if food is None:
        raise AppError("FOOD_NOT_FOUND", "No existe ese alimento.", status_code=404)

    outcome = await resolve_image(session, food, type, size)
    headers = {"Cache-Control": outcome.cache_control}
    if outcome.path is not None:
        return FileResponse(outcome.path, media_type=outcome.media_type, headers=headers)
    return Response(outcome.placeholder, media_type=outcome.media_type, headers=headers)


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
    return _to_detail(
        food,
        nutrients,
        await _load_allergens(session, food_id),
        await _load_image_credit(session, food_id),
    )


async def _get_food_by_barcode(session: AsyncSession, ean: str) -> FoodDetail | None:
    food = await session.scalar(select(Food).where(Food.barcode_ean == ean).limit(1))
    if food is None:
        return None
    nutrients = await session.get(FoodNutrient, food.id)
    if nutrients is None:
        return None
    return _to_detail(
        food,
        nutrients,
        await _load_allergens(session, food.id),
        await _load_image_credit(session, food.id),
    )


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


class SimilarFoodItem(BaseModel):
    id: str
    name_es: str
    brand: str | None
    kcal_100g: float | None
    distance: float
    # Cantidad de esta alternativa que equivale a `grams` del original (conserva kcal o proteína).
    grams: float


class SimilarFoodsResponse(BaseModel):
    items: list[SimilarFoodItem]


@router.get("/{food_id}/similar")
async def get_similar_foods(
    food_id: UUID,
    limit: int = Query(default=3, ge=1, le=20),
    keep: Literal["kcal", "protein"] = "kcal",
    grams: float = Query(default=100, gt=0, le=5000),
    user_id: UUID = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_db),
) -> SimilarFoodsResponse:
    """Alternativas para sustituir un alimento: nutricionalmente parecidas (distancia L2 sobre
    `food_vectors`, ver `domain/food_vector.py`), del mismo grupo alimentario y permitidas por
    las restricciones del usuario (alérgenos, intolerancias, vetados). Cada una trae los gramos
    ya recalculados para conservar las kcal (`keep=kcal`) o la proteína (`keep=protein`) de
    `grams` del original — nunca se ofrece una alternativa sin ajustar."""
    food = await session.get(Food, food_id)
    if food is None:
        raise AppError("FOOD_NOT_FOUND", "No existe ese alimento.", status_code=404)

    has_vector = await session.scalar(
        text("SELECT 1 FROM food_vectors WHERE food_id = :food_id"), {"food_id": str(food_id)}
    )
    if has_vector is None:
        raise AppError(
            "FOOD_VECTOR_NOT_FOUND",
            "Este alimento todavía no tiene un vector nutricional calculado.",
            status_code=404,
        )

    alternatives = await find_alternatives(
        session, food_id, grams, user_id, keep=keep, limit=limit
    )
    return SimilarFoodsResponse(
        items=[
            SimilarFoodItem(
                id=str(alt.food_id),
                name_es=alt.name_es,
                brand=alt.brand,
                kcal_100g=alt.kcal_100g,
                distance=alt.distance,
                grams=alt.grams,
            )
            for alt in alternatives
        ]
    )


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
