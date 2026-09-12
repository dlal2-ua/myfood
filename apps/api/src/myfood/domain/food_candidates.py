"""Selección de alimentos candidatos para un plan (compartida entre el
motor determinista, `routers/diet_plans.py`, y el flujo de iafood,
`ai/flows/diet_plan.py`, sección 10.6 — el mismo RAG de candidatos que se
le pasa filtrado a la IA es el que ya usaba el motor de la Fase 4). No es un
caso de "duplicación deliberada" como la cadena de fórmulas de objetivos
(`_day_targets`, ver `routers/water.py`/`routers/diet_plans.py`): aquí sí
hay una única fuente de verdad porque las reglas de exclusión son bastante
más grandes (SQL con varios filtros) y no hay ningún motivo para que iafood
vea un conjunto de alimentos "seguros" distinto del que ve el motor.

Extraído de `routers/diet_plans.py` (Fase 4) al construir el flujo de
iafood (Fase 5) — mismo comportamiento, solo relocalizado.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from myfood.db.models import PlanItemAlternative
from myfood.domain.diet_engine import CandidateFood

CANDIDATE_BUCKET_SIZE = 40

# Alimentos con más proteína/carbohidrato/grasa respectivamente, más los de
# mejor `quality_rank` en general — un candidato puede aparecer en varios
# cubos, se deduplica por id. Heurística simple (documentada como tal en
# `domain/diet_engine.py`): el catálogo no tiene una taxonomía de grupos de
# alimentos limpia entre fuentes (USDA/CIQUAL/BEDCA/OFF), así que no se
# puede pedir "N por grupo" de forma fiable — esto garantiza que el solver
# tenga materia prima de cada macronutriente en vez de un muestreo que por
# azar salga, p. ej., todo verduras bajas en proteína.
#
# Deliberadamente SIN cubo de fibra: el solver no optimiza fibra (no es uno
# de sus objetivos, ver `domain/diet_engine.py`), así que ese cubo solo
# aportaba candidatos elegidos por un criterio que nadie iba a usar —
# encontrado así probando un plan real: arrastraba salvado de maíz, algas
# deshidratadas y similares (altísima fibra, pero nadie se come 300 g de
# alga seca), inflando kcal/macros sin ningún beneficio a cambio.
CANDIDATE_BUCKETS = (
    "fn.protein_100g DESC",
    "fn.carbs_100g DESC",
    "fn.fat_100g DESC",
    "f.quality_rank ASC",
)

# Un alimento "de verdad" (no un ingrediente concentrado como aceite puro,
# manteca, o un producto casi sin calorías como un caldo o una infusión) cae
# casi siempre en este rango de kcal/100g — filtro simple pero efectivo
# para dejar fuera aceites/grasas puras (aceite de oliva ronda 884 kcal,
# manteca vegetal ~900) y productos casi vacíos de kcal (salvados, algas
# deshidratadas, edulcorantes) que de otro modo dominan los cubos de arriba
# por su densidad de macro sin ser algo que se coma en cantidad real.
# Limitación conocida de esta v1: los aceites/grasas de cocina quedan fuera
# de la selección automática (se añaden en la preparación, no como "un
# alimento" discreto del plan) — no se modela todavía.
MIN_REALISTIC_KCAL_100G = 20
MAX_REALISTIC_KCAL_100G = 600

EXCLUDE_RESTRICTED_SQL = """
    f.id NOT IN (
        SELECT fa.food_id FROM food_allergens fa
        JOIN user_restrictions ur
          ON ur.allergen_code = fa.allergen_code AND ur.kind = 'allergen'
        WHERE ur.user_id = :user_id
    )
    AND f.id NOT IN (
        SELECT ur.food_id FROM user_restrictions ur
        WHERE ur.user_id = :user_id AND ur.food_id IS NOT NULL
    )
"""

# Especias/hierbas/edulcorantes/condimentos no son "un alimento de la
# comida" en cantidades de 20-400 g (los límites del solver, ver
# `domain/diet_engine.py`) — sin este filtro el `ORDER BY protein/carbs/
# fat/fiber DESC` de los cubos de abajo puede elegir, p. ej., 400 g de
# canela en polvo o un edulcorante de mesa por su densidad de macros,
# aunque nadie los coma así en la vida real. Encontrado verificando a mano
# la salida de un plan generado de verdad contra el catálogo completo,
# no es hipotético. `\m`/`\M` en el regex son límites de palabra de
# Postgres — sin ellos "especias" (spices) también atraparía "especial"
# ("Pan especial", "especiales"), un falso positivo real que sí se dio
# probando esto (excluía panes especiales por error).
NON_STAPLE_CATEGORY_PATTERN = (
    r"\mspice|\mherb|sweetener|condiment|\mépice|aromat|edulcor|\mespecias?\M"
)
EXCLUDE_NON_STAPLE_CATEGORY_SQL = f"""
    (f.category IS NULL OR f.category !~* '{NON_STAPLE_CATEGORY_PATTERN}')
