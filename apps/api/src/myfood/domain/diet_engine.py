"""Motor de generación de dietas (Fase 4, sección "Motor de generación de
dietas (determinista)") — Mixed Integer Goal Programming con PuLP.

Independiente de la IA (R1): esta función nunca se llama con datos que no
vengan ya validados — los objetivos de kcal/macros los calcula `/calc/targets`
(que ya aplica el suelo de seguridad R6), y los candidatos vienen filtrados
de alergias/restricciones *antes* de llegar aquí (sección "Alimentos
similares"). El motor solo decide gramajes; nunca inventa un alimento, un
precio o un tiempo de cocina que no exista en el catálogo (R9) — ver
limitaciones documentadas más abajo.

Formulación (goal programming, evita las infactibilidades típicas del
problema de la dieta de Stigler al usar metas blandas en vez de duras):
- Variables continuas `x[comida, alimento]` = gramos (acotadas por comida).
- Variables binarias `y[comida, alimento]` = ¿se usa este alimento en esta
  comida? — vinculadas a `x` con bigM, limitan cuántos alimentos distintos
  entran en cada comida (evita platos con 20 ingredientes a la vez).
- Variables de desviación (positiva/negativa) para kcal/proteína/grasa/
  carbohidratos del día completo — el objetivo minimiza su suma, escalada
  por el propio objetivo para que kcal (cientos/miles) no eclipse a
  proteína (decenas/cientos) en la función objetivo.
- Penalización blanda por repetir un alimento usado en días anteriores de
  la misma semana (variedad, sección "Motor de generación de dietas").

Limitaciones deliberadas de esta primera versión (no se simulan ni se
estiman para "completar" el modelo — R9 aplica también a precios/tiempos):
- Presupuesto máximo: el catálogo de `foods` no tiene ningún precio por
  alimento (no existe esa columna) — no hay dato real con el que
  restringir esto todavía. Se acepta un parámetro pero no se usa; se
  documenta explícitamente en vez de inventar un precio.
- Tiempo de cocina: los alimentos del catálogo no tienen tiempo de
  preparación (eso vive en `recipes.prep_minutes`, que todavía no participa
  en el motor — las recetas son una extensión natural, no esta versión).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pulp

MAX_GRAMS_PER_ITEM = 400.0
MIN_GRAMS_PER_ITEM = 20.0
MAX_ITEMS_PER_MEAL = 4
VARIETY_PENALTY_WEIGHT = 0.05
SOLVER_TIME_LIMIT_SECONDS = 10


@dataclass
class CandidateFood:
    id: str
    name_es: str
    kcal_100g: float
    protein_100g: float
    fat_100g: float
    carbs_100g: float
    # Solo la usa `ai/anonymize.py` (sección 10.2) para dar contexto de
    # categoría al LLM — el solver de este módulo nunca la lee.
    category: str | None = None


@dataclass
class DayTargets:
    kcal: float
    protein_g: float
    fat_g: float
    carbs_g: float


@dataclass
class PlannedItem:
    food_id: str
    grams: float


@dataclass
class PlannedMeal:
    meal_type: str
    items: list[PlannedItem] = field(default_factory=list)


@dataclass
class DayPlan:
    feasible: bool
    meals: list[PlannedMeal]
    totals: DayTargets


def solve_day(
    candidates: list[CandidateFood],
    targets: DayTargets,
    meal_types: list[str],
    recently_used_food_ids: frozenset[str] = frozenset(),
    *,
    max_items_per_meal: int = MAX_ITEMS_PER_MEAL,
    min_grams_per_item: float = MIN_GRAMS_PER_ITEM,
    max_grams_per_item: float = MAX_GRAMS_PER_ITEM,
    variety_penalty_weight: float = VARIETY_PENALTY_WEIGHT,
) -> DayPlan:
    """Genera un único día de plan. El llamador itera esta función día a día
    para una semana completa, acumulando `recently_used_food_ids` — resolver
    la semana entera de una vez dispararía el tamaño del MIP sin necesidad
    (sección "Motor de generación de dietas" no exige optimalidad conjunta,
    solo variedad razonable entre días)."""
    if not candidates or not meal_types:
        return DayPlan(feasible=False, meals=[], totals=DayTargets(0, 0, 0, 0))

    food_by_id = {f.id: f for f in candidates}
    prob = pulp.LpProblem("myfood_day_plan", pulp.LpMinimize)

    x: dict[tuple[str, str], pulp.LpVariable] = {}
    y: dict[tuple[str, str], pulp.LpVariable] = {}
    for meal in meal_types:
        for food in candidates:
            key = (meal, food.id)
            x[key] = pulp.LpVariable(f"x_{meal}_{food.id}", lowBound=0, upBound=max_grams_per_item)
            y[key] = pulp.LpVariable(f"y_{meal}_{food.id}", cat="Binary")
            prob += x[key] <= max_grams_per_item * y[key]
            prob += x[key] >= min_grams_per_item * y[key]
        prob += pulp.lpSum(y[meal, f.id] for f in candidates) <= max_items_per_meal
        prob += pulp.lpSum(y[meal, f.id] for f in candidates) >= 1

    def _total(attr: str) -> pulp.LpAffineExpression:
        return pulp.lpSum(
            x[meal, f.id] * getattr(f, attr) / 100 for meal in meal_types for f in candidates
        )

    kcal_total = _total("kcal_100g")
    protein_total = _total("protein_100g")
    fat_total = _total("fat_100g")
    carbs_total = _total("carbs_100g")

    deviation_terms = []
    for name, total_expr, target_value in (
        ("kcal", kcal_total, targets.kcal),
        ("protein", protein_total, targets.protein_g),
        ("fat", fat_total, targets.fat_g),
        ("carbs", carbs_total, targets.carbs_g),
    ):
        pos = pulp.LpVariable(f"dev_{name}_pos", lowBound=0)
        neg = pulp.LpVariable(f"dev_{name}_neg", lowBound=0)
        prob += total_expr - target_value == pos - neg
        # Escalado por el propio objetivo: sin esto, la desviación de kcal
        # (cientos/miles) dominaría sobre la de proteína (decenas/cientos) y
        # el solver ignoraría de facto los macros para pulir solo kcal.
        scale = max(target_value, 1.0)
        deviation_terms.append((pos + neg) / scale)

    variety_terms = [
        variety_penalty_weight * y[meal, food_id]
        for meal in meal_types
        for food_id in recently_used_food_ids
        if (meal, food_id) in y
    ]

    prob += pulp.lpSum(deviation_terms) + pulp.lpSum(variety_terms)
    prob.solve(pulp.PULP_CBC_CMD(msg=False, timeLimit=SOLVER_TIME_LIMIT_SECONDS))

    meals_out = []
    for meal in meal_types:
        items = [
            PlannedItem(food_id=food.id, grams=round(grams, 1))
            for food in candidates
            if (grams := x[meal, food.id].value()) and grams > 0.5
        ]
        meals_out.append(PlannedMeal(meal_type=meal, items=items))

    feasible = any(m.items for m in meals_out)
    totals = _actual_totals(meals_out, food_by_id) if feasible else DayTargets(0, 0, 0, 0)
    return DayPlan(feasible=feasible, meals=meals_out, totals=totals)


def solve_day_with_fixed_items(
    items_by_meal: dict[str, list[CandidateFood]],
    targets: DayTargets,
    *,
    min_grams_per_item: float = MIN_GRAMS_PER_ITEM,
    max_grams_per_item: float = MAX_GRAMS_PER_ITEM,
) -> DayPlan:
    """Variante para iafood (sección 10.6): a diferencia de `solve_day`, aquí
    QUÉ alimentos van en cada comida ya lo decidió la IA (function calling,
    R1 — nunca decide cantidades). No hay variables binarias de selección
    ni penalización de variedad ni conjunto candidato compartido entre
    comidas: cada alimento que la IA puso en una comida aparece siempre en
    ESA comida (nunca se reasigna a otra), con un gramaje entre
    `min_grams_per_item` y `max_grams_per_item` que el solver ajusta para
    acercarse a los objetivos del día — la misma función objetivo de
    desviaciones relativas que `solve_day`, sin el término de variedad (la
    variedad entre días ya la razona la IA en el prompt, sección 10.4)."""
    if not items_by_meal or not any(items_by_meal.values()):
        return DayPlan(feasible=False, meals=[], totals=DayTargets(0, 0, 0, 0))

    food_by_id: dict[str, CandidateFood] = {
        food.id: food for foods in items_by_meal.values() for food in foods
    }
    prob = pulp.LpProblem("myfood_day_plan_fixed", pulp.LpMinimize)

    x: dict[tuple[str, str], pulp.LpVariable] = {}
    for meal, foods in items_by_meal.items():
        for food in foods:
            x[meal, food.id] = pulp.LpVariable(
                f"x_{meal}_{food.id}", lowBound=min_grams_per_item, upBound=max_grams_per_item
            )

    def _total(attr: str) -> pulp.LpAffineExpression:
        return pulp.lpSum(
            x[meal, food.id] * getattr(food, attr) / 100
            for meal, foods in items_by_meal.items()
            for food in foods
        )

    deviation_terms = []
    for name, total_expr, target_value in (
        ("kcal", _total("kcal_100g"), targets.kcal),
        ("protein", _total("protein_100g"), targets.protein_g),
        ("fat", _total("fat_100g"), targets.fat_g),
        ("carbs", _total("carbs_100g"), targets.carbs_g),
    ):
        pos = pulp.LpVariable(f"dev_{name}_pos", lowBound=0)
        neg = pulp.LpVariable(f"dev_{name}_neg", lowBound=0)
        prob += total_expr - target_value == pos - neg
        scale = max(target_value, 1.0)
        deviation_terms.append((pos + neg) / scale)

    prob += pulp.lpSum(deviation_terms)
    prob.solve(pulp.PULP_CBC_CMD(msg=False, timeLimit=SOLVER_TIME_LIMIT_SECONDS))

    meals_out = [
        PlannedMeal(
            meal_type=meal,
            items=[
                PlannedItem(food_id=food.id, grams=round(x[meal, food.id].value(), 1))
                for food in foods
            ],
        )
        for meal, foods in items_by_meal.items()
    ]
    feasible = bool(meals_out) and all(m.items for m in meals_out)
    totals = _actual_totals(meals_out, food_by_id) if feasible else DayTargets(0, 0, 0, 0)
    return DayPlan(feasible=feasible, meals=meals_out, totals=totals)


def _actual_totals(meals: list[PlannedMeal], food_by_id: dict[str, CandidateFood]) -> DayTargets:
    """Recalcula los totales desde los gramos ya redondeados del resultado
    extraído — nunca desde el valor interno (potencialmente con ruido de
    coma flotante) de las variables del solver."""
    kcal = protein = fat = carbs = 0.0
    for meal in meals:
        for item in meal.items:
            food = food_by_id[item.food_id]
            kcal += item.grams * food.kcal_100g / 100
            protein += item.grams * food.protein_100g / 100
            fat += item.grams * food.fat_100g / 100
            carbs += item.grams * food.carbs_100g / 100
    return DayTargets(
        kcal=round(kcal, 1),
        protein_g=round(protein, 1),
        fat_g=round(fat, 1),
        carbs_g=round(carbs, 1),
    )
