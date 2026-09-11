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


_UPSERT_FOOD_SQL = """
INSERT INTO foods (
    kind, source, source_id, license, attribution, barcode_ean,
    name_es, name_en, brand, category, serving_size_g, serving_label,
    quality_rank, nutriscore_grade, nova_group, ecoscore_grade
) VALUES (
    %(kind)s, %(source)s, %(source_id)s, %(license)s, %(attribution)s, %(barcode_ean)s,
    %(name_es)s, %(name_en)s, %(brand)s, %(category)s, %(serving_size_g)s, %(serving_label)s,
    %(quality_rank)s, %(nutriscore_grade)s, %(nova_group)s, %(ecoscore_grade)s
)
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
RETURNING id
"""

_UPSERT_NUTRIENTS_SQL = """
INSERT INTO food_nutrients (
    food_id, kcal_100g, protein_100g, fat_100g, saturated_100g,
    carbs_100g, sugars_100g, fiber_100g, salt_100g, micros
) VALUES (
    %(food_id)s, %(kcal_100g)s, %(protein_100g)s, %(fat_100g)s, %(saturated_100g)s,
    %(carbs_100g)s, %(sugars_100g)s, %(fiber_100g)s, %(salt_100g)s, %(micros)s
)
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


def upsert_foods(conn, foods: Iterable[ParsedFood]) -> int:
    """Upsert por lotes, clave (source, source_id) — idempotente (sección 11.2)."""
    count = 0
    with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
        for food in foods:
            row = asdict(food)
            micros = row.pop("micros")
            row["micros"] = None  # placeholder, no se usa en _UPSERT_FOOD_SQL
            cur.execute(_UPSERT_FOOD_SQL, row)
            food_id: UUID = cur.fetchone()["id"]
            cur.execute(
                _UPSERT_NUTRIENTS_SQL,
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
                    "micros": json.dumps(micros),
                },
            )
            count += 1
        conn.commit()
    return count
