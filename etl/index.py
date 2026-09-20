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
INDEX = os.environ.get("MEILI_INDEX", "foods")
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
    f.nutriscore_grade,
    f.nova_group,
    f.ecoscore_grade,
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
