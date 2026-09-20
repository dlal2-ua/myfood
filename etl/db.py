"""Conexión y upserts idempotentes contra `foods`/`food_nutrients`.

Estas tablas son catálogo global sin `user_id` — no están sujetas a RLS
(sección 22 solo lista tablas con datos de usuario) — así que el ETL usa
directamente el rol superusuario de Postgres, igual que Alembic.
"""

import json
import os
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from uuid import UUID

import psycopg2
import psycopg2.extras


def get_connection():
    return psycopg2.connect(
        host=os.environ.get("POSTGRES_HOST", "postgres"),
        port=int(os.environ.get("POSTGRES_PORT", "5432")),
        dbname=os.environ.get("POSTGRES_DB", "myfood"),
        user=os.environ.get("POSTGRES_USER", "myfood"),
        password=os.environ["POSTGRES_PASSWORD"],
    )


@dataclass
class ParsedFood:
    source: str
    source_id: str
    license: str
    name_es: str
    kcal_100g: float
    quality_rank: int
    name_en: str | None = None
    brand: str | None = None
    category: str | None = None
    barcode_ean: str | None = None
    serving_size_g: float | None = None
    serving_label: str | None = None
    attribution: str | None = None
    nutriscore_grade: str | None = None
    nova_group: int | None = None
    ecoscore_grade: str | None = None
    protein_100g: float = 0
    fat_100g: float = 0
    saturated_100g: float | None = None
    carbs_100g: float = 0
    sugars_100g: float | None = None
    fiber_100g: float | None = None
    salt_100g: float | None = None
    micros: dict = field(default_factory=dict)
    kind: str = "generic"


@dataclass
class LoadStats:
    read: int = 0
    upserted: int = 0
    rejected: int = 0


_FOOD_TEMPLATE = (
    "(%(kind)s, %(source)s, %(source_id)s, %(license)s, %(attribution)s, %(barcode_ean)s, "
    "%(name_es)s, %(name_en)s, %(brand)s, %(category)s, %(serving_size_g)s, %(serving_label)s, "
    "%(quality_rank)s, %(nutriscore_grade)s, %(nova_group)s, %(ecoscore_grade)s)"
)

_UPSERT_FOOD_BATCH_SQL = """
INSERT INTO foods (
    kind, source, source_id, license, attribution, barcode_ean,
    name_es, name_en, brand, category, serving_size_g, serving_label,
    quality_rank, nutriscore_grade, nova_group, ecoscore_grade
) VALUES %s
ON CONFLICT (source, source_id) WHERE source_id IS NOT NULL DO UPDATE SET
    license = EXCLUDED.license,
    attribution = EXCLUDED.attribution,
    barcode_ean = EXCLUDED.barcode_ean,
    name_es = EXCLUDED.name_es,
    name_en = EXCLUDED.name_en,
    brand = EXCLUDED.brand,
    category = EXCLUDED.category,
    serving_size_g = EXCLUDED.serving_size_g,
    serving_label = EXCLUDED.serving_label,
    quality_rank = EXCLUDED.quality_rank,
    nutriscore_grade = EXCLUDED.nutriscore_grade,
    nova_group = EXCLUDED.nova_group,
    ecoscore_grade = EXCLUDED.ecoscore_grade
RETURNING id, source, source_id
"""

_NUTRIENT_TEMPLATE = (
    "(%(food_id)s, %(kcal_100g)s, %(protein_100g)s, %(fat_100g)s, %(saturated_100g)s, "
    "%(carbs_100g)s, %(sugars_100g)s, %(fiber_100g)s, %(salt_100g)s, %(micros)s)"
)

