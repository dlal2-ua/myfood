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

import functools
import random
import re
import unicodedata
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from myfood.db.models import PlanItemAlternative
from myfood.domain.diet_engine import CandidateFood
from myfood.domain.food_groups import (
    OIL_FAT,
    PLANNABLE_GROUPS,
    classify_food,
    gram_bounds,
    is_staple,
)

# Solo se arman planes con alimentos de fuentes con nombre en español: un plan con «Beef,
# chuck, arm pot roast…» no lo puede leer nadie.
#
# USDA y CIQUAL entraron aquí cuando se tradujeron sus 10.171 nombres (migración 0021). Hasta
# entonces la lista eran BEDCA y OFF, y eso dejaba el motor trabajando con 429 genéricos frente
# a 11.194 productos de supermercado: las alternativas a «pechuga de pollo» salían siendo otras
# tres marcas de pechuga de pollo, porque por cercanía nutricional lo más parecido a un producto
# de marca es el mismo producto de otra marca. Con los genéricos dentro, una alternativa vuelve
# a ser otro alimento.
PLAN_SOURCES = ("bedca", "off", "usda_foundation", "usda_sr", "ciqual")

# Rango de kcal/100 g que tiene sentido para un alimento de cada grupo. Los aceites (~880) y los
# frutos secos (~650) quedan fuera del rango general porque son grasa concentrada por naturaleza;
# los alimentos casi sin energía (algas secas, edulcorantes) ni entran en ningún plan.
_KCAL_RANGE: dict[str, tuple[float, float]] = {
    OIL_FAT: (500.0, 900.0),
    "nuts": (300.0, 750.0),
}
_DEFAULT_KCAL_RANGE = (20.0, 600.0)

_SIMPLE_NAME = re.compile(r"^[^\d]{3,42}$")

# Alergias E intolerancias (sección 9: "restricciones duras: alergias,
# intolerancias y alimentos vetados"): una intolerancia a la lactosa es un
# `user_restrictions` con `allergen_code='lacteos'` igual que una alergia, y
# para el plan de un usuario ambas se tratan igual — excluir el alimento.
# `food_allergens` recoge tanto lo declarado como las trazas ("puede contener")
# y lo inferido para genéricos (`origin`, migración 0012): para una alergia
# todo cuenta.
EXCLUDE_RESTRICTED_SQL = """
    f.id NOT IN (
        SELECT fa.food_id FROM food_allergens fa
        JOIN user_restrictions ur
          ON ur.allergen_code = fa.allergen_code AND ur.kind IN ('allergen', 'intolerance')
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

_CANDIDATES_SQL = text(f"""
    SELECT f.id, f.name_es, f.category, f.source, f.nutriscore_grade,
           fn.kcal_100g, fn.protein_100g, fn.fat_100g, fn.carbs_100g
    FROM foods f
    JOIN food_nutrients fn ON fn.food_id = f.id
    WHERE f.kind IN ('generic', 'branded')
      AND f.source = ANY(:sources)
      AND fn.kcal_100g BETWEEN 20 AND 900
      AND {EXCLUDE_RESTRICTED_SQL}
      AND {EXCLUDE_NON_STAPLE_CATEGORY_SQL}
