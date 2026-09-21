# ruff: noqa: E501
"""Taxonomía para filtrar el catálogo de alimentos: supermercado, tipo de alimento y tipo de
nutrición. Solo usa la biblioteca estándar (más `food_groups`, que también) porque la importan la
API y el indexador del ETL (`etl/index.py`): así el filtro de la web y el índice de Meilisearch
hablan siempre de lo mismo.

Nada de esto inventa datos (R9): el supermercado sale de la marca que declara Open Food Facts, el
tipo de alimento de las reglas de `food_groups` y las etiquetas de nutrición de los valores por
100 g del propio alimento, con los umbrales de las declaraciones nutricionales del Reglamento (CE)
1924/2006 cuando existen. Si falta el dato que hace falta (p. ej. los azúcares), la etiqueta no se
pone.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass

from myfood.domain import food_groups as g


def _normalize(text: str) -> str:
    stripped = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in stripped if not unicodedata.combining(c)).strip()


# --------------------------------------------------------------------------- supermercados


@dataclass(frozen=True)
class Supermarket:
    code: str
    label: str
    # Etiquetas de marca (sin acentos, en minúscula) que identifican a la cadena: su nombre y sus
    # marcas blancas. Una etiqueta coincide si es igual o empieza por ella seguida de espacio.
    aliases: tuple[str, ...]


SUPERMARKETS: tuple[Supermarket, ...] = (
    Supermarket("mercadona", "Mercadona", ("mercadona", "hacendado", "deliplus", "bosque verde", "compy", "delisano")),
    Supermarket("carrefour", "Carrefour", ("carrefour", "crf")),
    Supermarket("lidl", "Lidl", ("lidl", "milbona", "vemondo")),
    Supermarket("dia", "Dia", ("dia",)),
    Supermarket("alcampo", "Alcampo (Auchan)", ("alcampo", "auchan")),
    Supermarket("eroski", "Eroski", ("eroski", "seleqtia")),
    Supermarket("consum", "Consum", ("consum",)),
    Supermarket("aldi", "Aldi", ("aldi",)),
    Supermarket("el_corte_ingles", "El Corte Inglés", ("el corte ingles", "hipercor")),
    Supermarket("bonpreu", "Bonpreu", ("bonpreu", "esclat")),
    Supermarket("condis", "Condis", ("condis",)),
    Supermarket("froiz", "Froiz", ("froiz",)),
    Supermarket("spar", "Spar", ("spar",)),
    Supermarket("masymas", "Masymas", ("masymas", "mas y mas")),
    Supermarket("ahorramas", "Ahorramás", ("ahorramas",)),
    Supermarket("caprabo", "Caprabo", ("caprabo",)),
    Supermarket("gadis", "Gadis", ("gadis",)),
    Supermarket("bonarea", "bonÀrea", ("bonarea",)),
)
SUPERMARKET_LABELS: dict[str, str] = {s.code: s.label for s in SUPERMARKETS}


def _alias_matches(label: str, alias: str) -> bool:
    return label == alias or label.startswith(alias + " ")


def supermarket_for_brand(brand: str | None) -> str | None:
    """Código de la cadena a la que pertenece un producto según su campo de marca de OFF, que es
    una lista separada por comas («Hacendado, MERCADONA», «Milbona, Lidl», «Auchan, Gullón»).
    `None` si la marca no es de ninguna cadena conocida (una marca de fabricante suelta)."""
    if not brand:
        return None
    labels = [_normalize(part) for part in brand.split(",")]
    for label in labels:
        if not label:
            continue
        for market in SUPERMARKETS:
            if any(_alias_matches(label, alias) for alias in market.aliases):
                return market.code
    return None


# --------------------------------------------------------------------------- tipo de alimento

FOOD_TYPE_LABELS: dict[str, str] = {
    g.MEAT: "Carnes",
    g.PROCESSED_MEAT: "Embutidos y fiambres",
    g.FISH: "Pescados y mariscos",
    g.EGG: "Huevos",
    g.DAIRY: "Lácteos",
    g.CHEESE: "Quesos",
    g.LEGUME: "Legumbres",
    g.NUTS: "Frutos secos",
    g.VEGETABLE: "Verduras y hortalizas",
    g.FRUIT: "Frutas",
    g.GRAIN: "Arroz, pasta y cereales",
    g.CEREAL: "Cereales de desayuno",
    g.BREAD: "Pan y panadería",
    g.OIL_FAT: "Aceites y grasas",
    g.SWEET: "Dulces y bollería",
    g.BEVERAGE: "Bebidas",
    g.SNACK: "Snacks y aperitivos",
    g.PREPARED: "Platos preparados",
}


def food_type_for(name: str | None, category: str | None) -> str | None:
    """Tipo de alimento (código de `food_groups`) o `None` si las reglas no lo reconocen: nunca
    se inventa uno, y «otros» no es un tipo que se pueda filtrar."""
    group = g.classify_food(name, category)
    return group if group in FOOD_TYPE_LABELS else None


# --------------------------------------------------------------------------- nutrición


@dataclass(frozen=True)
class NutritionTag:
    code: str
    label: str
    description: str


NUTRITION_TAGS: tuple[NutritionTag, ...] = (
    NutritionTag("high_protein", "Alto en proteína", "Al menos el 20 % de la energía viene de la proteína (y 8 g o más por 100 g)."),
    NutritionTag("low_calorie", "Bajo en calorías", "40 kcal o menos por 100 g."),
    NutritionTag("low_fat", "Bajo en grasa", "3 g de grasa o menos por 100 g."),
    NutritionTag("low_saturated", "Bajo en grasa saturada", "1,5 g de saturadas o menos por 100 g."),
    NutritionTag("low_carb", "Bajo en hidratos", "5 g de hidratos de carbono o menos por 100 g."),
    NutritionTag("low_sugar", "Bajo en azúcares", "5 g de azúcares o menos por 100 g."),
    NutritionTag("sugar_free", "Sin azúcares", "0,5 g de azúcares o menos por 100 g."),
    NutritionTag("high_fiber", "Rico en fibra", "6 g de fibra o más por 100 g."),
    NutritionTag("low_salt", "Bajo en sal", "0,3 g de sal o menos por 100 g."),
    NutritionTag("nutriscore_ab", "Nutri-Score A o B", "Producto con Nutri-Score A o B."),
    NutritionTag("minimally_processed", "Poco procesado", "NOVA 1 o 2 (sin procesar o ingredientes culinarios)."),
)
NUTRITION_TAG_LABELS: dict[str, str] = {t.code: t.label for t in NUTRITION_TAGS}


def nutrition_tags(
    *,
    kcal: float | None,
    protein: float | None,
    fat: float | None,
    carbs: float | None,
    saturated: float | None = None,
    sugars: float | None = None,
    fiber: float | None = None,
    salt: float | None = None,
    nutriscore: str | None = None,
    nova: int | None = None,
) -> list[str]:
    """Etiquetas de nutrición de un alimento (valores por 100 g). Una etiqueta solo se pone si
    el dato que la decide existe: un azúcar desconocido no es «sin azúcares»."""
    tags: list[str] = []
    if kcal is not None and protein is not None and kcal > 0 and protein >= 8 and protein * 4 >= 0.2 * kcal:
        tags.append("high_protein")
    if kcal is not None and kcal <= 40:
        tags.append("low_calorie")
    if fat is not None and fat <= 3:
        tags.append("low_fat")
    if saturated is not None and saturated <= 1.5:
        tags.append("low_saturated")
    if carbs is not None and carbs <= 5:
        tags.append("low_carb")
    if sugars is not None and sugars <= 5:
        tags.append("low_sugar")
    if sugars is not None and sugars <= 0.5:
        tags.append("sugar_free")
    if fiber is not None and fiber >= 6:
        tags.append("high_fiber")
    if salt is not None and salt <= 0.3:
        tags.append("low_salt")
    if nutriscore is not None and nutriscore.lower() in ("a", "b"):
        tags.append("nutriscore_ab")
    if nova is not None and nova in (1, 2):
        tags.append("minimally_processed")
    return tags

