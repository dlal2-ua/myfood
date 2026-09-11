"""Open Food Facts — España (documento 2, sección 11).

Descarga el dump JSONL completo (público, ~13 GB comprimido) y lo filtra
con DuckDB por `countries_tags` antes de cargar nada — nunca se carga el
fichero entero en memoria ni en Postgres (sección 11.2).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import duckdb
import httpx

from etl.db import LoadStats, ParsedFood, get_connection, upsert_foods
from etl.rejected import Rejection, log_rejections
from etl.transform.nutrient_map import OFF_MACRO_KEYS, OFF_MICRO_KEYS

DUMP_URL = "https://static.openfoodfacts.org/data/openfoodfacts-products.jsonl.gz"
QUALITY_RANK = 5
CACHE_DIR = Path(__file__).parent.parent / ".cache"

_DUCKDB_COLUMNS = {
    "code": "VARCHAR",
    "product_name": "VARCHAR",
    "product_name_es": "VARCHAR",
    "brands": "VARCHAR",
    "categories_tags": "VARCHAR[]",
    "quantity": "VARCHAR",
    "serving_size": "VARCHAR",
    "serving_quantity": "DOUBLE",
    "nutriscore_grade": "VARCHAR",
    "nova_group": "INTEGER",
    "ecoscore_grade": "VARCHAR",
    "countries_tags": "VARCHAR[]",
    "nutriments": "JSON",
}


def download(cache_dir: Path = CACHE_DIR) -> Path:
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = cache_dir / "off-products.jsonl.gz"
    if not path.exists():
        with httpx.stream(
            "GET", DUMP_URL, headers={"User-Agent": "MyFood/1.0 (dev@example.com)"}, timeout=None
        ) as resp:
            resp.raise_for_status()
            with path.open("wb") as f:
                for chunk in resp.iter_bytes(chunk_size=1024 * 1024):
                    f.write(chunk)
    return path


def filter_spain(dump_path: Path, output_path: Path, country: str = "en:spain") -> int:
    """Filtra el dump completo con DuckDB, sin cargarlo en memoria (sección 11.2).

    Investigado el 2026-09-11: un producto con `nutriments` vacío al filtrar
    parecía un bug de DuckDB (el mismo código, vía la API pública de OFF,
    devuelve nutrientes completos). Verificado leyendo la línea cruda del
    dump directamente con `gzip`/`json` de la librería estándar, sin DuckDB
    de por medio: el dump estático **no tiene** `nutriments` para ese
    producto — su `last_modified_t` es posterior a la generación del dump.
    No es un bug de lectura, es la desincronización normal entre el dump
    diario y los datos en vivo (esperable, no evitable). DuckDB lee el
    fichero correctamente tal cual está.
    """
    columns_sql = ", ".join(f"'{k}': '{v}'" for k, v in _DUCKDB_COLUMNS.items())
    query = f"""
    COPY (
        SELECT code, product_name, product_name_es, brands, quantity,
               serving_size, serving_quantity, nutriscore_grade, nova_group,
               ecoscore_grade, categories_tags, nutriments
        FROM read_ndjson(
            '{dump_path}',
            columns={{{columns_sql}}},
            ignore_errors=true
        )
        WHERE list_contains(countries_tags, '{country}')
    ) TO '{output_path}' (FORMAT JSON)
    """
    con = duckdb.connect()
    con.execute(query)
    con.close()

    with output_path.open(encoding="utf-8") as f:
        return sum(1 for _ in f)


_VALID_GRADES = {"a", "b", "c", "d", "e"}


def _grade(value: str | None) -> str | None:
    """Nutri-Score/Eco-Score son CHAR(1) a-e — OFF también usa 'unknown',
    'not-applicable' u otros valores no puntuables; se descartan sin más
    (nunca se inventa una nota), nunca se pasan tal cual a la BD."""
    if value is None:
        return None
    value = value.strip().lower()
    return value if value in _VALID_GRADES else None


def _nova(value) -> int | None:
    try:
        n = int(value)
    except (TypeError, ValueError):
        return None
    return n if 1 <= n <= 4 else None


def _first_category(categories_tags: list | None) -> str | None:
    if not categories_tags:
        return None
    # 'en:dairies' -> 'dairies'
    return categories_tags[-1].split(":", 1)[-1].replace("-", " ")


def _per_100g(nutriments: dict, key: str, serving_quantity: float | None) -> float | None:
    value_100g = nutriments.get(f"{key}_100g")
    if value_100g is not None:
        return value_100g
    value_serving = nutriments.get(f"{key}_serving")
    if value_serving is not None and serving_quantity:
        return value_serving * 100 / serving_quantity
    return None


def parse_food(raw: dict) -> ParsedFood | Rejection:
    """Transforma un registro crudo de OFF. Función pura — sin I/O (testeable)."""
    barcode = str(raw.get("code") or "").strip()
    name = (raw.get("product_name_es") or raw.get("product_name") or "").strip()
    if not barcode:
        return Rejection("off", None, name or None, "MISSING_BARCODE")
    if not name:
        return Rejection("off", barcode, None, "MISSING_NAME")

    nutriments = raw.get("nutriments") or {}
    serving_quantity = raw.get("serving_quantity")

    macros = {}
    for off_key, field_name in OFF_MACRO_KEYS.items():
        base_key = off_key.removesuffix("_100g")
        value = _per_100g(nutriments, base_key, serving_quantity)
        if value is not None:
            macros[field_name] = value

    kcal_100g = macros.get("kcal_100g")
    if kcal_100g is None:
        return Rejection("off", barcode, name, "MISSING_KCAL")
    if kcal_100g > 900:
        return Rejection("off", barcode, name, "KCAL_OUT_OF_RANGE")

    protein = macros.get("protein_100g", 0.0)
    fat = macros.get("fat_100g", 0.0)
    carbs = macros.get("carbs_100g", 0.0)
    if protein + fat + carbs > 100:
        return Rejection("off", barcode, name, "MACROS_EXCEED_100G")

    micros = {}
    for off_key, key in OFF_MICRO_KEYS.items():
        base_key = off_key.removesuffix("_100g")
        value = _per_100g(nutriments, base_key, serving_quantity)
        if value is not None:
            micros[key] = value

    return ParsedFood(
        source="off",
        source_id=barcode,
        license="ODbL",
        attribution="Open Food Facts",
        kind="branded",
        barcode_ean=barcode,
        name_es=name,
        name_en=raw.get("product_name") if raw.get("product_name") != name else None,
        brand=raw.get("brands"),
        category=_first_category(raw.get("categories_tags")),
        serving_size_g=serving_quantity,
        serving_label=raw.get("serving_size"),
        quality_rank=QUALITY_RANK,
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


@dataclass
class OffLoadResult:
    stats: LoadStats
    rejected_path: Path | None


def load(dump_path: Path | None = None, filtered_path: Path | None = None) -> OffLoadResult:
    filtered = filtered_path or (CACHE_DIR / "off_spain.jsonl")
    if not filtered.exists():
        dump = dump_path or download()
        filter_spain(dump, filtered)

    parsed: list[ParsedFood] = []
    rejections: list[Rejection] = []
    read = 0
    with filtered.open(encoding="utf-8") as f:
        for line in f:
            read += 1
            raw = json.loads(line)
            result = parse_food(raw)
            if isinstance(result, Rejection):
                rejections.append(result)
            else:
                parsed.append(result)

    stats = LoadStats(read=read, rejected=len(rejections))

    conn = get_connection()
    try:
        stats.upserted = upsert_foods(conn, parsed)
    finally:
        conn.close()

    rejected_path = log_rejections("off", rejections) if rejections else None
    return OffLoadResult(stats=stats, rejected_path=rejected_path)
