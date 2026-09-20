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

from collections.abc import Mapping
from dataclasses import dataclass, field

import pulp

from myfood.domain.food_groups import MealTemplate

MAX_GRAMS_PER_ITEM = 400.0
MIN_GRAMS_PER_ITEM = 20.0
MAX_ITEMS_PER_MEAL = 4
VARIETY_PENALTY_WEIGHT = 0.05
SOLVER_TIME_LIMIT_SECONDS = 10
GRAMS_STEP = 5.0
# El solver para cuando está a menos de este margen relativo del óptimo: pulir el último 1 % cuesta
# segundos y no cambia el plan.
SOLVER_GAP_REL = 0.01

# Pesos de las desviaciones (sección 9): la proteína pesa más porque es el macro que peor tolera
# quedarse corto. Se aplican sobre la desviación relativa al propio objetivo.
DEVIATION_WEIGHTS = {"kcal": 1.0, "protein": 1.5, "fat": 0.6, "carbs": 0.4}
# Margen relativo dentro del cual no se penaliza la desviación de cada objetivo: clavar los
# números al gramo obliga a añadir «rellenos» de 20 g que nadie pondría en un plato, y un plan que
# se queda a un 2 % de las kcal es igual de bueno.
DEVIATION_DEADBAND = {"kcal": 0.02, "protein": 0.03, "fat": 0.06, "carbs": 0.06}
# Peso de acercar cada comida a su parte de las kcal del día: sin él el solver concentra casi todo
# en una sola comida (probado a mano: desayuno enorme y cena de 20 g de judías verdes).
MEAL_SHARE_WEIGHT = 0.25
# Una comida con muy pocos alimentos vale más que una con muchos que apenas aportan.
ITEM_COUNT_TIEBREAK = 0.003
# Bonificación por cada alimento «de diario» (pollo, merluza, tomate…) que entra en una comida:
# a igualdad de macros, el solver prefiere lo que la gente cocina de verdad.
STAPLE_BONUS = 0.01
# Si las kcal del día se desvían más de esto del objetivo, el día se marca `TARGETS_NOT_MET`.
KCAL_TOLERANCE = 0.05
TARGETS_NOT_MET = "TARGETS_NOT_MET"


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
    # Grupo alimentario (`domain/food_groups.py`) y cantidades razonables para ese alimento. Con
    # `group` el solver arma cada comida con los grupos que le tocan; sin él (candidatos genéricos,
    # como en los tests puros) se comporta como antes.
    group: str | None = None
    min_grams: float | None = None
    max_grams: float | None = None
    # Solo los usa la selección del pool de cada día (`food_candidates.sample_day_pool`), no el
    # solver: fuente del dato y si el producto trae los datos nutricionales completos.
    source: str | None = None
    complete_data: bool = False
    staple: bool = False


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
    # `False` si el solver agotó el tiempo y devuelve la mejor solución que encontró.
    is_optimal: bool = True
    # `TARGETS_NOT_MET` si las kcal del día quedan a más de un 5 % del objetivo.
    warning: str | None = None


def _round_to_step(grams: float, step: float) -> float:
    return round(grams / step) * step if step > 0 else round(grams, 1)


# A partir de cuatro usos repetir un alimento ya no cuesta más: sin tope, en un catálogo pequeño la
# penalización acumulada acabaría pesando más que cumplir los objetivos.
MAX_COUNTED_USES = 4


def _used_count(recently_used: frozenset[str] | Mapping[str, int], food_id: str) -> int:
    if isinstance(recently_used, Mapping):
        return min(int(recently_used.get(food_id, 0)), MAX_COUNTED_USES)
    return 1 if food_id in recently_used else 0


