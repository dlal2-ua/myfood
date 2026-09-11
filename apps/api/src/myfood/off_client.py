"""Cliente de la API en vivo de Open Food Facts, para el flujo de escaneo de
código de barras (sección 11.2: "no depender de las APIs en vivo para el
catálogo... las APIs solo como *fallback* para EAN no encontrados en local").

Duplica intencionadamente el mapeo de nutrientes y las reglas de descarte de
`etl/sources/off.py` / `etl/transform/nutrient_map.py` — `apps/api` y `etl`
son proyectos Python independientes (no se importan entre sí). Si cambia el
mapeo en uno, hay que replicarlo a mano en el otro.
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx

from myfood.config import get_settings

settings = get_settings()

PRODUCT_URL = "https://world.openfoodfacts.org/api/v2/product/{barcode}.json"
_FIELDS = (
    "code,product_name,product_name_es,brands,categories_tags,quantity,"
    "serving_size,serving_quantity,nutriscore_grade,nova_group,ecoscore_grade,nutriments"
)

_MACRO_KEYS = {
    "energy-kcal_100g": "kcal_100g",
    "proteins_100g": "protein_100g",
    "fat_100g": "fat_100g",
    "saturated-fat_100g": "saturated_100g",
    "carbohydrates_100g": "carbs_100g",
    "sugars_100g": "sugars_100g",
    "fiber_100g": "fiber_100g",
    "salt_100g": "salt_100g",
}

_MICRO_KEYS = {
    "vitamin-a_100g": "vitamin_a_ug",
    "vitamin-c_100g": "vitamin_c_mg",
    "vitamin-d_100g": "vitamin_d_ug",
    "vitamin-e_100g": "vitamin_e_mg",
    "vitamin-k_100g": "vitamin_k_ug",
    "vitamin-b1_100g": "thiamin_mg",
    "vitamin-b2_100g": "riboflavin_mg",
    "vitamin-pp_100g": "niacin_mg",
    "vitamin-b6_100g": "vitamin_b6_mg",
    "vitamin-b9_100g": "folate_ug",
    "vitamin-b12_100g": "vitamin_b12_ug",
    "calcium_100g": "calcium_mg",
    "iron_100g": "iron_mg",
    "magnesium_100g": "magnesium_mg",
    "phosphorus_100g": "phosphorus_mg",
    "potassium_100g": "potassium_mg",
    "zinc_100g": "zinc_mg",
}

_VALID_GRADES = {"a", "b", "c", "d", "e"}


def _grade(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    v = value.strip().lower()
    return v if v in _VALID_GRADES else None


def _nova(value: object) -> int | None:
    try:
        n = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return n if 1 <= n <= 4 else None


def _per_100g(nutriments: dict, key: str, serving_quantity: float | None) -> float | None:
    value_100g = nutriments.get(f"{key}_100g")
    if value_100g is not None:
        return value_100g
    value_serving = nutriments.get(f"{key}_serving")
    if value_serving is not None and serving_quantity:
        return value_serving * 100 / serving_quantity
    return None


def _first_category(categories_tags: list | None) -> str | None:
    if not categories_tags:
        return None
    return categories_tags[-1].split(":", 1)[-1].replace("-", " ")


@dataclass
class OffProduct:
    barcode_ean: str
    name_es: str
    name_en: str | None
    brand: str | None
    category: str | None
    serving_size_g: float | None
    serving_label: str | None
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


def parse_product(raw: dict, barcode: str) -> OffProduct | None:
    """Misma lógica de mapeo/descarte que `etl/sources/off.py::parse_food`
    (sección 11.2) — nunca se relaja para un producto individual solo porque
    viene de un escaneo en vivo. `None` = no pasa la validación; el llamador
    lo trata igual que "no encontrado" (nunca se inventa el dato que falta,
    R9), y ofrece el alta manual."""
    name = (raw.get("product_name_es") or raw.get("product_name") or "").strip()
    if not name:
        return None

    nutriments = raw.get("nutriments") or {}
    serving_quantity = raw.get("serving_quantity")

    macros: dict[str, float] = {}
    for off_key, field_name in _MACRO_KEYS.items():
        base_key = off_key.removesuffix("_100g")
        value = _per_100g(nutriments, base_key, serving_quantity)
        if value is not None:
            macros[field_name] = value

    kcal_100g = macros.get("kcal_100g")
    if kcal_100g is None or kcal_100g > 900:
        return None

    protein = macros.get("protein_100g", 0.0)
    fat = macros.get("fat_100g", 0.0)
    carbs = macros.get("carbs_100g", 0.0)
    if protein + fat + carbs > 100:
        return None

    micros: dict[str, float] = {}
    for off_key, key in _MICRO_KEYS.items():
        base_key = off_key.removesuffix("_100g")
        value = _per_100g(nutriments, base_key, serving_quantity)
        if value is not None:
            micros[key] = value

    return OffProduct(
        barcode_ean=barcode,
        name_es=name,
        name_en=raw.get("product_name") if raw.get("product_name") != name else None,
        brand=raw.get("brands"),
        category=_first_category(raw.get("categories_tags")),
        serving_size_g=serving_quantity,
        serving_label=raw.get("serving_size"),
        nutriscore_grade=_grade(raw.get("nutriscore_grade")),
        nova_group=_nova(raw.get("nova_group")),
        ecoscore_grade=_grade(raw.get("ecoscore_grade")),
        kcal_100g=kcal_100g,
        protein_100g=protein,
        fat_100g=fat,
        saturated_100g=macros.get("saturated_100g"),
        carbs_100g=carbs,
        sugars_100g=macros.get("sugars_100g"),
        fiber_100g=macros.get("fiber_100g"),
        salt_100g=macros.get("salt_100g"),
        micros=micros,
    )


async def fetch_product(barcode: str, client: httpx.AsyncClient | None = None) -> OffProduct | None:
    """Consulta la API en vivo de OFF para un único código de barras — el
    *fallback* de sección 11.2 cuando el catálogo local no tiene el EAN
    escaneado. Nunca se usa para carga masiva (eso es el ETL, `etl/sources/off.py`).

    Acepta un `client` inyectado para tests (sin tocar la red real).
    """
    url = PRODUCT_URL.format(barcode=barcode)
    owns_client = client is None
    if client is None:
        client = httpx.AsyncClient(headers={"User-Agent": settings.off_user_agent}, timeout=10.0)
    try:
        resp = await client.get(url, params={"fields": _FIELDS})
        if resp.status_code != 200:
            return None
        data = resp.json()
    finally:
        if owns_client:
            await client.aclose()

    if data.get("status") != 1:
        return None
    return parse_product(data.get("product") or {}, barcode)
