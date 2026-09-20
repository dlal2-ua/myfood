"""Tests del motor de dietas (documento 2, "Motor de generación de dietas
(determinista)") — puros, sin BD. Cada valor esperado se calcula a mano
antes de escribir el assert, igual que `test_formulas.py`."""

import pytest

from myfood.domain.diet_engine import (
    CandidateFood,
    DayTargets,
    solve_day,
    solve_day_with_fixed_items,
)

CHICKEN = CandidateFood(
    "chicken", "Pechuga de pollo", kcal_100g=165, protein_100g=31, fat_100g=3.6, carbs_100g=0
)
RICE = CandidateFood(
    "rice", "Arroz blanco cocido", kcal_100g=130, protein_100g=2.7, fat_100g=0.3, carbs_100g=28
)
OIL = CandidateFood(
    "oil", "Aceite de oliva", kcal_100g=884, protein_100g=0, fat_100g=100, carbs_100g=0
)
BROCCOLI = CandidateFood(
    "broccoli", "Brócoli", kcal_100g=34, protein_100g=2.8, fat_100g=0.4, carbs_100g=7
)

BASIC_CANDIDATES = [CHICKEN, RICE, OIL, BROCCOLI]
LUNCH_TARGETS = DayTargets(kcal=500, protein_g=40, fat_g=15, carbs_g=50)


def test_empty_candidates_is_infeasible():
    plan = solve_day([], LUNCH_TARGETS, ["lunch"])
    assert plan.feasible is False
    assert plan.meals == []


def test_empty_meal_types_is_infeasible():
    plan = solve_day(BASIC_CANDIDATES, LUNCH_TARGETS, [])
    assert plan.feasible is False


def test_basic_plan_is_feasible_and_close_to_targets():
    plan = solve_day(BASIC_CANDIDATES, LUNCH_TARGETS, ["lunch"])
    assert plan.feasible is True
    assert len(plan.meals) == 1
    meal = plan.meals[0]
    assert meal.meal_type == "lunch"
    assert len(meal.items) >= 1

    # Con estos 4 alimentos (proteína limpia, carbohidrato limpio, grasa
    # pura, verdura) el solver debe poder acercarse mucho al objetivo — no
    # es un caso ajustado. Margen generoso (±15%) porque es un MIP con
    # gramajes mínimos de 20 g, no una solución continua exacta.
    assert abs(plan.totals.kcal - LUNCH_TARGETS.kcal) <= LUNCH_TARGETS.kcal * 0.15
    assert abs(plan.totals.protein_g - LUNCH_TARGETS.protein_g) <= LUNCH_TARGETS.protein_g * 0.20


def test_totals_are_recomputed_from_extracted_grams():
    plan = solve_day(BASIC_CANDIDATES, LUNCH_TARGETS, ["lunch"])
    food_by_id = {f.id: f for f in BASIC_CANDIDATES}
    expected_kcal = sum(
        item.grams * food_by_id[item.food_id].kcal_100g / 100
        for meal in plan.meals
        for item in meal.items
    )
    assert plan.totals.kcal == round(expected_kcal, 1)


def test_respects_max_items_per_meal():
    plan = solve_day(BASIC_CANDIDATES, LUNCH_TARGETS, ["lunch"], max_items_per_meal=2)
    assert len(plan.meals[0].items) <= 2


def test_respects_min_and_max_grams_per_item():
    plan = solve_day(
        BASIC_CANDIDATES,
        LUNCH_TARGETS,
        ["lunch"],
        min_grams_per_item=20.0,
        max_grams_per_item=400.0,
    )
    for item in plan.meals[0].items:
        assert 20.0 <= item.grams <= 400.0


def test_multiple_meals_each_respect_item_cap():
    plan = solve_day(
        BASIC_CANDIDATES,
        DayTargets(kcal=2000, protein_g=150, fat_g=60, carbs_g=200),
        ["breakfast", "lunch", "dinner"],
        max_items_per_meal=3,
    )
    assert plan.feasible is True
    assert {m.meal_type for m in plan.meals} == {"breakfast", "lunch", "dinner"}
    for meal in plan.meals:
        assert 1 <= len(meal.items) <= 3


