"""BEDCA (AESAN) — España (documento 2, sección 11). Referencia nacional.

Fuente: servicio HTTP+XML público en `https://www.bedca.net/bdpub/procquery.php`
(verificado en vivo 2026-09-11). El README y el enunciado original del
proyecto lo describen como "servicio SOAP", pero la investigación real del
endpoint (la WSDL clásica `bdpub/procedure_call.php?wsdl` ya no existe, 404)
mostró que es en realidad un protocolo propio: se envía una petición XML
(`<foodquery>`) por HTTP POST con `Content-Type: text/xml` y se recibe una
respuesta XML (`<foodresponse>`) — no hay envoltorio SOAP/WSDL real. Esto se
confirmó tanto probando el endpoint directamente (`curl -X POST`, HTTP 200
con datos reales) como revisando clientes de terceros ya existentes
(github.com/statickidz/bedca-api, MIT). Por eso no hace falta añadir `zeep`
(cliente SOAP) como dependencia — `httpx` (ya en `pyproject.toml`) basta para
hacer el POST, y `xml.etree.ElementTree` (stdlib) para parsear la respuesta.

Operaciones usadas (replican `BedcaClient::getFoodGroups/getFoodsInGroup/
getFood` del cliente PHP de referencia, verificadas contra el servicio real):
  - `<type level="3"/>` -> lista de grupos de alimentos (`fg_id`, `fg_ori_name`).
  - `<type level="1"/>` + condición `foodgroup_id` -> alimentos de un grupo
    (`f_id`, `f_ori_name`, `f_origen`).
  - `<type level="2"/>` + condición `f_id` -> composición nutricional
    completa de un alimento (lista de `<foodvalue>`, cada uno con `eur_name`,
    `best_location` (el valor) y `v_unit`).

`f_origen` distingue la procedencia de cada registro dentro de la red BEDCA:
además del propio equipo BEDCA, universidades colaboradoras aportan datos
bajo otros orígenes (`UCM`, `UGR`, `UCO`, `CESNID`, `TOTAL`, `COMPLEMENTO`,
`HPH`, `UMU`, `UGR2015`, y una segunda tanda propia `BEDCA2`). El total sin
filtrar (verificado sumando las 13 categorías) es de más de 2.300 registros
de calidad heterogénea. Se carga solo `f_origen == "BEDCA"` exacto (431
alimentos, verificado 2026-09-11) — es el conjunto de referencia oficial de
BEDCA que documenta el README (~500). El propio filtro de condición del
servicio (`f_origen EQUAL 'BEDCA'`) hace coincidencia por subcadena y también
devuelve `BEDCA2` (verificado: 91+59=150 resultados en el grupo 1 pidiendo
solo "BEDCA") — por eso se pide la lista sin condición de origen y se filtra
en cliente por igualdad exacta.

BEDCA ya normaliza todos los valores "por 100 g de porción comestible"
(`mu_id == "W"`, verificado en todos los alimentos muestreados) — no hace
falta convertir por ración (sección 11.2). La energía solo se reporta en kJ
(`eur_name == "ENERC"`); se convierte a kcal dividiendo por 4.184 (factor
estándar, verificado con cálculo inverso desde macros: kcal convertido desde
kJ para "Queso Camembert 20-30% MG/ES" (f_id=929) da ~199.7 kcal, y
proteína×4 + grasa×9 de ese mismo alimento da ~200 kcal — consistente).
"""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

import httpx

from etl.db import LoadStats, ParsedFood, get_connection, upsert_foods
from etl.rejected import Rejection, log_rejections
from etl.transform.nutrient_map import (
    BEDCA_ENERGY_EUR_NAME,
    BEDCA_KJ_PER_KCAL,
    BEDCA_MACRO_EUR_NAMES,
    BEDCA_MICRO_EUR_NAMES,
    BEDCA_SODIUM_EUR_NAME,
)

BASE_URL = "https://www.bedca.net/bdpub/procquery.php"
QUALITY_RANK = 4
ORIGIN_FILTER = "BEDCA"
CACHE_DIR = Path(__file__).parent.parent / ".cache"

_HEADERS = {"Content-Type": "text/xml", "User-Agent": "Mozilla/5.0"}

_FOOD_GROUPS_XML = """<?xml version="1.0" encoding="utf-8"?>
<foodquery>
    <type level="3"/>
    <selection>
        <atribute name="fg_id"/>
        <atribute name="fg_ori_name"/>
    </selection>
    <order ordtype="ASC">
        <atribute3 name="fg_id"/>
    </order>
</foodquery>"""