_UPSERT_NUTRIENTS_BATCH_SQL = """
INSERT INTO food_nutrients (
    food_id, kcal_100g, protein_100g, fat_100g, saturated_100g,
    carbs_100g, sugars_100g, fiber_100g, salt_100g, micros
) VALUES %s
ON CONFLICT (food_id) DO UPDATE SET
    kcal_100g = EXCLUDED.kcal_100g,
    protein_100g = EXCLUDED.protein_100g,
    fat_100g = EXCLUDED.fat_100g,
    saturated_100g = EXCLUDED.saturated_100g,
    carbs_100g = EXCLUDED.carbs_100g,
    sugars_100g = EXCLUDED.sugars_100g,
    fiber_100g = EXCLUDED.fiber_100g,
    salt_100g = EXCLUDED.salt_100g,
    micros = EXCLUDED.micros
"""

_BATCH_SIZE = 1000


def upsert_foods(conn, foods: Iterable[ParsedFood], batch_size: int = _BATCH_SIZE) -> int:
    """Upsert por lotes, clave (source, source_id) — idempotente (sección 11.2).

    Usa `execute_values` (pipeline de varias filas por round-trip) en vez de
    una sentencia por fila — a la escala de OFF-España (cientos de miles de
    filas) un round-trip por fila tarda demasiado.
    """
    count = 0
    batch: list[ParsedFood] = []

    def flush(cur, batch: list[ParsedFood]) -> None:
        if not batch:
            return
        food_rows = []
        for food in batch:
            row = asdict(food)
            row.pop("micros")
            food_rows.append(row)

        returned = psycopg2.extras.execute_values(
            cur, _UPSERT_FOOD_BATCH_SQL, food_rows, template=_FOOD_TEMPLATE, fetch=True
        )
        id_by_key: dict[tuple[str, str], UUID] = {
            (r["source"], r["source_id"]): r["id"] for r in returned
        }

        nutrient_rows = []
        for food in batch:
            food_id = id_by_key[(food.source, food.source_id)]
            nutrient_rows.append(
                {
                    "food_id": food_id,
                    "kcal_100g": food.kcal_100g,
                    "protein_100g": food.protein_100g,
                    "fat_100g": food.fat_100g,
                    "saturated_100g": food.saturated_100g,
                    "carbs_100g": food.carbs_100g,
                    "sugars_100g": food.sugars_100g,
                    "fiber_100g": food.fiber_100g,
                    "salt_100g": food.salt_100g,
                    "micros": json.dumps(food.micros),
                }
            )
        psycopg2.extras.execute_values(
            cur, _UPSERT_NUTRIENTS_BATCH_SQL, nutrient_rows, template=_NUTRIENT_TEMPLATE
        )

    with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
        for food in foods:
            batch.append(food)
            count += 1
            if len(batch) >= batch_size:
                flush(cur, batch)
                conn.commit()
                batch = []
        flush(cur, batch)
        conn.commit()
    return count


_DELETE_ALLERGENS_SQL = (
    "DELETE FROM food_allergens WHERE food_id = ANY(%s::uuid[]) AND origin = ANY(%s)"
)
_INSERT_ALLERGENS_SQL = """
INSERT INTO food_allergens (food_id, allergen_code, origin) VALUES %s
ON CONFLICT (food_id, allergen_code) DO NOTHING
"""


def replace_allergens(
    conn,
    food_ids: Iterable[UUID],
    rows: Iterable[tuple[UUID, str, str]],
    *,
    origins: tuple[str, ...],
    batch_size: int = 2000,
) -> int:
    """Sustituye los alérgenos de `origins` de esos alimentos (idempotente: repetir
    la carga deja el mismo resultado, y si una etiqueta desaparece de la fuente
    desaparece también de la tabla). Un alérgeno ya presente con otro origen no
    se pisa (`ON CONFLICT DO NOTHING`): un `declared` gana a un `inferred`."""
    ids = list(food_ids)
    all_rows = list(rows)
    inserted = 0
    with conn.cursor() as cur:
        for start in range(0, len(ids), batch_size):
            cur.execute(_DELETE_ALLERGENS_SQL, (ids[start : start + batch_size], list(origins)))
        for start in range(0, len(all_rows), batch_size):
            chunk = all_rows[start : start + batch_size]
            psycopg2.extras.execute_values(cur, _INSERT_ALLERGENS_SQL, chunk)
            inserted += len(chunk)
    conn.commit()
    return inserted
