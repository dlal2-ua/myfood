"""USDA Foundation Foods y SR Legacy (documento 2, sección 11).

Ambas fuentes ya vienen normalizadas por 100 g — a diferencia de Open Food
Facts, no hace falta ninguna conversión de porción (sección 11.2).

Descarga: https://fdc.nal.usda.gov/download-datasets/ (verificado 2026-09-11,
el dominio real de los ficheros es fdc.nal.usda.gov, no www.usda.gov).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from zipfile import ZipFile

import httpx

from etl.db import LoadStats, ParsedFood, get_connection, upsert_foods
from etl.rejected import Rejection, log_rejections
from etl.transform.nutrient_map import (
    USDA_MACRO_IDS,
    USDA_MICRO_IDS,
    USDA_SODIUM_ID,
    USDA_SUGARS_ID_PRIORITY,
)

USDASource = Literal["usda_foundation", "usda_sr"]

_DOWNLOAD_URLS: dict[USDASource, str] = {
    "usda_foundation": (
        "https://fdc.nal.usda.gov/fdc-datasets/"
        "FoodData_Central_foundation_food_json_2026-04-30.zip"
    ),
    "usda_sr": (
        "https://fdc.nal.usda.gov/fdc-datasets/FoodData_Central_sr_legacy_food_json_2018-04.zip"
    ),
}
_JSON_ROOT_KEY: dict[USDASource, str] = {
    "usda_foundation": "FoundationFoods",
    "usda_sr": "SRLegacyFoods",
}
_QUALITY_RANK: dict[USDASource, int] = {"usda_foundation": 1, "usda_sr": 2}

CACHE_DIR = Path(__file__).parent.parent / ".cache"


def download(source: USDASource, cache_dir: Path = CACHE_DIR) -> Path:
    """Descarga y descomprime el dataset si no está ya en caché local."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    zip_path = cache_dir / f"{source}.zip"
    if not zip_path.exists():
        with httpx.stream(
            "GET", _DOWNLOAD_URLS[source], headers={"User-Agent": "Mozilla/5.0"}, timeout=120
        ) as resp:
            resp.raise_for_status()
            with zip_path.open("wb") as f:
                for chunk in resp.iter_bytes():
                    f.write(chunk)

    with ZipFile(zip_path) as zf:
        json_name = next(n for n in zf.namelist() if n.endswith(".json"))
        json_path = cache_dir / f"{source}.json"
        if not json_path.exists():
            zf.extract(json_name, cache_dir)
            (cache_dir / json_name).rename(json_path)
    return json_path


def _sugars_100g(nutrient_amounts: dict[int, float]) -> float | None:
    for nid in USDA_SUGARS_ID_PRIORITY:
        if nid in nutrient_amounts:
            return nutrient_amounts[nid]
    return None


def parse_food(raw: dict, source: USDASource) -> ParsedFood | Rejection:
    """Transforma un registro crudo de USDA. Función pura — sin I/O (testeable)."""
    if raw is None:
        return Rejection(source, None, None, "NULL_RECORD")

    source_id = str(raw.get("fdcId"))
    name = raw.get("description")
    if not name:
        return Rejection(source, source_id, None, "MISSING_NAME")

    nutrient_amounts: dict[int, float] = {}
    for n in raw.get("foodNutrients") or []:
        nutrient = n.get("nutrient")
        amount = n.get("amount")
        if nutrient is None or amount is None:
            continue
        nutrient_amounts[nutrient["id"]] = amount

    macros = {
        field_name: nutrient_amounts[nid]
        for nid, field_name in USDA_MACRO_IDS.items()
        if nid in nutrient_amounts
    }

    kcal_100g = macros.get("kcal_100g")
    if kcal_100g is None:
        return Rejection(source, source_id, name, "MISSING_KCAL")
    if kcal_100g > 900:
        return Rejection(source, source_id, name, "KCAL_OUT_OF_RANGE")

    protein = macros.get("protein_100g", 0.0)
    fat = macros.get("fat_100g", 0.0)
    carbs = macros.get("carbs_100g", 0.0)
    if protein + fat + carbs > 100:
        return Rejection(source, source_id, name, "MACROS_EXCEED_100G")

    sodium_mg = nutrient_amounts.get(USDA_SODIUM_ID)
    salt_100g = round(sodium_mg * 2.5 / 1000, 3) if sodium_mg is not None else None

    micros = {
        key: nutrient_amounts[nid] for nid, key in USDA_MICRO_IDS.items() if nid in nutrient_amounts
    }

    portions = raw.get("foodPortions") or []
    serving_size_g = portions[0].get("gramWeight") if portions else None
    serving_label = (
        (portions[0].get("measureUnit") or {}).get("name") if portions else None
    )

    return ParsedFood(
        source=source,
        source_id=source_id,
        license="CC0",
        attribution="USDA FoodData Central",
        name_es=name,  # USDA no trae nombre en español — fallback documentado (sección 11.2)
        name_en=name,
        category=(raw.get("foodCategory") or {}).get("description"),
        serving_size_g=serving_size_g,
        serving_label=serving_label,
        quality_rank=_QUALITY_RANK[source],
        kcal_100g=kcal_100g,
        protein_100g=protein,
        fat_100g=fat,
        saturated_100g=macros.get("saturated_100g"),
        carbs_100g=carbs,
        sugars_100g=_sugars_100g(nutrient_amounts),
        fiber_100g=macros.get("fiber_100g"),
        salt_100g=salt_100g,
        micros=micros,
    )


@dataclass
class UsdaLoadResult:
    stats: LoadStats
    rejected_path: Path | None


def load(source: USDASource, json_path: Path | None = None) -> UsdaLoadResult:
    path = json_path or download(source)
    with path.open(encoding="utf-8") as f:
        data = json.load(f)

    raw_foods = data[_JSON_ROOT_KEY[source]]
    stats = LoadStats(read=len(raw_foods))

    parsed: list[ParsedFood] = []
    rejections: list[Rejection] = []
    for raw in raw_foods:
        result = parse_food(raw, source)
        if isinstance(result, Rejection):
            rejections.append(result)
        else:
            parsed.append(result)
    stats.rejected = len(rejections)

    conn = get_connection()
    try:
        stats.upserted = upsert_foods(conn, parsed)
    finally:
        conn.close()

    rejected_path = log_rejections(source, rejections) if rejections else None
    return UsdaLoadResult(stats=stats, rejected_path=rejected_path)
