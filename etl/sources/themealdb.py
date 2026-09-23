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


# TheMealDB escribe la cocina en inglés y sin criterio fijo: unas veces el gentilicio
# («Spanish») y otras el país («France»). Se traduce al gentilicio femenino porque en la
# pantalla acompaña a la palabra «cocina»: «cocina española», «cocina tailandesa».
AREA_ES = {
    "Algerian": "Argelina",
    "American": "Estadounidense",
    "Argentina": "Argentina",
    "Argentine": "Argentina",
    "Australian": "Australiana",
    "British": "Británica",
    "Canadian": "Canadiense",
    "Chinese": "China",
    "Croatian": "Croata",
    "Dutch": "Holandesa",
    "Egyptian": "Egipcia",
    "Filipino": "Filipina",
    "France": "Francesa",
    "French": "Francesa",
    "Greek": "Griega",
    "India": "India",
    "Indian": "India",
    "Irish": "Irlandesa",
    "Italian": "Italiana",
    "Jamaican": "Jamaicana",
    "Japanese": "Japonesa",
    "Kenyan": "Keniana",
    "Malaysian": "Malasia",
    "Mexican": "Mexicana",
    "Moroccan": "Marroquí",
    "Netherlands": "Holandesa",
    "Norway": "Noruega",
    "Norwegian": "Noruega",
    "Polish": "Polaca",
    "Portuguese": "Portuguesa",
    "Russian": "Rusa",
    "Saudi Arabian": "Saudí",
    "Slovak": "Eslovaca",
    "Slovakia": "Eslovaca",
    "Spanish": "Española",
    "Syrian": "Siria",
    "Thai": "Tailandesa",
    "Tunisian": "Tunecina",
    "Turkish": "Turca",
    "Ukrainian": "Ucraniana",
    "United States": "Estadounidense",
    "Uruguayan": "Uruguaya",
    "Venezuela": "Venezolana",
    "Venezuelan": "Venezolana",
    "Vietnamese": "Vietnamita",
}

# El vocabulario de categorías está cerrado y no cambia, así que se traduce con una tabla y no
# gastando tokens: son catorce palabras que salen en los filtros de la pantalla.
CATEGORY_ES = {
    "Beef": "Ternera",
    "Breakfast": "Desayuno",
    "Chicken": "Pollo",
    "Dessert": "Postre",
    "Goat": "Cabrito",
    "Lamb": "Cordero",
    "Miscellaneous": "Varios",
    "Pasta": "Pasta",
    "Pork": "Cerdo",
    "Seafood": "Pescado y marisco",
    "Side": "Guarnición",
    "Starter": "Entrante",
    "Vegan": "Vegana",
    "Vegetarian": "Vegetariana",
}

# Lo que la tabla no conocía la última vez que se importó. Se deja a la vista en vez de
# traducirlo a medias: un nombre en inglés en los filtros se ve, y una traducción inventada no.
SIN_TRADUCIR: set[str] = set()


def _translate(value: str | None, table: dict[str, str]) -> str | None:
    """El término en español, o el original apuntado para que se note que falta."""
    if not value:
        return None
    spanish = table.get(value)
    if spanish is None:
        SIN_TRADUCIR.add(value)
        return value
    return spanish


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
        category=_translate(_clean(meal.get("strCategory")), CATEGORY_ES),
        cuisine=_translate(_clean(meal.get("strArea")), AREA_ES),
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