def solve_day(
    candidates: list[CandidateFood],
    targets: DayTargets,
    meal_types: list[str],
    recently_used_food_ids: frozenset[str] | Mapping[str, int] = frozenset(),
    *,
    max_items_per_meal: int = MAX_ITEMS_PER_MEAL,
    min_grams_per_item: float = MIN_GRAMS_PER_ITEM,
    max_grams_per_item: float = MAX_GRAMS_PER_ITEM,
    variety_penalty_weight: float = VARIETY_PENALTY_WEIGHT,
    meal_kcal_shares: Mapping[str, float] | None = None,
    meal_templates: Mapping[str, MealTemplate] | None = None,
    grams_step: float = GRAMS_STEP,
    time_limit_seconds: int = SOLVER_TIME_LIMIT_SECONDS,
) -> DayPlan:
    """Genera un único día de plan. El llamador itera esta función día a día
    para una semana completa, acumulando `recently_used_food_ids` (o cuántas
    veces se ha usado cada alimento) — resolver la semana entera de una vez
    dispararía el tamaño del MIP sin necesidad (sección "Motor de generación
    de dietas" no exige optimalidad conjunta, solo variedad razonable entre días).

    - `meal_kcal_shares`: parte de las kcal del día que le toca a cada comida; se persigue
      como meta blanda, no como restricción, para que el problema nunca sea infactible.
    - `meal_templates`: qué grupos alimentarios entran en cada comida (y cuántos), para los
      candidatos que traen `group`. Un candidato sin grupo puede ir en cualquier comida.
    - Los gramos se redondean a múltiplos de `grams_step` y los totales se recalculan con ellos.
    """
    if not candidates or not meal_types:
        return DayPlan(feasible=False, meals=[], totals=DayTargets(0, 0, 0, 0))

    def _allowed(food: CandidateFood, meal: str) -> bool:
        if meal_templates is None or food.group is None:
            return True
        template = meal_templates.get(meal)
        return template is None or food.group in template.caps

    def _bounds(food: CandidateFood) -> tuple[float, float]:
        low = food.min_grams if food.min_grams is not None else min_grams_per_item
        high = food.max_grams if food.max_grams is not None else max_grams_per_item
        return low, high

    food_by_id = {f.id: f for f in candidates}
    meal_candidates = {m: [f for f in candidates if _allowed(f, m)] for m in meal_types}
    active_meals = [m for m in meal_types if meal_candidates[m]]
    if not active_meals:
        return DayPlan(feasible=False, meals=[], totals=DayTargets(0, 0, 0, 0))

    prob = pulp.LpProblem("myfood_day_plan", pulp.LpMinimize)

    x: dict[tuple[str, str], pulp.LpVariable] = {}
    y: dict[tuple[str, str], pulp.LpVariable] = {}
    for meal in active_meals:
        template = meal_templates.get(meal) if meal_templates else None
        for food in meal_candidates[meal]:
            low, high = _bounds(food)
            key = (meal, food.id)
            x[key] = pulp.LpVariable(f"x_{meal}_{food.id}", lowBound=0, upBound=high)
            y[key] = pulp.LpVariable(f"y_{meal}_{food.id}", cat="Binary")
            prob += x[key] <= high * y[key]
            prob += x[key] >= low * y[key]
        cap = template.max_items if template is not None else max_items_per_meal
        prob += pulp.lpSum(y[meal, f.id] for f in meal_candidates[meal]) <= cap
        prob += pulp.lpSum(y[meal, f.id] for f in meal_candidates[meal]) >= 1

        if template is not None:
            for group, group_cap in template.caps.items():
                members = [f for f in meal_candidates[meal] if f.group == group]
                if members:
                    prob += pulp.lpSum(y[meal, f.id] for f in members) <= group_cap
            for union, union_cap in template.union_caps:
                members = [f for f in meal_candidates[meal] if f.group in union]
                if members:
                    prob += pulp.lpSum(y[meal, f.id] for f in members) <= union_cap
            for required in template.required:
                members = [f for f in meal_candidates[meal] if f.group in required]
                if members:  # sin candidatos de ese grupo no se puede exigir
                    prob += pulp.lpSum(y[meal, f.id] for f in members) >= 1

    def _expr(attr: str, meals: list[str]) -> pulp.LpAffineExpression:
        return pulp.lpSum(
            x[meal, f.id] * getattr(f, attr) / 100 for meal in meals for f in meal_candidates[meal]
        )

    deviation_terms = []
    for name, attr, target_value in (
        ("kcal", "kcal_100g", targets.kcal),
        ("protein", "protein_100g", targets.protein_g),
        ("fat", "fat_100g", targets.fat_g),
        ("carbs", "carbs_100g", targets.carbs_g),
    ):
        pos = pulp.LpVariable(f"dev_{name}_pos", lowBound=0)
        neg = pulp.LpVariable(f"dev_{name}_neg", lowBound=0)
        band = DEVIATION_DEADBAND[name] * target_value
        expr = _expr(attr, active_meals)
        prob += expr - target_value <= band + pos
        prob += target_value - expr <= band + neg
        # Escalado por el propio objetivo: sin esto, la desviación de kcal
        # (cientos/miles) dominaría sobre la de proteína (decenas/cientos) y
        # el solver ignoraría de facto los macros para pulir solo kcal.
        scale = max(target_value, 1.0)
        deviation_terms.append(DEVIATION_WEIGHTS[name] * (pos + neg) / scale)

    share_terms = []
    if meal_kcal_shares:
        share_total = sum(meal_kcal_shares.get(m, 0.0) for m in active_meals) or 1.0
        for meal in active_meals:
            meal_target = targets.kcal * meal_kcal_shares.get(meal, 0.0) / share_total
            if meal_target <= 0:
                continue
            pos = pulp.LpVariable(f"meal_{meal}_pos", lowBound=0)
            neg = pulp.LpVariable(f"meal_{meal}_neg", lowBound=0)
            prob += _expr("kcal_100g", [meal]) - meal_target == pos - neg
            share_terms.append(MEAL_SHARE_WEIGHT * (pos + neg) / meal_target)

    variety_terms = []
    for meal in active_meals:
        for food in meal_candidates[meal]:
            count = _used_count(recently_used_food_ids, food.id)
            if count:
                variety_terms.append(variety_penalty_weight * count * y[meal, food.id])

    item_terms = [ITEM_COUNT_TIEBREAK * y[key] for key in y]
    staple_terms = [
        -STAPLE_BONUS * y[meal, f.id]
        for meal in active_meals
        for f in meal_candidates[meal]
        if f.staple
    ]

    prob += (
        pulp.lpSum(deviation_terms)
        + pulp.lpSum(share_terms)
        + pulp.lpSum(variety_terms)
        + pulp.lpSum(item_terms)
        + pulp.lpSum(staple_terms)
    )
    prob.solve(pulp.PULP_CBC_CMD(msg=False, timeLimit=time_limit_seconds, gapRel=SOLVER_GAP_REL))
    is_optimal = prob.sol_status == pulp.LpSolutionOptimal

    meals_out = []
    for meal in meal_types:
        items = []
        for food in meal_candidates[meal]:
            variable = x.get((meal, food.id))
            raw = variable.value() if variable is not None else None
            if not raw or raw <= 0.5:
                continue
            low, high = _bounds(food)
            grams = min(max(_round_to_step(raw, grams_step), low), high)
            items.append(PlannedItem(food_id=food.id, grams=round(grams, 1)))
        meals_out.append(PlannedMeal(meal_type=meal, items=items))

    feasible = any(m.items for m in meals_out)
    totals = _actual_totals(meals_out, food_by_id) if feasible else DayTargets(0, 0, 0, 0)
    warning = None
    off_target = abs(totals.kcal - targets.kcal) > targets.kcal * KCAL_TOLERANCE
    if feasible and targets.kcal > 0 and off_target:
        warning = TARGETS_NOT_MET
    return DayPlan(
        feasible=feasible, meals=meals_out, totals=totals, is_optimal=is_optimal, warning=warning
    )


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