def test_variety_penalty_avoids_recently_used_food_when_equivalent_alternative_exists():
    chicken_a = CandidateFood(
        "chicken_a", "Pollo A", kcal_100g=165, protein_100g=31, fat_100g=3.6, carbs_100g=0
    )
    chicken_b = CandidateFood(
        "chicken_b", "Pollo B", kcal_100g=165, protein_100g=31, fat_100g=3.6, carbs_100g=0
    )
    candidates = [chicken_a, chicken_b, RICE, OIL, BROCCOLI]

    plan = solve_day(
        candidates,
        LUNCH_TARGETS,
        ["lunch"],
        recently_used_food_ids=frozenset({"chicken_a"}),
    )
    used_ids = {item.food_id for item in plan.meals[0].items}
    # chicken_a y chicken_b son nutricionalmente idénticos — la única razón
    # para preferir uno sobre otro es la penalización de variedad.
    assert "chicken_a" not in used_ids
    assert "chicken_b" in used_ids


def test_single_candidate_still_produces_a_plan():
    plan = solve_day([CHICKEN], LUNCH_TARGETS, ["lunch"])
    assert plan.feasible is True
    assert {item.food_id for item in plan.meals[0].items} == {"chicken"}


# --- solve_day_with_fixed_items (iafood, sección 10.6) ----------------------
# A diferencia de solve_day, aquí la estructura por comida ya viene dada (la
# eligió la IA vía function calling) — el solver solo ajusta gramos.


def test_fixed_items_empty_is_infeasible():
    plan = solve_day_with_fixed_items({}, LUNCH_TARGETS)
    assert plan.feasible is False
    assert plan.meals == []


def test_fixed_items_meal_with_no_foods_is_infeasible():
    plan = solve_day_with_fixed_items({"lunch": []}, LUNCH_TARGETS)
    assert plan.feasible is False


def test_fixed_items_every_listed_food_appears_in_its_own_meal():
    plan = solve_day_with_fixed_items(
        {"breakfast": [CHICKEN], "lunch": [RICE, BROCCOLI]}, LUNCH_TARGETS
    )
    assert plan.feasible is True
    by_meal = {m.meal_type: {item.food_id for item in m.items} for m in plan.meals}
    assert by_meal == {"breakfast": {"chicken"}, "lunch": {"rice", "broccoli"}}


def test_fixed_items_respects_min_and_max_grams_per_item():
    plan = solve_day_with_fixed_items(
        {"lunch": [CHICKEN, RICE]},
        LUNCH_TARGETS,
        min_grams_per_item=20.0,
        max_grams_per_item=400.0,
    )
    for item in plan.meals[0].items:
        assert 20.0 <= item.grams <= 400.0


def test_fixed_items_totals_are_close_to_targets():
    plan = solve_day_with_fixed_items(
        {"breakfast": [CHICKEN], "lunch": [RICE, BROCCOLI]}, LUNCH_TARGETS
    )
    assert plan.feasible is True
    assert abs(plan.totals.kcal - LUNCH_TARGETS.kcal) <= 0.2 * LUNCH_TARGETS.kcal


def test_fixed_items_totals_recomputed_from_extracted_grams():
    plan = solve_day_with_fixed_items({"lunch": [CHICKEN, RICE]}, LUNCH_TARGETS)
    expected_kcal = sum(
        item.grams * {"chicken": CHICKEN, "rice": RICE}[item.food_id].kcal_100g / 100
        for item in plan.meals[0].items
    )
    assert plan.totals.kcal == round(expected_kcal, 1)


# --- plantillas de comida, reparto de kcal, redondeo y avisos (Fase 4) ------------------------

from myfood.domain import food_groups as fg  # noqa: E402
from myfood.domain.diet_engine import TARGETS_NOT_MET  # noqa: E402


def _food(id_, group, kcal, protein, fat, carbs, *, staple=True):
    bounds = fg.gram_bounds(group, kcal)
    return CandidateFood(
        id_, id_, kcal, protein, fat, carbs,
        group=group, min_grams=bounds.min_g, max_grams=bounds.max_g, staple=staple,
    )