# Atributos completos de composición (documento 2, sección 11) — replica la
# selección usada por el cliente de referencia (statickidz/bedca-api).
_FOOD_DETAIL_ATTRIBUTES = (
    "f_id",
    "f_ori_name",
    "f_eng_name",
    "f_origen",
    "eur_name",
    "best_location",
    "v_unit",
)


def _foods_in_group_xml(group_id: str) -> str:
    return f"""<?xml version="1.0" encoding="utf-8"?>
<foodquery>
    <type level="1"/>
    <selection>
        <atribute name="f_id"/>
        <atribute name="f_ori_name"/>
        <atribute name="f_eng_name"/>
        <atribute name="f_origen"/>
    </selection>
    <condition>
        <cond1>
            <atribute1 name="foodgroup_id"/>
        </cond1>
        <relation type="EQUAL"/>
        <cond3>{group_id}</cond3>
    </condition>
    <order ordtype="ASC">
        <atribute3 name="f_eng_name"/>
    </order>
</foodquery>"""


def _food_detail_xml(food_id: str) -> str:
    attrs = "\n        ".join(f'<atribute name="{name}"/>' for name in _FOOD_DETAIL_ATTRIBUTES)
    return f"""<?xml version="1.0" encoding="utf-8"?>
<foodquery>
    <type level="2"/>
    <selection>
        {attrs}
    </selection>
    <condition>
        <cond1>
            <atribute1 name="f_id"/>
        </cond1>
        <relation type="EQUAL"/>
        <cond3>{food_id}</cond3>
    </condition>
    <condition>
        <cond1>
            <atribute1 name="publico"/>
        </cond1>
        <relation type="EQUAL"/>
        <cond3>1</cond3>
    </condition>
    <order ordtype="ASC">
        <atribute3 name="componentgroup_id"/>
    </order>
</foodquery>"""


def _post(xml_body: str, client: httpx.Client) -> ET.Element:
    resp = client.post(BASE_URL, content=xml_body.encode("utf-8"), headers=_HEADERS, timeout=30)
    resp.raise_for_status()
    return ET.fromstring(resp.content)


def _fetch_food_groups(client: httpx.Client) -> list[dict[str, str]]:
    root = _post(_FOOD_GROUPS_XML, client)
    return [
        {"fg_id": f.findtext("fg_id") or "", "fg_ori_name": f.findtext("fg_ori_name") or ""}
        for f in root.findall("food")
    ]


def _fetch_group_members(group_id: str, client: httpx.Client) -> list[dict[str, str]]:
    root = _post(_foods_in_group_xml(group_id), client)
    return [
        {
            "f_id": f.findtext("f_id") or "",
            "f_origen": f.findtext("f_origen") or "",
        }
        for f in root.findall("food")
    ]


def _fetch_food_detail(food_id: str, client: httpx.Client) -> dict | None:
    root = _post(_food_detail_xml(food_id), client)
    food_el = root.find("food")
    if food_el is None:
        return None
    foodvalues = [
        {
            "eur_name": fv.findtext("eur_name"),
            "best_location": fv.findtext("best_location"),
            "v_unit": fv.findtext("v_unit"),
        }
        for fv in food_el.findall("foodvalue")
    ]
    return {
        "f_id": food_el.findtext("f_id"),
        "f_ori_name": food_el.findtext("f_ori_name"),
        "f_eng_name": food_el.findtext("f_eng_name"),
        "f_origen": food_el.findtext("f_origen"),
        "foodvalues": foodvalues,
    }


