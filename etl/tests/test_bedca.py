"""Tests de transformación BEDCA con muestras reales (documento 2, sección 16)."""

import json
from pathlib import Path

from etl.db import ParsedFood
from etl.rejected import Rejection
from etl.sources.bedca import _parse_number, parse_food

FIXTURES = Path(__file__).parent.parent / "fixtures"


def _load_fixture() -> list[dict]:
    with (FIXTURES / "bedca_sample.json").open(encoding="utf-8") as f:
        return json.load(f)["rows"]


def _by_id(food_id: str) -> dict:
    return next(row for row in _load_fixture() if row.get("f_id") == food_id)


def test_parse_real_food_maps_macros():
    row = _by_id("929")
    assert row["f_ori_name"] == "Queso Camembert 20-30% MG/ES"

    result = parse_food(row)

    assert isinstance(result, ParsedFood)
    assert result.source == "bedca"
    assert result.source_id == "929"
    assert result.name_es == "Queso Camembert 20-30% MG/ES"
    assert result.name_en == "Camembert cheese, 20-30% fidm"
    assert result.category == "Lácteos y derivados"
    assert result.quality_rank == 4
    assert result.protein_100g == 24.7
    assert result.fat_100g == 11.2381
    assert result.saturated_100g == 7.0
    assert result.license == "Uso público (AESAN/BEDCA, no comercial sin autorización expresa)"


def test_energy_is_converted_from_kj_to_kcal():
    """BEDCA solo reporta energía en kJ (`ENERC`) — nunca en kcal directamente
    (verificado 2026-09-11 contra el servicio real: ningún alimento de
    origen BEDCA trae un componente de energía distinto). Se convierte
    dividiendo por 4.184 (factor estándar), nunca se estima."""
    row = _by_id("929")
    result = parse_food(row)
    assert isinstance(result, ParsedFood)
    # 835.71 kJ / 4.184 = 199.739 kcal
    assert result.kcal_100g == 199.739


def test_sodium_is_converted_to_salt():
    """BEDCA no reporta sal directamente, solo sodio (`NA`, mg) — se
    convierte con el mismo factor que USDA (NaCl/Na = 2.5)."""
    row = _by_id("929")
    result = parse_food(row)
    assert isinstance(result, ParsedFood)
    # sodio 891 mg -> 891 * 2.5 / 1000 = 2.2275 -> redondeado a 2.228
    assert result.salt_100g == 2.228


def test_parse_second_real_food_pure_fat():
    """Segundo alimento real, con perfil de macros muy distinto (aceite:
    100% grasa, sin proteína ni carbohidratos) — confirma que el mapeo no
    depende de que todos los campos estén presentes."""
    row = _by_id("748")
    result = parse_food(row)
    assert isinstance(result, ParsedFood)
    assert result.name_es == "Aceite de coco"
    assert result.category == "Grasas y aceites"
    assert result.fat_100g == 100.0
    assert result.protein_100g == 0.0
    assert result.carbs_100g == 0.0
    assert result.kcal_100g < 900  # justo por debajo del límite de sección 11.2


def test_real_food_exceeding_100g_macros_is_rejected():
    """Caso real (no sintético) encontrado en el propio dump de BEDCA:
    proteína+grasa+carbohidratos de este alimento suman 100.7 g — un
    problema real de los datos de origen, no un bug del pipeline. Se
    descarta en vez de forzar el número (sección 11.2, R9)."""
    row = _by_id("1050")
    result = parse_food(row)
    assert isinstance(result, Rejection)
    assert result.reason == "MACROS_EXCEED_100G"
    assert result.name == "Galleta, cubierta de chocolate"


def test_food_with_empty_detail_response_is_rejected():
    """Quirk real del servicio: un alimento listado en un grupo puede
    devolver un `<food>` vacío al consultar su detalle (`f_id` nulo,
    verificado 2026-09-11 contra el servicio en vivo) — se descarta en vez
    de inventar un identificador."""
    row = next(row for row in _load_fixture() if row.get("f_id") is None)
    result = parse_food(row)
    assert isinstance(result, Rejection)
    assert result.reason == "MISSING_SOURCE_ID"


def test_missing_kcal_is_rejected():
    """Ningún alimento real de origen BEDCA carece de energía (verificado
    contra las 431 filas cargadas), pero el mismo caso puede darse en el
    futuro (nueva alta sin analizar) — se construye a partir de la forma
    real de una fila quitando el componente ENERC."""
    row = {
        "f_id": "99999",
        "f_ori_name": "Alimento sin energía",
        "f_eng_name": "Food without energy",
        "foodvalues": [
            {"eur_name": "PROT", "best_location": "10", "v_unit": "g"},
        ],
    }
    result = parse_food(row)
    assert isinstance(result, Rejection)
    assert result.reason == "MISSING_KCAL"


def test_kcal_above_900_is_rejected():
    """Ningún alimento real de origen BEDCA supera los 900 kcal/100g (el
    máximo real muestreado es aceite de coco, 884.321 kcal) — caso límite
    construido para testear la regla (sección 11.2)."""
    row = {
        "f_id": "99998",
        "f_ori_name": "Imposible",
        "f_eng_name": "Impossible",
        "foodvalues": [
            {"eur_name": "ENERC", "best_location": "4000", "v_unit": "kJ"},  # ~956 kcal
        ],
    }
    result = parse_food(row)
    assert isinstance(result, Rejection)
    assert result.reason == "KCAL_OUT_OF_RANGE"


def test_missing_name_is_rejected():
    row = {"f_id": "1", "f_ori_name": "", "foodvalues": []}
    result = parse_food(row)
    assert isinstance(result, Rejection)
    assert result.reason == "MISSING_NAME"


def test_traces_component_is_treated_as_missing_not_zero():
    """BEDCA deja `best_location` vacío para componentes detectados pero no
    cuantificados ("trazas") — se traduce a ausente, nunca a 0 (sección
    11.2). El azúcar del Camembert de muestra viene así."""
    row = _by_id("929")
    sugar_values = [fv for fv in row["foodvalues"] if fv["eur_name"] == "SUGAR"]
    assert sugar_values[0]["best_location"] == ""

    result = parse_food(row)
    assert isinstance(result, ParsedFood)
    assert result.sugars_100g is None  # no se estima un 0


def test_parse_number_handles_empty_string():
    assert _parse_number("") is None


def test_parse_number_handles_none():
    assert _parse_number(None) is None


def test_parse_number_parses_plain_float():
    assert _parse_number("835.71") == 835.71
