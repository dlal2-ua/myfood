"""CIQUAL — ANSES, Francia (documento 2, sección 11). Refuerzo europeo.

Fuente: tabla Excel 2020 en data.gouv.fr, hoja "compo" (verificado
2026-09-11). Formato `.xls` legado (BIFF), no `.xlsx` — requiere `xlrd`.
Valores en francés, coma decimal, con marcadores especiales:
  "-"        -> no medido (se descarta como dato, no se estima)
  "traces"   -> detectado pero no cuantificado (idem, no se estima un 0)
  "< X"      -> por debajo del límite de detección; se usa X literal, tal
                cual lo reporta la fuente (no es una estimación nuestra)
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import httpx
import xlrd

from etl.db import LoadStats, ParsedFood, get_connection, upsert_foods
from etl.rejected import Rejection, log_rejections
from etl.transform.nutrient_map import CIQUAL_MACRO_HEADERS, CIQUAL_MICRO_HEADERS

DOWNLOAD_URL = "https://www.data.gouv.fr/api/1/datasets/r/bcdb7fec-875c-42aa-ba6e-460adf97aad3"
QUALITY_RANK = 3
CACHE_DIR = Path(__file__).parent.parent / ".cache"


def download(cache_dir: Path = CACHE_DIR) -> Path:
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = cache_dir / "ciqual.xls"
    if not path.exists():
        resp = httpx.get(
            DOWNLOAD_URL, headers={"User-Agent": "Mozilla/5.0"}, timeout=60, follow_redirects=True
        )
        resp.raise_for_status()
        path.write_bytes(resp.content)
    return path


def _parse_number(raw: str) -> float | None:
    v = raw.strip()
    if not v or v == "-" or v.lower() == "traces":
        return None
    if v.startswith("<"):
        v = v[1:].strip()
    try:
        return float(v.replace(",", "."))
    except ValueError:
        return None


def _read_rows(xls_path: Path) -> list[dict[str, object]]:
    wb = xlrd.open_workbook(xls_path)
    sheet = wb.sheet_by_name("compo")
    header = [sheet.cell_value(0, c) for c in range(sheet.ncols)]
    rows = []
    for r in range(1, sheet.nrows):
        row = {}
        for c, key in enumerate(header):
            cell = sheet.cell(r, c)
            row[key] = cell.value if cell.ctype != 0 else ""
        rows.append(row)
    return rows


def parse_food(row: dict[str, object]) -> ParsedFood | Rejection:
    """Transforma una fila cruda de CIQUAL. Función pura — sin I/O (testeable)."""
    source_id = str(row.get("alim_code") or "").strip()
    name = str(row.get("alim_nom_fr") or "").strip()
    if not source_id:
        return Rejection("ciqual", None, name or None, "MISSING_SOURCE_ID")
    if not name:
        return Rejection("ciqual", source_id, None, "MISSING_NAME")

    macros = {}
    for header, field_name in CIQUAL_MACRO_HEADERS.items():
        raw = row.get(header)
        value = _parse_number(str(raw)) if raw not in (None, "") else None
        if value is not None:
            macros[field_name] = value

    kcal_100g = macros.get("kcal_100g")
    if kcal_100g is None:
        return Rejection("ciqual", source_id, name, "MISSING_KCAL")
    if kcal_100g > 900:
        return Rejection("ciqual", source_id, name, "KCAL_OUT_OF_RANGE")

    protein = macros.get("protein_100g", 0.0)
    fat = macros.get("fat_100g", 0.0)
    carbs = macros.get("carbs_100g", 0.0)
    if protein + fat + carbs > 100:
        return Rejection("ciqual", source_id, name, "MACROS_EXCEED_100G")

    micros = {}
    for header, key in CIQUAL_MICRO_HEADERS.items():
        raw = row.get(header)
        value = _parse_number(str(raw)) if raw not in (None, "") else None
        if value is not None:
            micros[key] = value

    category = row.get("alim_ssgrp_nom_fr") or row.get("alim_grp_nom_fr") or None

    return ParsedFood(
        source="ciqual",
        source_id=source_id,
        license="Licence Ouverte (Etalab)",
        attribution="ANSES-CIQUAL 2020",
        name_es=name,  # CIQUAL no trae nombre en español — fallback documentado
        name_en=None,
        category=str(category) if category else None,
        quality_rank=QUALITY_RANK,
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
class CiqualLoadResult:
    stats: LoadStats
    rejected_path: Path | None


def load(xls_path: Path | None = None) -> CiqualLoadResult:
    path = xls_path or download()
    rows = _read_rows(path)
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

    rejected_path = log_rejections("ciqual", rejections) if rejections else None
    return CiqualLoadResult(stats=stats, rejected_path=rejected_path)
