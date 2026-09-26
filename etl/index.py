"""Indexación en Meilisearch (documento 2, sección 11.3).

Uso: `python -m etl.index` — reindexa el índice `foods` completo desde
Postgres. Se ejecuta después de cargar cualquier fuente.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import httpx

from etl.db import get_connection

# La taxonomía de filtros (supermercado, tipo de alimento, nutrición) vive en la API, que también
# la usa para validar y etiquetar los filtros: una sola definición. Es Python puro, sin
# dependencias, así que el ETL (que es otro proyecto) la importa por ruta.
_API_SRC = Path(__file__).resolve().parents[1] / "apps" / "api" / "src"
if str(_API_SRC) not in sys.path:
    sys.path.insert(0, str(_API_SRC))

from myfood.domain.food_taxonomy import (  # noqa: E402
    food_type_for,
    nutrition_tags,
    supermarket_for_brand,
)

MEILI_URL = os.environ.get("MEILI_URL", "http://meilisearch:7700")
MEILI_MASTER_KEY = os.environ.get("MEILI_MASTER_KEY", "")
INDEX = os.environ.get("MEILI_INDEX", "foods")
BATCH_SIZE = 1000

INDEX_SETTINGS = {
    # El nombre corto también se busca: alguien que escribe «pechuga de pollo» tiene que
    # encontrar el alimento cuyo nombre de fuente es «Pollo, pechuga, con piel, crudo».
    "searchableAttributes": ["name_es", "name_short", "brand", "name_en"],
    "filterableAttributes": [
        "kind",
        "category",
        "quality_rank",
        "has_image",
        "source",
        "supermarket",
        "food_group",
        "nutrition_tags",
    ],
    "sortableAttributes": ["quality_rank", "kcal_100g", "protein_100g"],
    "typoTolerance": {"enabled": True},
    # Por defecto Meilisearch corta el total en 1000: el contador de resultados de los filtros
    # mentiría en cuanto una búsqueda tuviera más.
    "pagination": {"maxTotalHits": 50000},
    "synonyms": {
        "refresco": ["bebida"],
        "bebida": ["refresco"],
        "atun": ["bonito"],
        "bonito": ["atun"],
        "patata": ["papa"],
        "papa": ["patata"],
    },
}

_SELECT_FOODS_SQL = """
SELECT
    f.id::text AS id,
    f.name_es,
    f.name_short,
    f.name_en,
    f.brand,
    f.kind,
    f.category,
    f.quality_rank,
    f.source,
    f.nutriscore_grade,
    f.nova_group,
    f.ecoscore_grade,
    n.kcal_100g,
    n.protein_100g,
    n.fat_100g,
    n.carbs_100g,
    n.saturated_100g,
    n.sugars_100g,
    n.fiber_100g,
    n.salt_100g,
    EXISTS (SELECT 1 FROM food_images i WHERE i.food_id = f.id) AS has_image
FROM foods f
JOIN food_nutrients n ON n.food_id = f.id
"""


def _headers() -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if MEILI_MASTER_KEY:
        headers["Authorization"] = f"Bearer {MEILI_MASTER_KEY}"
    return headers


def configure_index(client: httpx.Client) -> None:
    resp = client.patch(f"/indexes/{INDEX}/settings", json=INDEX_SETTINGS)
    resp.raise_for_status()


def fetch_documents() -> list[dict]:
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(_SELECT_FOODS_SQL)
            columns = [c.name for c in cur.description]
            rows = cur.fetchall()
    finally:
        conn.close()

    return [build_document(dict(zip(columns, row, strict=True))) for row in rows]


def _num(value) -> float | None:
    return float(value) if value is not None else None


def build_document(row: dict) -> dict:
    """Documento de Meilisearch de un alimento: los campos del buscador más los de los filtros
    (`supermarket`, `food_group`, `nutrition_tags`), con `myfood.domain.food_taxonomy`."""
    kcal = _num(row["kcal_100g"])
    protein = _num(row["protein_100g"])
    fat = _num(row["fat_100g"])
    carbs = _num(row["carbs_100g"])
    doc = {
        key: row[key]
        for key in (
            "id",
            "name_es",
            "name_short",
            "name_en",
            "brand",
            "kind",
            "category",
            "quality_rank",
            "source",
            "nutriscore_grade",
            "nova_group",
            "ecoscore_grade",
            "has_image",
        )
    }
    doc.update(kcal_100g=kcal, protein_100g=protein, fat_100g=fat, carbs_100g=carbs)
    doc["supermarket"] = supermarket_for_brand(row["brand"])
    doc["food_group"] = food_type_for(row["name_es"], row["category"])
    doc["nutrition_tags"] = nutrition_tags(
        kcal=kcal,
        protein=protein,
        fat=fat,
        carbs=carbs,
        saturated=_num(row["saturated_100g"]),
        sugars=_num(row["sugars_100g"]),
        fiber=_num(row["fiber_100g"]),
        salt=_num(row["salt_100g"]),
        nutriscore=row["nutriscore_grade"],
        nova=row["nova_group"],
    )
    return doc


def index_documents(client: httpx.Client, documents: list[dict]) -> int:
    total = 0
    for i in range(0, len(documents), BATCH_SIZE):
        batch = documents[i : i + BATCH_SIZE]
        resp = client.post(f"/indexes/{INDEX}/documents?primaryKey=id", json=batch)
        resp.raise_for_status()
        total += len(batch)
    return total


def remove_stale_documents(client: httpx.Client, current_ids: set[str]) -> int:
    """Quita del índice los alimentos que ya no existen en Postgres (p. ej. borrados
    tras una limpieza): `reindex` solo añadía y actualizaba, así que se quedaban en
    las búsquedas para siempre."""
    stale: list[str] = []
    offset = 0
    while True:
        resp = client.get(
            f"/indexes/{INDEX}/documents", params={"fields": "id", "limit": 1000, "offset": offset}
        )
        resp.raise_for_status()
        page = resp.json()["results"]
        if not page:
            break
        stale += [doc["id"] for doc in page if doc["id"] not in current_ids]
        offset += len(page)
    for i in range(0, len(stale), BATCH_SIZE):
        client.post(
            f"/indexes/{INDEX}/documents/delete-batch", json=stale[i : i + BATCH_SIZE]
        ).raise_for_status()
    return len(stale)


def reindex() -> int:
    with httpx.Client(base_url=MEILI_URL, headers=_headers(), timeout=30) as client:
        configure_index(client)
        documents = fetch_documents()
        total = index_documents(client, documents)
        removed = remove_stale_documents(client, {doc["id"] for doc in documents})
        if removed:
            print(f"[index] {removed} alimentos obsoletos quitados del índice")
        return total


if __name__ == "__main__":
    count = reindex()
    print(f"[index] {count} alimentos indexados en Meilisearch")
