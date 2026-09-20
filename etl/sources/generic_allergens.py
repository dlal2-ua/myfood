"""Alérgenos inferidos de los alimentos genéricos (USDA, CIQUAL, BEDCA).

Estas fuentes no publican etiquetas de alérgenos; se clasifican por nombre y
categoría con `etl.transform.allergens.classify_generic`. Ver ese módulo para
las limitaciones (heurística, prefiere errar por exceso)."""

from __future__ import annotations

from etl.db import LoadStats, get_connection, replace_allergens
from etl.transform.allergens import classify_generic

_GENERIC_SOURCES = ("usda_foundation", "usda_sr", "ciqual", "bedca")


def load() -> LoadStats:
    stats = LoadStats()
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, name_es, name_en, category FROM foods "
                "WHERE kind = 'generic' AND source = ANY(%s)",
                (list(_GENERIC_SOURCES),),
            )
            foods = cur.fetchall()
        ids = []
        rows = []
        for food_id, name_es, name_en, category in foods:
            stats.read += 1
            ids.append(food_id)
            rows += [
                (food_id, code, "inferred")
                for code in sorted(classify_generic(name_es, name_en, category))
            ]
        stats.upserted = replace_allergens(conn, ids, rows, origins=("inferred",))
    finally:
        conn.close()
    return stats
