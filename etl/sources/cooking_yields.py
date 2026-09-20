"""Factor de cocción (documento 2, secciones 11.2 y 21): gramos cocido / gramos crudo de los
alimentos base de mayor uso, rellenado a mano en `etl/seeds/cooking_yields.csv` — no viene de
ninguna fuente automática. Con él, el registro de comidas puede aceptar el peso de un plato ya
cocinado y calcular la nutrición sobre el peso crudo equivalente."""

from __future__ import annotations

import csv
import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from etl.db import LoadStats, get_connection

SEED_PATH = Path(__file__).resolve().parent.parent / "seeds" / "cooking_yields.csv"


@dataclass(frozen=True)
class YieldRule:
    source: str
    pattern: re.Pattern[str]
    factor: float


def load_rules(path: Path = SEED_PATH) -> list[YieldRule]:
    rules = []
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            factor = float(row["factor"])
            if factor <= 0:
                raise ValueError(f"factor de cocción no válido en {row['name_regex']!r}: {factor}")
            rules.append(
                YieldRule(row["source"], re.compile(row["name_regex"], re.IGNORECASE), factor)
            )
    return rules


def assign_factors(
    foods: Iterable[tuple[str, str, str]], rules: list[YieldRule]
) -> dict[str, float]:
    """`{food_id: factor}` para los alimentos `(id, source, name_es)` que encajan con alguna regla.
    Gana la primera regla que encaja (las más específicas van antes en el CSV)."""
    assigned: dict[str, float] = {}
    for food_id, source, name in foods:
        for rule in rules:
            if rule.source == source and rule.pattern.search(name):
                assigned[food_id] = rule.factor
                break
    return assigned


def load() -> LoadStats:
    rules = load_rules()
    stats = LoadStats()
    conn = get_connection()
    try:
        with conn, conn.cursor() as cur:
            cur.execute(
                "SELECT id::text, source, name_es FROM foods WHERE source = ANY(%s)",
                (sorted({r.source for r in rules}),),
            )
            foods = cur.fetchall()
            stats.read = len(foods)
            for food_id, factor in assign_factors(foods, rules).items():
                cur.execute(
                    "UPDATE foods SET cooking_yield_factor = %s WHERE id = %s::uuid "
                    "AND cooking_yield_factor IS DISTINCT FROM %s",
                    (factor, food_id, factor),
                )
                stats.upserted += cur.rowcount
    finally:
        conn.close()
    return stats