def download(cache_dir: Path = CACHE_DIR) -> Path:
    """Consulta el servicio BEDCA completo (grupos -> alimentos -> detalle) y
    cachea el resultado combinado en un único JSON (sección 11.2, igual
    patrón de caché local que el resto de fuentes)."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = cache_dir / "bedca.json"
    if path.exists():
        return path

    with httpx.Client() as client:
        groups = _fetch_food_groups(client)

        # (f_id -> categoría) solo para los alimentos de origen BEDCA exacto
        # (sección 11.2 — nunca se relaja el filtro de calidad para inflar
        # el número cargado; ver docstring del módulo).
        selected: dict[str, str] = {}
        for group in groups:
            members = _fetch_group_members(group["fg_id"], client)
            for member in members:
                if member["f_origen"] != ORIGIN_FILTER:
                    continue
                selected.setdefault(member["f_id"], group["fg_ori_name"])

        rows = []
        for food_id, category in selected.items():
            detail = _fetch_food_detail(food_id, client)
            if detail is None:
                continue
            detail["category"] = category
            rows.append(detail)

    path.write_text(json.dumps({"rows": rows}, ensure_ascii=False), encoding="utf-8")
    return path


def _parse_number(raw: str | None) -> float | None:
    if raw is None:
        return None
    v = raw.strip()
    if not v:
        return None
    try:
        return float(v)
    except ValueError:
        return None


def _component_values(foodvalues: list[dict]) -> dict[str, float]:
    """Un alimento trae varias `<foodvalue>`, una por componente (nutriente).
    Cuando el componente no fue cuantificado (solo detectado, "trazas"),
    BEDCA deja `best_location` vacío — se traduce a `None` (dato ausente),
    nunca se estima (sección 11.2)."""
    values: dict[str, float] = {}
    for fv in foodvalues:
        eur_name = fv.get("eur_name")
        if not eur_name:
            continue
        value = _parse_number(fv.get("best_location"))
        if value is not None:
            values[eur_name] = value
    return values


def parse_food(row: dict) -> ParsedFood | Rejection:
    """Transforma un alimento crudo de BEDCA. Función pura — sin I/O (testeable)."""
    source_id = str(row.get("f_id") or "").strip()
    name = str(row.get("f_ori_name") or "").strip()
    if not source_id:
        return Rejection("bedca", None, name or None, "MISSING_SOURCE_ID")
    if not name:
        return Rejection("bedca", source_id, None, "MISSING_NAME")

    values = _component_values(row.get("foodvalues") or [])

    energy_kj = values.get(BEDCA_ENERGY_EUR_NAME)
    kcal_100g = round(energy_kj / BEDCA_KJ_PER_KCAL, 3) if energy_kj is not None else None
    if kcal_100g is None:
        return Rejection("bedca", source_id, name, "MISSING_KCAL")
    if kcal_100g > 900:
        return Rejection("bedca", source_id, name, "KCAL_OUT_OF_RANGE")

    macros = {
        field_name: values[eur_name]
        for eur_name, field_name in BEDCA_MACRO_EUR_NAMES.items()
        if eur_name in values
    }

    protein = macros.get("protein_100g", 0.0)
    fat = macros.get("fat_100g", 0.0)
    carbs = macros.get("carbs_100g", 0.0)
    if protein + fat + carbs > 100:
        return Rejection("bedca", source_id, name, "MACROS_EXCEED_100G")

    sodium_mg = values.get(BEDCA_SODIUM_EUR_NAME)
    salt_100g = round(sodium_mg * 2.5 / 1000, 3) if sodium_mg is not None else None

    micros = {
        field_name: values[eur_name]
        for eur_name, field_name in BEDCA_MICRO_EUR_NAMES.items()
        if eur_name in values
    }

    name_en_raw = row.get("f_eng_name")
    name_en = str(name_en_raw).strip() if name_en_raw else None

    return ParsedFood(
        source="bedca",
        source_id=source_id,
        license="Uso público (AESAN/BEDCA, no comercial sin autorización expresa)",
        attribution="AESAN/BEDCA v1.0 (2010)",
        name_es=name,
        name_en=name_en or None,
        category=str(row.get("category")) if row.get("category") else None,
        quality_rank=QUALITY_RANK,
        kcal_100g=kcal_100g,
        protein_100g=protein,
        fat_100g=fat,
        saturated_100g=macros.get("saturated_100g"),
        carbs_100g=carbs,
        sugars_100g=macros.get("sugars_100g"),
        fiber_100g=macros.get("fiber_100g"),
        salt_100g=salt_100g,
        micros=micros,
    )


@dataclass
class BedcaLoadResult:
    stats: LoadStats
    rejected_path: Path | None


def load(json_path: Path | None = None) -> BedcaLoadResult:
    path = json_path or download()
    with path.open(encoding="utf-8") as f:
        data = json.load(f)

    rows = data["rows"]
    stats = LoadStats(read=len(rows))

    parsed: list[ParsedFood] = []
    rejections: list[Rejection] = []
    for row in rows:
        result = parse_food(row)
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

    rejected_path = log_rejections("bedca", rejections) if rejections else None
    return BedcaLoadResult(stats=stats, rejected_path=rejected_path)
