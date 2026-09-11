"""Tests de transformación USDA con muestras reales (documento 2, sección 16).

`parse_food` es una función pura — estos tests no tocan la base de datos,
solo la lógica de mapeo, conversión y descarte de la sección 11.2.
"""

import json
from pathlib import Path

from etl.db import ParsedFood
from etl.rejected import Rejection
from etl.sources.usda import parse_food

FIXTURES = Path(__file__).parent.parent / "fixtures"


def _load_fixture(name: str) -> list[dict]:
    with (FIXTURES / name).open(encoding="utf-8") as f:
        return json.load(f)["FoundationFoods"]


def test_parse_real_food_maps_macros_correctly():
    hummus = _load_fixture("usda_foundation_sample.json")[0]
    assert hummus["description"] == "Hummus, commercial"

    result = parse_food(hummus, "usda_foundation")

    assert isinstance(result, ParsedFood)
    assert result.source == "usda_foundation"
    assert result.source_id == str(hummus["fdcId"])
    assert result.name_es == "Hummus, commercial"
    assert result.kcal_100g == 229
    assert result.quality_rank == 1
    assert result.license == "CC0"


def test_parse_real_food_maps_micros_by_explicit_id_not_name():
    hummus = _load_fixture("usda_foundation_sample.json")[0]
    result = parse_food(hummus, "usda_foundation")
    assert isinstance(result, ParsedFood)
    # id 1162 = Vitamin C -> vitamin_c_mg (tabla explícita, no adivinada por nombre)
    vit_c = next(
        n["amount"] for n in hummus["foodNutrients"] if n["nutrient"]["id"] == 1162
    )
    assert result.micros["vitamin_c_mg"] == vit_c


def test_parse_second_real_food():
    tomatoes = _load_fixture("usda_foundation_sample.json")[1]
    result = parse_food(tomatoes, "usda_sr")
    assert isinstance(result, ParsedFood)
    assert result.kcal_100g == 27.0
    assert result.quality_rank == 2  # usda_sr


def test_null_record_is_rejected():
    result = parse_food(None, "usda_foundation")
    assert isinstance(result, Rejection)
    assert result.reason == "NULL_RECORD"


def test_missing_kcal_is_rejected():
    raw = {"fdcId": 1, "description": "Sin energía", "foodNutrients": []}
    result = parse_food(raw, "usda_foundation")
    assert isinstance(result, Rejection)
    assert result.reason == "MISSING_KCAL"


def test_kcal_above_900_is_rejected():
    raw = {
        "fdcId": 2,
        "description": "Aceite imposible",
        "foodNutrients": [{"nutrient": {"id": 1008}, "amount": 950}],
    }
    result = parse_food(raw, "usda_foundation")
    assert isinstance(result, Rejection)
    assert result.reason == "KCAL_OUT_OF_RANGE"


def test_macros_exceeding_100g_is_rejected():
    raw = {
        "fdcId": 3,
        "description": "Macros imposibles",
        "foodNutrients": [
            {"nutrient": {"id": 1008}, "amount": 400},
            {"nutrient": {"id": 1003}, "amount": 60},
            {"nutrient": {"id": 1004}, "amount": 30},
            {"nutrient": {"id": 1005}, "amount": 30},
        ],
    }
    result = parse_food(raw, "usda_foundation")
    assert isinstance(result, Rejection)
    assert result.reason == "MACROS_EXCEED_100G"


def test_missing_name_is_rejected():
    raw = {"fdcId": 4, "foodNutrients": [{"nutrient": {"id": 1008}, "amount": 100}]}
    result = parse_food(raw, "usda_foundation")
    assert isinstance(result, Rejection)
    assert result.reason == "MISSING_NAME"


def test_sodium_converts_to_salt_100g():
    raw = {
        "fdcId": 5,
        "description": "Con sodio",
        "foodNutrients": [
            {"nutrient": {"id": 1008}, "amount": 100},
            {"nutrient": {"id": 1093}, "amount": 400},  # 400 mg sodio
        ],
    }
    result = parse_food(raw, "usda_foundation")
    assert isinstance(result, ParsedFood)
    assert result.salt_100g == 1.0  # 400 * 2.5 / 1000


def test_sugars_prefers_2000_over_1063():
    raw = {
        "fdcId": 6,
        "description": "Con dos azúcares",
        "foodNutrients": [
            {"nutrient": {"id": 1008}, "amount": 100},
            {"nutrient": {"id": 1063}, "amount": 5.0},
            {"nutrient": {"id": 2000}, "amount": 6.0},
        ],
    }
    result = parse_food(raw, "usda_foundation")
    assert isinstance(result, ParsedFood)
    assert result.sugars_100g == 6.0


def test_sugars_falls_back_to_1063_when_2000_absent():
    raw = {
        "fdcId": 7,
        "description": "Solo azúcar legacy",
        "foodNutrients": [
            {"nutrient": {"id": 1008}, "amount": 100},
            {"nutrient": {"id": 1063}, "amount": 5.0},
        ],
    }
    result = parse_food(raw, "usda_foundation")
    assert isinstance(result, ParsedFood)
    assert result.sugars_100g == 5.0