CATALOG = [
    _food("pollo", fg.MEAT, 165, 31, 3.6, 0),
    _food("ternera", fg.MEAT, 156, 28, 4.5, 0),
    _food("merluza", fg.FISH, 71, 16, 0.8, 0),
    _food("huevo", fg.EGG, 155, 13, 11, 1.1),
    _food("lentejas", fg.LEGUME, 116, 9, 0.4, 20),
    _food("brocoli", fg.VEGETABLE, 35, 2.4, 0.4, 7),
    _food("tomate", fg.VEGETABLE, 22, 1, 0.2, 3.5),
    _food("arroz", fg.GRAIN, 130, 2.7, 0.3, 28),
    _food("pasta", fg.GRAIN, 131, 5, 1.1, 25),
    _food("pan", fg.BREAD, 250, 9, 3.3, 43),
    _food("avena", fg.CEREAL, 372, 13.5, 7, 60),
    _food("leche", fg.DAIRY, 46, 3.4, 1.6, 4.8),
    _food("yogur", fg.DAIRY, 61, 3.5, 3.3, 4.7),
    _food("queso", fg.CHEESE, 174, 18, 10, 3),
    _food("platano", fg.FRUIT, 90, 1.1, 0.3, 21),
    _food("nueces", fg.NUTS, 654, 15, 65, 7),
    _food("aceite", fg.OIL_FAT, 884, 0, 100, 0),
    _food("jamon", fg.PROCESSED_MEAT, 125, 20, 4, 1),
]
DAY = DayTargets(kcal=2200, protein_g=140, fat_g=70, carbs_g=240)
THREE = ["breakfast", "lunch", "dinner"]
GROUP_OF = {f.id: f.group for f in CATALOG}


def _solve(targets=DAY, meals=THREE, candidates=None, **kwargs):
    return solve_day(
        candidates or CATALOG,
        targets,
        meals,
        meal_kcal_shares=fg.MEAL_KCAL_SHARES[len(meals)],
        meal_templates=fg.MEAL_TEMPLATES,
        **kwargs,
    )


def _groups(plan, meal_type):
    meal = next(m for m in plan.meals if m.meal_type == meal_type)
    return [GROUP_OF[i.food_id] for i in meal.items]


def test_main_meals_have_a_main_protein_and_a_vegetable():
    plan = _solve()
    for meal_type in ("lunch", "dinner"):
        groups = _groups(plan, meal_type)
        assert set(groups) & {fg.MEAT, fg.FISH, fg.EGG, fg.LEGUME, fg.PROCESSED_MEAT}
        assert fg.VEGETABLE in groups


def test_a_meal_has_a_single_main_dish_and_a_single_carb_side():
    plan = _solve()
    for meal_type in ("lunch", "dinner"):
        groups = _groups(plan, meal_type)
        assert sum(g in (fg.MEAT, fg.FISH, fg.EGG) for g in groups) <= 1
        assert sum(g in (fg.GRAIN, fg.BREAD) for g in groups) <= 1


def test_breakfast_is_a_breakfast():
    plan = _solve()
    groups = set(_groups(plan, "breakfast"))
    assert groups <= {
        fg.BREAD, fg.CEREAL, fg.DAIRY, fg.EGG, fg.FRUIT, fg.NUTS, fg.CHEESE, fg.PROCESSED_MEAT
    }
    assert groups & {fg.BREAD, fg.CEREAL}
    assert groups & {fg.DAIRY, fg.EGG, fg.CHEESE}


def test_snacks_are_light_and_made_of_snack_foods():
    plan = _solve(
        DayTargets(2400, 140, 70, 260),
        ["breakfast", "morning_snack", "lunch", "afternoon_snack", "dinner"],
    )
    for meal_type in ("morning_snack", "afternoon_snack"):
        groups = _groups(plan, meal_type)
        assert 1 <= len(groups) <= 2
        assert set(groups) <= {fg.FRUIT, fg.DAIRY, fg.NUTS, fg.BREAD, fg.CHEESE, fg.CEREAL}


def test_energy_is_spread_across_meals_by_their_share():
    plan = _solve()
    by_id = {f.id: f for f in CATALOG}
    shares = fg.MEAL_KCAL_SHARES[3]
    for meal in plan.meals:
        kcal = sum(by_id[i.food_id].kcal_100g * i.grams / 100 for i in meal.items)
        expected = DAY.kcal * shares[meal.meal_type]
        assert abs(kcal - expected) <= expected * 0.3


def test_grams_are_multiples_of_five_within_each_foods_bounds():
    plan = _solve()
    by_id = {f.id: f for f in CATALOG}
    for meal in plan.meals:
        for item in meal.items:
            assert item.grams % 5 == 0
            assert by_id[item.food_id].min_grams <= item.grams <= by_id[item.food_id].max_grams