""")


@functools.lru_cache(maxsize=32768)
def _group_of(name: str, category: str | None) -> str:
    return classify_food(name, category)


def _plausible(group: str, kcal: float, protein: float, fat: float, carbs: float) -> bool:
    """Descarta datos incoherentes: kcal fuera del rango del grupo o que no cuadran con sus
    propios macros (proteína/carbohidratos 4 kcal/g, grasa 9 kcal/g). Margen amplio (0,5×–2×)
    para no descartar variación real de redondeo o medición; no «arregla» ningún dato."""
    low, high = _KCAL_RANGE.get(group, _DEFAULT_KCAL_RANGE)
    if not low <= kcal <= high:
        return False
    implied = protein * 4 + fat * 9 + carbs * 4
    if kcal < implied * 0.5 or kcal > max(implied * 2.0, 50):
        return False
    # Ningún macro por sí solo debe dar más del 90 % de las kcal (azúcar, almidón o proteína
    # puros), salvo en las grasas de cocina, que sí lo son.
    return group == OIL_FAT or max(protein * 4, fat * 9, carbs * 4) <= kcal * 0.9


async def select_candidates(session: AsyncSession, user_id: UUID) -> list[CandidateFood]:
    """Todos los alimentos con los que se puede armar un plan para este usuario: de fuentes en
    español, sin lo que le prohíben sus restricciones (alérgenos, intolerancias, vetados), con
    su grupo alimentario y unas cantidades razonables. Elegir cuáles entran cada día es cosa
    del llamador (`sample_day_pool`)."""
    rows = (
        await session.execute(
            _CANDIDATES_SQL, {"user_id": str(user_id), "sources": list(PLAN_SOURCES)}
        )
    ).all()
    candidates: list[CandidateFood] = []
    for row in rows:
        group = _group_of(row.name_es, row.category)
        if group not in PLANNABLE_GROUPS:
            continue
        kcal = float(row.kcal_100g)
        protein, fat, carbs = (
            float(row.protein_100g),
            float(row.fat_100g),
            float(row.carbs_100g),
        )
        if not _plausible(group, kcal, protein, fat, carbs):
            continue
        bounds = gram_bounds(group, kcal)
        candidates.append(
            CandidateFood(
                id=str(row.id),
                name_es=row.name_es,
                kcal_100g=kcal,
                protein_100g=protein,
                fat_100g=fat,
                carbs_100g=carbs,
                category=row.category,
                group=group,
                min_grams=bounds.min_g,
                max_grams=bounds.max_g,
                source=row.source,
                complete_data=row.nutriscore_grade is not None,
                staple=is_staple(group, row.name_es),
            )
        )
    return candidates


# Alimentos de cada grupo que entran en el modelo de un día: pocos y distintos cada día para que
# el solver sea rápido y la semana tenga variedad.
_POOL_PER_GROUP = 6
_POOL_MAX_MARKET = 2
# Con más alimentos por grupo el pool es más variado, a costa de un modelo mayor (o de más tokens
# si se le pasa a la IA): iafood usa el doble.
IAFOOD_POOL_PER_GROUP = 12
# Lo que no es de diario solo completa el grupo cuando hay muy pocos alimentos de diario.
_MIN_STAPLES = 3


def sample_day_pool(
    candidates: list[CandidateFood], rng: random.Random, per_group: int = _POOL_PER_GROUP
) -> list[CandidateFood]:
    """Subconjunto de los candidatos para resolver un día. En cada grupo se prefiere, por este
    orden: lo de diario con dato oficial (BEDCA), lo de diario de supermercado con nombre
    sencillo y datos completos, lo oficial que no es de diario y, por último, lo de
    supermercado que tampoco lo es. Los productos de Open Food Facts los introduce la
    comunidad y son de peor calidad, así que como mucho `_POOL_MAX_MARKET` por grupo.
    Los candidatos sin grupo (los pasa el llamador ya elegidos) entran todos."""
    pool = [c for c in candidates if c.group is None]
    by_group: dict[str, list[CandidateFood]] = {}
    for candidate in candidates:
        if candidate.group is not None:
            by_group.setdefault(candidate.group, []).append(candidate)
    for _group, members in sorted(by_group.items()):
        official = [c for c in members if c.source != "off"]
        market = [
            c
            for c in members
            if c.source == "off" and c.complete_data and _SIMPLE_NAME.match(c.name_es)
        ]
        staples_available = sum(1 for c in members if c.staple)
        tiers = [
            [c for c in official if c.staple],
            [c for c in market if c.staple],
            [c for c in official if not c.staple] if staples_available < _MIN_STAPLES else [],
            [c for c in market if not c.staple] if staples_available < _MIN_STAPLES else [],
        ]
        chosen: list[CandidateFood] = []
        market_taken = 0
        market_cap = max(_POOL_MAX_MARKET, per_group // 3)
        for index, tier in enumerate(tiers):
            rng.shuffle(tier)
            is_market = index in (1, 3)
            for candidate in tier:
                if len(chosen) >= per_group:
                    break
                if is_market and market_taken >= market_cap and official:
                    break
                chosen.append(candidate)
                market_taken += is_market
        pool += chosen
    return pool


@dataclass
class Alternative:
    food_id: UUID
    name_es: str
    brand: str | None
    kcal_100g: float
    distance: float
    grams: float


def _alternatives_sql(restrict_sources: str):
    return text(f"""
        SELECT fv2.food_id AS food_id, f.name_es, f.brand, f.category, fn.kcal_100g,
               fn.protein_100g, (fv1.vec <-> fv2.vec) AS distance
        FROM food_vectors fv1
        JOIN food_vectors fv2 ON fv2.food_id != fv1.food_id
        JOIN foods f ON f.id = fv2.food_id
        JOIN food_nutrients fn ON fn.food_id = fv2.food_id
        WHERE fv1.food_id = :food_id
          AND fn.kcal_100g > 0
          AND {restrict_sources}
          AND {EXCLUDE_RESTRICTED_SQL}
          AND {EXCLUDE_NON_STAPLE_CATEGORY_SQL}
        ORDER BY fv1.vec <-> fv2.vec
        LIMIT :pool
    """)


_ALTERNATIVES_POOL = 120
# Cuánto puede salirse de las cantidades razonables del grupo el gramaje ajustado.
_ADJUST_SLACK = (0.7, 1.3)


def _adjust_grams(grams: float, original: float, alternative: float) -> float | None:
    if alternative <= 0 or original <= 0:
        return None
    adjusted = grams * original / alternative
    return max(5.0, round(adjusted / 5) * 5)


# Palabras que no distinguen un alimento de otro: si dos nombres solo se diferencian en éstas,
# son el mismo alimento escrito con más o menos detalle.
_ALTERNATIVE_STOPWORDS = frozenset(
    """de del la el los las y con sin al a en un una fresco fresca frescos frescas natural
    naturales crudo cruda crudos crudas entero entera enteros enteras tipo variedad gr g kg
    envasado envasada envasados envasadas""".split()
)


def _significant_words(name: str) -> frozenset[str]:
    plain = unicodedata.normalize("NFD", name.lower())
    plain = "".join(c for c in plain if unicodedata.category(c) != "Mn")
    words = re.findall(r"[a-z]+", plain)
    return frozenset(w for w in words if len(w) > 2 and w not in _ALTERNATIVE_STOPWORDS)


def _is_the_same_food(a: frozenset[str], b: frozenset[str]) -> bool:
    """Si las palabras de un nombre contienen todas las del otro, es el mismo alimento.

    «Pechuga de pollo» y «Filete de pechuga de pollo» no son alternativas: son el mismo
    alimento de otra marca. Y por cercanía nutricional son justo lo primero que sale, porque
    lo más parecido a un producto envasado es el mismo producto envasado por otro. La regla es
    de subconjunto y no de parecido: «Pavo, pechuga» comparte «pechuga» con «Pechuga de pollo»
    y sí es una alternativa de verdad, así que no puede caer.
    """
    if not a or not b:
        return False
    return a <= b or b <= a


async def find_alternatives(
    session: AsyncSession,
    food_id: UUID,
    grams: float,
    user_id: UUID,
    *,
    keep: str = "kcal",
    limit: int = 3,
) -> list[Alternative]:
    """Alimentos más parecidos (distancia L2 sobre `food_vectors`) que el usuario puede comer,
    del MISMO grupo alimentario — pollo por pavo, no por queso curado aunque los macros cuadren —
    y con los gramos recalculados para conservar las kcal (o la proteína) del hueco original.
    Nunca se devuelve una alternativa sin ajustar ni una que exigiría una cantidad absurda.
    Si el alimento no tiene grupo conocido, no se filtra por grupo (no se inventa uno)."""
    original = (
        await session.execute(
            text("""
                SELECT f.name_es, f.category, f.source, fn.kcal_100g, fn.protein_100g
                FROM foods f JOIN food_nutrients fn ON fn.food_id = f.id
                WHERE f.id = :food_id
            """),
            {"food_id": str(food_id)},
        )
    ).first()
    if original is None:
        return []
    group = _group_of(original.name_es, original.category)
    keep_group = group in PLANNABLE_GROUPS
    restrict = "f.source = ANY(:sources)" if original.source in PLAN_SOURCES else "TRUE"
    params: dict = {"food_id": str(food_id), "user_id": str(user_id), "pool": _ALTERNATIVES_POOL}
    if original.source in PLAN_SOURCES:
        params["sources"] = list(PLAN_SOURCES)
    rows = (await session.execute(_alternatives_sql(restrict), params)).all()

    original_kcal = float(original.kcal_100g)
    original_protein = float(original.protein_100g or 0)
    seen_names = {original.name_es.strip().lower()}
    original_words = _significant_words(original.name_es)
    seen_words = [original_words]
    alternatives: list[Alternative] = []
    for row in rows:
        name_key = row.name_es.strip().lower()
        if name_key in seen_names:
            continue
        words = _significant_words(row.name_es)
        if any(_is_the_same_food(words, other) for other in seen_words):
            continue
        if keep_group and _group_of(row.name_es, row.category) != group:
            continue
        alt_kcal = float(row.kcal_100g)
        if keep == "protein":
            adjusted = _adjust_grams(grams, original_protein, float(row.protein_100g or 0))
        else:
            adjusted = _adjust_grams(grams, original_kcal, alt_kcal)
        if adjusted is None:
            continue
        if keep_group:
            bounds = gram_bounds(group, alt_kcal)
            if not bounds.min_g * _ADJUST_SLACK[0] <= adjusted <= bounds.max_g * _ADJUST_SLACK[1]:
                continue
        seen_names.add(name_key)
        seen_words.append(words)
        alternatives.append(
            Alternative(
                food_id=row.food_id,
                name_es=row.name_es,
                brand=row.brand,
                kcal_100g=alt_kcal,
                distance=round(float(row.distance), 4),
                grams=adjusted,
            )
        )
        if len(alternatives) >= limit:
            break
    return alternatives


async def compute_alternatives_for_item(
    session: AsyncSession,
    plan_item_id: UUID,
    food_id: UUID,
    grams: float,
    user_id: UUID,
    keep: str = "kcal",
) -> None:
    """Guarda las 3 mejores alternativas de un alimento del plan (con los gramos ya ajustados);
    si `food_vectors` todavía no tiene el alimento o no hay ninguna del mismo grupo, no guarda
    ninguna — nunca se inventa una alternativa (R9). Compartida entre el motor determinista
    (`routers/diet_plans.py`) y las propuestas aprobadas de iafood (`ai/flows/diet_plan.py`)."""
    for rank, alternative in enumerate(
        await find_alternatives(session, food_id, grams, user_id, keep=keep), start=1
    ):
        session.add(
            PlanItemAlternative(
                plan_item_id=plan_item_id,
                food_id=alternative.food_id,
                grams=alternative.grams,
                rank=rank,
                distance=alternative.distance,
            )
        )
