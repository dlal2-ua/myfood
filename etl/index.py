"""Indexación en Meilisearch (documento 2, sección 11.3).

Uso: `python -m etl.index` — reindexa el índice `foods` completo desde
Postgres. Se ejecuta después de cargar cualquier fuente.
"""

from __future__ import annotations

import os

import httpx

from etl.db import get_connection

MEILI_URL = os.environ.get("MEILI_URL", "http://meilisearch:7700")
MEILI_MASTER_KEY = os.environ.get("MEILI_MASTER_KEY", "")
BATCH_SIZE = 1000

INDEX_SETTINGS = {
    "searchableAttributes": ["name_es", "brand", "name_en"],
    "filterableAttributes": ["kind", "category", "quality_rank", "has_image"],
    "sortableAttributes": ["quality_rank", "kcal_100g"],
    "typoTolerance": {"enabled": True},
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
    f.name_en,
    f.brand,
    f.kind,
    f.category,
    f.quality_rank,
    f.source,
    n.kcal_100g,
    n.protein_100g,
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
    resp = client.patch("/indexes/foods/settings", json=INDEX_SETTINGS)
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

    documents = []
    for row in rows:
        doc = dict(zip(columns, row, strict=True))
        for numeric_field in ("kcal_100g", "protein_100g"):
            if doc[numeric_field] is not None:
                doc[numeric_field] = float(doc[numeric_field])
        documents.append(doc)
    return documents


def index_documents(client: httpx.Client, documents: list[dict]) -> int:
    total = 0
    for i in range(0, len(documents), BATCH_SIZE):
        batch = documents[i : i + BATCH_SIZE]
        resp = client.post("/indexes/foods/documents?primaryKey=id", json=batch)
        resp.raise_for_status()
        total += len(batch)
    return total


def reindex() -> int:
    with httpx.Client(base_url=MEILI_URL, headers=_headers(), timeout=30) as client:
        configure_index(client)
        documents = fetch_documents()
        return index_documents(client, documents)


if __name__ == "__main__":
    count = reindex()
    print(f"[index] {count} alimentos indexados en Meilisearch")