def test_a_day_that_hits_the_targets_has_no_warning_and_is_optimal():
    plan = _solve()
    assert plan.feasible
    assert plan.warning is None
    assert plan.is_optimal is True
    assert abs(plan.totals.kcal - DAY.kcal) <= DAY.kcal * 0.05
    assert plan.totals.protein_g >= DAY.protein_g * 0.9


def test_a_day_that_cannot_reach_the_kcal_target_is_flagged():
    plan = _solve(DayTargets(kcal=6500, protein_g=300, fat_g=200, carbs_g=700))
    assert plan.feasible
    assert plan.warning == TARGETS_NOT_MET
    assert plan.totals.kcal < 6500 * 0.95


def test_a_food_never_goes_outside_its_own_portion_bounds():
    tiny = _food("tiny", fg.MEAT, 165, 31, 3.6, 0)
    tiny.min_grams, tiny.max_grams = 100, 120
    plan = _solve(candidates=[tiny] + [f for f in CATALOG if f.id != "pollo"])
    for meal in plan.meals:
        for item in meal.items:
            if item.food_id == "tiny":
                assert 100 <= item.grams <= 120


def test_repeating_a_food_costs_more_each_time_it_was_already_used():
    pollo_a = _food("pollo_a", fg.MEAT, 165, 31, 3.6, 0)
    pollo_b = _food("pollo_b", fg.MEAT, 165, 31, 3.6, 0)
    candidates = [pollo_a, pollo_b] + [f for f in CATALOG if f.group != fg.MEAT]
    plan = _solve(
        candidates=candidates,
        recently_used_food_ids={"pollo_a": 4, "pollo_b": 1},
        variety_penalty_weight=0.01,
    )
    used = {i.food_id for m in plan.meals for i in m.items}
    assert "pollo_a" not in used


def test_a_staple_is_preferred_over_an_equivalent_exotic_food():
    ordinary = _food("pollo_normal", fg.MEAT, 165, 31, 3.6, 0)
    exotic = _food("pollo_raro", fg.MEAT, 165, 31, 3.6, 0, staple=False)
    no_protein = {fg.MEAT, fg.FISH, fg.EGG, fg.LEGUME, fg.PROCESSED_MEAT}
    candidates = [exotic, ordinary] + [f for f in CATALOG if f.group not in no_protein]
    plan = _solve(candidates=candidates)
    used = {i.food_id for m in plan.meals for i in m.items}
    assert "pollo_normal" in used
    assert "pollo_raro" not in used


def test_candidates_without_a_group_can_go_in_any_meal():
    plan = solve_day(
        BASIC_CANDIDATES,
        LUNCH_TARGETS,
        ["breakfast", "lunch"],
        meal_templates=fg.MEAL_TEMPLATES,
    )
    assert plan.feasible
    assert all(m.items for m in plan.meals)


def test_a_meal_with_no_candidate_for_its_template_is_left_empty_not_infeasible():
    only_meat = [_food("pollo", fg.MEAT, 165, 31, 3.6, 0)]
    plan = _solve(candidates=only_meat, meals=["breakfast", "lunch"])
    lunch = next(m for m in plan.meals if m.meal_type == "lunch")
    breakfast = next(m for m in plan.meals if m.meal_type == "breakfast")
    assert lunch.items and not breakfast.items


@pytest.mark.parametrize(
    "targets",
    [
        DayTargets(1400, 100, 50, 150),
        DayTargets(1800, 130, 60, 190),
        DayTargets(2500, 160, 80, 280),
        DayTargets(3200, 200, 100, 380),
    ],
)
def test_seven_days_stay_within_five_percent_kcal_and_ninety_percent_protein(targets):
    """Criterio de aceptación de la Fase 4 (sección «Criterios de aceptación»): un plan de
    7 días con desviación ≤ 5 % en kcal y ≥ 90 % de la proteína objetivo."""
    times_used: dict[str, int] = {}
    for day in range(7):
        plan = _solve(
            targets, recently_used_food_ids=dict(times_used), variety_penalty_weight=0.003
        )
        assert plan.feasible
        assert abs(plan.totals.kcal - targets.kcal) <= targets.kcal * 0.05, f"día {day}"
        assert plan.totals.protein_g >= targets.protein_g * 0.9, f"día {day}"
        assert plan.warning is None
        for meal in plan.meals:
            for item in meal.items:
                times_used[item.food_id] = times_used.get(item.food_id, 0) + 1
