"""Recetas de TheMealDB: platos con sus ingredientes, sus cantidades y sus pasos.

MyFood sabía calcular nutrición pero no tenía recetario: solo lo que cada uno escribía a mano.
Esta fuente trae un catálogo de platos reales para inspirarse y para que el planificador pueda
proponer «pollo teriyaki al horno» en vez de una lista de alimentos sueltos.

De la API se toma el PLATO, no sus números: ingredientes, cantidades en medidas caseras, pasos
y foto. La nutrición la calcula MyFood sumando sus propios `food_nutrients`, igual que con
cualquier receta escrita a mano (R9) — así ninguna caloría viene de una fuente que no se pueda
comprobar.

Sus condiciones permiten copiar y guardar lo que devuelve la API usando los puntos de acceso
oficiales, y piden citar la fuente: se guarda en `recipes.attribution`.
"""

from __future__ import annotations

import string
from dataclasses import dataclass, field

import httpx

# Clave de desarrollo pública que la propia documentación publica para pruebas.
API_KEY = "1"
BASE_URL = f"https://www.themealdb.com/api/json/v1/{API_KEY}"
ATTRIBUTION = "Receta de TheMealDB (themealdb.com)"

# Cada plato trae hasta 20 pares ingrediente/cantidad en campos numerados.
MAX_INGREDIENT_SLOTS = 20
REQUEST_TIMEOUT = 30.0


@dataclass
class RawIngredient:
    name: str
    measure: str


@dataclass
class RawRecipe:
    source_id: str
    name: str
    category: str | None
    cuisine: str | None
    instructions: str
    image_url: str | None
    ingredients: list[RawIngredient] = field(default_factory=list)


def _clean(value: str | None) -> str:
    return (value or "").strip()


def parse_meal(meal: dict) -> RawRecipe | None:
    """Convierte un plato de la API. Devuelve `None` si le falta lo imprescindible: sin
    ingredientes no se puede calcular nada, y sin pasos no es una receta."""
    name = _clean(meal.get("strMeal"))
    instructions = _clean(meal.get("strInstructions"))
    source_id = _clean(meal.get("idMeal"))
    if not name or not instructions or not source_id:
        return None

    ingredients = []
    for i in range(1, MAX_INGREDIENT_SLOTS + 1):
        ingredient = _clean(meal.get(f"strIngredient{i}"))
        if not ingredient:
            continue
        measure = _clean(meal.get(f"strMeasure{i}"))
        ingredients.append(RawIngredient(name=ingredient, measure=measure))
    if not ingredients:
        return None

    return RawRecipe(
        source_id=source_id,
        name=name,
        category=_clean(meal.get("strCategory")) or None,
        cuisine=_clean(meal.get("strArea")) or None,
        instructions=instructions,
        image_url=_clean(meal.get("strMealThumb")) or None,
        ingredients=ingredients,
    )


def fetch_all(client: httpx.Client | None = None) -> list[RawRecipe]:
    """Todo el catálogo, recorriendo la búsqueda por primera letra.

    Es la forma que ofrece la clave de desarrollo de llegar a todos los platos: el listado
    completo está reservado a los suscriptores. Se recorre una letra por petición, no un
    barrido de la web, que es lo que sus condiciones prohíben."""
    own_client = client is None
    client = client or httpx.Client(timeout=REQUEST_TIMEOUT)
    seen: dict[str, RawRecipe] = {}
    try:
        for letter in string.ascii_lowercase:
            response = client.get(f"{BASE_URL}/search.php", params={"f": letter})
            response.raise_for_status()
            for meal in response.json().get("meals") or []:
                recipe = parse_meal(meal)
                # Un plato puede salir en varias letras si cambian el nombre: la clave es su id.
                if recipe is not None:
                    seen[recipe.source_id] = recipe
    finally:
        if own_client:
            client.close()
    return list(seen.values())
