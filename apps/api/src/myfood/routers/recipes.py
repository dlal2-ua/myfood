"""Recetas propias (sección 6.4/20). `recipes` tiene RLS propia (tiene
`user_id`, migración 0002); `recipe_ingredients` NO (sin `user_id`) — su
aislamiento multiusuario pasa por `_get_recipe` (RLS + comprobación
explícita sobre `recipes`) y de ahí para abajo, mismo patrón R3 ya usado
para `plan_items`/`plan_item_alternatives` en `diet_plans.py`.

Sin columnas de nutrición propias por diseño: los totales siempre se
calculan sumando `food_nutrients` de cada ingrediente × gramos/100 (R9 —
nunca un valor guardado que pueda desincronizarse si cambian los
ingredientes)."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, File, Response, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from myfood.ai.consent import require_ai_processing_consent
from myfood.ai.flows.recipe_import import request_recipe_import
from myfood.ai.quota import QuotaExceeded, check_and_consume_quota, reset_at_iso
from myfood.ai.schemas import AiSessionOut, ai_session_to_out
from myfood.db.models import Food, FoodNutrient, Recipe, RecipeIngredient
from myfood.deps import get_current_user_id, get_db
from myfood.domain.ean import ean13_svg, generate_internal_ean
from myfood.errors import AppError
from myfood.routers._user_images import serve_image, store_uploaded_image
from myfood.services import user_images

router = APIRouter(prefix="/recipes", tags=["recipes"])


class RecipeIngredientIn(BaseModel):
    food_id: UUID
    grams: float = Field(gt=0, le=10000)


class RecipeIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    servings: int = Field(default=1, ge=1, le=50)
    prep_minutes: int | None = Field(default=None, ge=0, le=1440)
    instructions: str | None = None
    ingredients: list[RecipeIngredientIn] = Field(default_factory=list)


class RecipePatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    servings: int | None = Field(default=None, ge=1, le=50)
    prep_minutes: int | None = Field(default=None, ge=0, le=1440)
    instructions: str | None = None


class RecipeIngredientOut(BaseModel):
    id: UUID
    food_id: UUID
    name_es: str
    grams: float
    kcal: float
    protein_g: float
    fat_g: float
    carbs_g: float


class NutritionTotals(BaseModel):
    kcal: float
    protein_g: float
    fat_g: float
    carbs_g: float


class RecipeOut(BaseModel):
    id: UUID
    name: str
    # EAN-13 interno (prefijo 20) para imprimir una etiqueta y escanearla al registrar la receta.
    internal_ean: str | None = None
    image_url: str | None = None
    servings: int
    prep_minutes: int | None
    instructions: str | None
    ingredients: list[RecipeIngredientOut]
    totals: NutritionTotals
    totals_per_serving: NutritionTotals
    # De dónde salió la receta. Las fuentes del recetario piden que se las cite, así que
    # tiene que llegar a la pantalla: guardarla y no enseñarla no cumple nada.
    attribution: str | None = None


class RecipeSummaryOut(BaseModel):
    id: UUID
    name: str
    servings: int
    prep_minutes: int | None
    image_url: str | None = None


def _scale(nutrient_100g, grams: float) -> float:
    return round(float(nutrient_100g or 0) * grams / 100, 2)


async def _get_recipe(
    session: AsyncSession, user_id: UUID, recipe_id: UUID, *, allow_catalog: bool = False
) -> Recipe:
    """Por defecto solo las del usuario. `allow_catalog` añade las del recetario compartido
    (`user_id IS NULL`), que se pueden LEER y usar pero nunca editar ni borrar."""
    recipe = await session.get(Recipe, recipe_id)
    if recipe is None:
        raise AppError("RECIPE_NOT_FOUND", "No existe esa receta.", status_code=404)
    if recipe.user_id == user_id:
        return recipe
    if allow_catalog and recipe.user_id is None:
        return recipe
    raise AppError("RECIPE_NOT_FOUND", "No existe esa receta.", status_code=404)


async def _ensure_internal_ean(session: AsyncSession, recipe: Recipe) -> str:
    """Asigna un EAN interno a la receta si todavía no lo tiene (las anteriores a esta función no
    lo traen). Los códigos son aleatorios y únicos: si uno choca, se genera otro."""
    if recipe.internal_ean:
        return recipe.internal_ean
    for _ in range(20):
        candidate = generate_internal_ean()
        taken = await session.scalar(select(Recipe.id).where(Recipe.internal_ean == candidate))
        if taken is None:
            recipe.internal_ean = candidate
            await session.commit()
            return candidate
    raise AppError("EAN_GENERATION_FAILED", "No se pudo generar un código.", status_code=500)


async def _load_ingredients(session: AsyncSession, recipe_id: UUID) -> list[RecipeIngredient]:
    return list(
        await session.scalars(
            select(RecipeIngredient).where(RecipeIngredient.recipe_id == recipe_id)
        )
    )


async def _to_out(session: AsyncSession, recipe: Recipe) -> RecipeOut:
    ingredients = await _load_ingredients(session, recipe.id)

    ingredients_out: list[RecipeIngredientOut] = []
    totals = {"kcal": 0.0, "protein_g": 0.0, "fat_g": 0.0, "carbs_g": 0.0}
    for ingredient in ingredients:
        food = await session.get(Food, ingredient.food_id)
        nutrients = await session.get(FoodNutrient, ingredient.food_id)
        grams = float(ingredient.grams)
        kcal = _scale(nutrients.kcal_100g, grams) if nutrients else 0.0
        protein_g = _scale(nutrients.protein_100g, grams) if nutrients else 0.0
        fat_g = _scale(nutrients.fat_100g, grams) if nutrients else 0.0
        carbs_g = _scale(nutrients.carbs_100g, grams) if nutrients else 0.0
        totals["kcal"] += kcal
        totals["protein_g"] += protein_g
        totals["fat_g"] += fat_g
        totals["carbs_g"] += carbs_g
        ingredients_out.append(
            RecipeIngredientOut(
                id=ingredient.id,
                food_id=ingredient.food_id,
                name_es=food.name_es if food else "",
                grams=grams,
                kcal=kcal,
                protein_g=protein_g,
                fat_g=fat_g,
                carbs_g=carbs_g,
            )
        )

    totals = {k: round(v, 2) for k, v in totals.items()}
    servings = max(recipe.servings, 1)
    per_serving = {k: round(v / servings, 2) for k, v in totals.items()}

    return RecipeOut(
        id=recipe.id,
        name=recipe.name,
        internal_ean=recipe.internal_ean,
        image_url=user_images.image_url(f"/api/recipes/{recipe.id}", "recipe", recipe.id),
        servings=recipe.servings,
        prep_minutes=recipe.prep_minutes,
        instructions=recipe.instructions,
        ingredients=ingredients_out,
        totals=NutritionTotals(**totals),
        totals_per_serving=NutritionTotals(**per_serving),
        attribution=recipe.attribution,
    )


@router.post("", status_code=201)
async def create_recipe(
    body: RecipeIn,
    user_id: UUID = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_db),
) -> RecipeOut:
    recipe = Recipe(
        user_id=user_id,
        name=body.name,
        servings=body.servings,
        prep_minutes=body.prep_minutes,
        instructions=body.instructions,
    )
    session.add(recipe)
    await session.flush()
    await _ensure_internal_ean(session, recipe)

    for item in body.ingredients:
        session.add(
            RecipeIngredient(recipe_id=recipe.id, food_id=item.food_id, grams=item.grams)
        )

    await session.commit()
    await session.refresh(recipe)
    return await _to_out(session, recipe)


@router.get("")
async def list_recipes(
    user_id: UUID = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_db),
) -> list[RecipeSummaryOut]:
    recipes = await session.scalars(
        select(Recipe).where(Recipe.user_id == user_id).order_by(Recipe.created_at.desc())
    )
    return [
        RecipeSummaryOut(
            id=r.id,
            name=r.name,
            servings=r.servings,
            prep_minutes=r.prep_minutes,
            image_url=user_images.image_url(f"/api/recipes/{r.id}", "recipe", r.id),
        )
        for r in recipes
    ]


class CatalogRecipeOut(BaseModel):
    """Una receta del recetario compartido, con lo justo para la lista: la nutrición POR
    RACIÓN, que es como se decide si un plato encaja en tu día."""

    id: UUID
    name: str
    servings: int
    cuisine: str | None
    category: str | None
    image_url: str | None
    ingredient_count: int
    kcal_per_serving: float
    protein_g_per_serving: float
    fat_g_per_serving: float
    carbs_g_per_serving: float


class CatalogPageOut(BaseModel):
    items: list[CatalogRecipeOut]
    total: int
    cuisines: list[str]
    categories: list[str]


CATALOG_PAGE_SIZE = 24

# 190 de las 790 recetas del recetario vienen de TheMealDB sin cocina, porque la fuente no la
# trae. Inventarles una sería mentir, pero dejarlas sin etiqueta las volvía inalcanzables: el
# filtro de cocina no las enseñaba nunca. Con este valor se pueden pedir igual que las demás.
SIN_COCINA = "Sin especificar"


@router.get("/catalog")
async def list_catalog(
    q: str | None = None,
    cuisine: str | None = None,
    category: str | None = None,
    max_kcal: float | None = None,
    offset: int = 0,
    limit: int = CATALOG_PAGE_SIZE,
    _user_id: UUID = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_db),
) -> CatalogPageOut:
    """Recetario compartido: platos que no son de nadie y todo el mundo ve.

    Las calorías se calculan aquí sumando los `food_nutrients` de sus ingredientes (R9), no se
    guardan: si mañana se corrige un alimento del catálogo, la receta se corrige sola."""
    limit = max(1, min(limit, 60))
    filters = ["r.user_id IS NULL"]
    params: dict = {"limit": limit, "offset": max(0, offset)}
    if q and q.strip():
        filters.append("r.name ILIKE :q")
        params["q"] = f"%{q.strip()}%"
    if cuisine == SIN_COCINA:
        filters.append("r.cuisine IS NULL")
    elif cuisine:
        filters.append("r.cuisine = :cuisine")
        params["cuisine"] = cuisine
    if category:
        filters.append("r.category = :category")
        params["category"] = category
    where = " AND ".join(filters)

    having = ""
    if max_kcal is not None:
        params["max_kcal"] = max_kcal
        having = "HAVING COALESCE(SUM(n.kcal_100g * ri.grams / 100), 0) / r.servings <= :max_kcal"

    rows = (
        await session.execute(
            text(f"""
                SELECT r.id, r.name, r.servings, r.cuisine, r.category, r.image_url,
                       COUNT(ri.id) AS ingredient_count,
                       COALESCE(SUM(n.kcal_100g    * ri.grams / 100), 0) AS kcal,
                       COALESCE(SUM(n.protein_100g * ri.grams / 100), 0) AS protein_g,
                       COALESCE(SUM(n.fat_100g     * ri.grams / 100), 0) AS fat_g,
                       COALESCE(SUM(n.carbs_100g   * ri.grams / 100), 0) AS carbs_g
                FROM recipes r
                LEFT JOIN recipe_ingredients ri ON ri.recipe_id = r.id
                LEFT JOIN food_nutrients n ON n.food_id = ri.food_id
                WHERE {where}
                GROUP BY r.id
                {having}
                ORDER BY r.name
                LIMIT :limit OFFSET :offset
            """),
            params,
        )
    ).all()

    total = await session.scalar(
        text(f"SELECT count(*) FROM recipes r WHERE {where}"),
        {k: v for k, v in params.items() if k not in ("limit", "offset", "max_kcal")},
    )

    facets = (
        await session.execute(
            text("""
                SELECT DISTINCT cuisine, category FROM recipes
                WHERE user_id IS NULL
            """)
        )
    ).all()

    def _per_serving(value, servings: int) -> float:
        return round(float(value) / max(servings, 1), 1)

    return CatalogPageOut(
        items=[
            CatalogRecipeOut(
                id=r.id,
                name=r.name,
                servings=r.servings,
                cuisine=r.cuisine,
                category=r.category,
                image_url=r.image_url,
                ingredient_count=r.ingredient_count,
                kcal_per_serving=_per_serving(r.kcal, r.servings),
                protein_g_per_serving=_per_serving(r.protein_g, r.servings),
                fat_g_per_serving=_per_serving(r.fat_g, r.servings),
                carbs_g_per_serving=_per_serving(r.carbs_g, r.servings),
            )
            for r in rows
        ],
        total=total or 0,
        cuisines=_cuisine_facets(facets),
        categories=sorted({r.category for r in facets if r.category}),
    )


def _cuisine_facets(facets) -> list[str]:
    """Las cocinas, con «Sin especificar» al final si hay recetas que no la traen."""
    cuisines = sorted({r.cuisine for r in facets if r.cuisine})
    if any(r.cuisine is None for r in facets):
        cuisines.append(SIN_COCINA)
    return cuisines


@router.post("/{recipe_id}/copy", status_code=201)
async def copy_catalog_recipe(
    recipe_id: UUID,
    user_id: UUID = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_db),
) -> RecipeOut:
    """Guarda una receta del catálogo entre las tuyas, para poder ajustarla.

    Se copia en vez de enlazarla: el catálogo puede cambiar al reimportarlo, y lo que tú
    hayas ajustado — las raciones, un ingrediente que cambiaste — no puede depender de eso."""
    original = await _get_recipe(session, user_id, recipe_id, allow_catalog=True)
    if original.user_id is not None:
        raise AppError("RECIPE_NOT_IN_CATALOG", "Esa receta ya es tuya.", status_code=422)

    copy = Recipe(
        user_id=user_id,
        name=original.name,
        servings=original.servings,
        prep_minutes=original.prep_minutes,
        instructions=original.instructions,
        source="user",
        image_url=original.image_url,
        cuisine=original.cuisine,
        category=original.category,
        attribution=original.attribution,
    )
    session.add(copy)
    await session.flush()
    for ingredient in await _load_ingredients(session, original.id):
        session.add(
            RecipeIngredient(
                recipe_id=copy.id, food_id=ingredient.food_id, grams=ingredient.grams
            )
        )
    await session.commit()
    await session.refresh(copy)
    return await _to_out(session, copy)


@router.get("/by-ean/{ean}")
async def get_recipe_by_ean(
    ean: str,
    user_id: UUID = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_db),
) -> RecipeOut:
    """Resuelve el código de una etiqueta impresa a la receta del usuario."""
    recipe = await session.scalar(
        select(Recipe).where(Recipe.internal_ean == ean, Recipe.user_id == user_id)
    )
    if recipe is None:
        raise AppError("RECIPE_NOT_FOUND", "No existe esa receta.", status_code=404)
    return await _to_out(session, recipe)


@router.put("/{recipe_id}/image", status_code=204)
async def upload_recipe_image(
    recipe_id: UUID,
    file: UploadFile = File(...),
    user_id: UUID = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_db),
) -> None:
    """Foto de la receta (máx. 10 MB; se reescala a 1024 px y se quita el EXIF)."""
    await _get_recipe(session, user_id, recipe_id)
    await store_uploaded_image("recipe", recipe_id, file)


@router.get("/{recipe_id}/image")
async def get_recipe_image(
    recipe_id: UUID,
    user_id: UUID = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_db),
):
    await _get_recipe(session, user_id, recipe_id)
    return serve_image("recipe", recipe_id)


@router.delete("/{recipe_id}/image", status_code=204)
async def delete_recipe_image(
    recipe_id: UUID,
    user_id: UUID = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_db),
) -> None:
    await _get_recipe(session, user_id, recipe_id)
    user_images.delete_image("recipe", recipe_id)


@router.get("/{recipe_id}/label.svg")
async def get_recipe_label(
    recipe_id: UUID,
    user_id: UUID = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_db),
) -> Response:
    """Etiqueta imprimible de la receta: código de barras, nombre y raciones."""
    recipe = await _get_recipe(session, user_id, recipe_id)
    ean = await _ensure_internal_ean(session, recipe)
    svg = ean13_svg(ean, recipe.name[:40], f"{recipe.servings} raciones")
    return Response(content=svg, media_type="image/svg+xml")


@router.get("/{recipe_id}")
async def get_recipe(
    recipe_id: UUID,
    user_id: UUID = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_db),
) -> RecipeOut:
    recipe = await _get_recipe(session, user_id, recipe_id, allow_catalog=True)
    if recipe.user_id is not None:
        # El EAN interno es para imprimir la etiqueta de TU receta: una del catálogo no
        # se etiqueta ni se guarda con un código propio.
        await _ensure_internal_ean(session, recipe)
    return await _to_out(session, recipe)


@router.patch("/{recipe_id}")
async def update_recipe(
    recipe_id: UUID,
    body: RecipePatch,
    user_id: UUID = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_db),
) -> RecipeOut:
    recipe = await _get_recipe(session, user_id, recipe_id)
    if body.name is not None:
        recipe.name = body.name
    if body.servings is not None:
        recipe.servings = body.servings
    if body.prep_minutes is not None:
        recipe.prep_minutes = body.prep_minutes
    if body.instructions is not None:
        recipe.instructions = body.instructions
    await session.commit()
    await session.refresh(recipe)
    return await _to_out(session, recipe)


@router.delete("/{recipe_id}", status_code=204)
async def delete_recipe(
    recipe_id: UUID,
    user_id: UUID = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_db),
) -> None:
    recipe = await _get_recipe(session, user_id, recipe_id)
    await session.delete(recipe)
    await session.commit()
    user_images.delete_image("recipe", recipe_id)


@router.post("/{recipe_id}/ingredients", status_code=201)
async def add_ingredient(
    recipe_id: UUID,
    body: RecipeIngredientIn,
    user_id: UUID = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_db),
) -> RecipeOut:
    recipe = await _get_recipe(session, user_id, recipe_id)
    session.add(RecipeIngredient(recipe_id=recipe.id, food_id=body.food_id, grams=body.grams))
    await session.commit()
    await session.refresh(recipe)
    return await _to_out(session, recipe)


@router.patch("/{recipe_id}/ingredients/{ingredient_id}")
async def update_ingredient(
    recipe_id: UUID,
    ingredient_id: UUID,
    body: RecipeIngredientIn,
    user_id: UUID = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_db),
) -> RecipeOut:
    recipe = await _get_recipe(session, user_id, recipe_id)
    ingredient = await session.get(RecipeIngredient, ingredient_id)
    if ingredient is None or ingredient.recipe_id != recipe.id:
        raise AppError(
            "RECIPE_INGREDIENT_NOT_FOUND", "No existe ese ingrediente.", status_code=404
        )
    ingredient.food_id = body.food_id
    ingredient.grams = body.grams
    await session.commit()
    await session.refresh(recipe)
    return await _to_out(session, recipe)


@router.delete("/{recipe_id}/ingredients/{ingredient_id}", status_code=204)
async def remove_ingredient(
    recipe_id: UUID,
    ingredient_id: UUID,
    user_id: UUID = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_db),
) -> None:
    recipe = await _get_recipe(session, user_id, recipe_id)
    ingredient = await session.get(RecipeIngredient, ingredient_id)
    if ingredient is None or ingredient.recipe_id != recipe.id:
        raise AppError(
            "RECIPE_INGREDIENT_NOT_FOUND", "No existe ese ingrediente.", status_code=404
        )
    await session.delete(ingredient)
    await session.commit()


class RecipeImportIn(BaseModel):
    url: str = Field(min_length=1, max_length=2000)


@router.post("/import-url", status_code=202)
async def create_recipe_import_request(
    body: RecipeImportIn,
    user_id: UUID = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_db),
) -> AiSessionOut:
    """Importación de recetas desde URL (sección 20). No guarda nada
    todavía — el resultado (vía `GET /ai/sessions/{id}`, mismo patrón de
    polling que el resto de iafood) es una receta EN BORRADOR; el usuario
    la revisa y la confirma llamando a `POST /recipes` normal."""
    await require_ai_processing_consent(session, user_id)
    try:
        await check_and_consume_quota(user_id, scope="recipe_import")
    except QuotaExceeded as exc:
        raise AppError(
            exc.code, exc.message, status_code=429, details={"reset_at": reset_at_iso()}
        ) from exc

    ai_session = await request_recipe_import(session, user_id, url=body.url)
    return ai_session_to_out(ai_session)