"""

# Dos comprobaciones más, encontradas verificando a mano la salida de un
# plan generado de verdad contra el catálogo completo (no hipotéticas):
#
# 1. Ningún macronutriente por sí solo debe aportar más del 90% de las
#    kcal declaradas — deja fuera azúcar/almidón/grasa/proteína puros
#    (p. ej. "Azúcar blanco": 100% de las kcal vienen de carbohidratos).
#    Sin esto el solver combina varios "ingredientes puros" de un solo
#    macronutriente cada uno en vez de alimentos reales con varios
#    macros a la vez, y la kcal total se dispara como efecto secundario
#    de sumar varias masas grandes independientes.
# 2. `kcal_100g` declarado debe ser razonablemente coherente con el que
#    implican sus propias macros (proteína/carbohidratos 4 kcal/g, grasa
#    9 kcal/g) — encontrado un caso real de dato erróneo en el catálogo
#    ("Queso de alcampo": declara 6 kcal/100g con 55 g de proteína y 36 g
#    de grasa, que a solas ya implican >540 kcal) que las reglas de
#    descarte del ETL (sección 11.2) no detectan porque solo comprueban
#    "sin kcal" / "kcal>900" / "macros>100g", nunca la coherencia
#    kcal-vs-macros. Margen amplio (0,5×-2×) para no descartar variación
#    real de redondeo/medición, no para "arreglar" el dato.
MACRO_CONSISTENCY_SQL = """
    AND GREATEST(fn.protein_100g * 4, fn.fat_100g * 9, fn.carbs_100g * 4) <= fn.kcal_100g * 0.9
    AND fn.kcal_100g >= (fn.protein_100g * 4 + fn.fat_100g * 9 + fn.carbs_100g * 4) * 0.5
    AND fn.kcal_100g
        <= GREATEST((fn.protein_100g * 4 + fn.fat_100g * 9 + fn.carbs_100g * 4) * 2.0, 50)
"""


async def select_candidates(session: AsyncSession, user_id: UUID) -> list[CandidateFood]:
    seen: dict[str, CandidateFood] = {}
    for order_by in CANDIDATE_BUCKETS:
        stmt = text(f"""
            SELECT f.id, f.name_es, f.category, fn.kcal_100g, fn.protein_100g,
                   fn.fat_100g, fn.carbs_100g
            FROM foods f
            JOIN food_nutrients fn ON fn.food_id = f.id
            WHERE f.kind IN ('generic', 'branded')
              AND fn.kcal_100g BETWEEN {MIN_REALISTIC_KCAL_100G} AND {MAX_REALISTIC_KCAL_100G}
              AND {EXCLUDE_RESTRICTED_SQL}
              AND {EXCLUDE_NON_STAPLE_CATEGORY_SQL}
              {MACRO_CONSISTENCY_SQL}
            ORDER BY {order_by}
            LIMIT :bucket_size
        """)
        rows = (
            await session.execute(
                stmt, {"user_id": str(user_id), "bucket_size": CANDIDATE_BUCKET_SIZE}
            )
        ).all()
        for row in rows:
            seen[str(row.id)] = CandidateFood(
                id=str(row.id),
                name_es=row.name_es,
                kcal_100g=float(row.kcal_100g),
                protein_100g=float(row.protein_100g),
                fat_100g=float(row.fat_100g),
                carbs_100g=float(row.carbs_100g),
                category=row.category,
            )
    return list(seen.values())


async def compute_alternatives_for_item(
    session: AsyncSession, plan_item_id: UUID, food_id: UUID, grams: float, user_id: UUID
) -> None:
    """Top-3 alimentos nutricionalmente más cercanos (pgvector, distancia
    L2) entre los que el usuario puede comer — se salta en silencio (0
    alternativas) si `food_vectors` todavía no tiene el alimento, nunca
    inventa una alternativa (R9). Compartida entre el motor determinista
    (`routers/diet_plans.py`) y las propuestas aprobadas de iafood
    (`ai/flows/diet_plan.py`) — ambas materializan `plan_items` iguales."""
    rows = (
        await session.execute(
            text(f"""
                SELECT fv2.food_id AS food_id, (fv1.vec <-> fv2.vec) AS distance
                FROM food_vectors fv1
                JOIN food_vectors fv2 ON fv2.food_id != fv1.food_id
                JOIN foods f ON f.id = fv2.food_id
                JOIN food_nutrients fn ON fn.food_id = fv2.food_id
                WHERE fv1.food_id = :food_id
                  AND fn.kcal_100g BETWEEN {MIN_REALISTIC_KCAL_100G} AND {MAX_REALISTIC_KCAL_100G}
                  AND {EXCLUDE_RESTRICTED_SQL}
                  AND {EXCLUDE_NON_STAPLE_CATEGORY_SQL}
                  {MACRO_CONSISTENCY_SQL}
                ORDER BY fv1.vec <-> fv2.vec
                LIMIT 3
            """),
            {"food_id": str(food_id), "user_id": str(user_id)},
        )
    ).all()
    for rank, row in enumerate(rows, start=1):
        session.add(
            PlanItemAlternative(
                plan_item_id=plan_item_id,
                food_id=row.food_id,
                grams=grams,
                rank=rank,
                distance=round(float(row.distance), 4),
            )
        )
