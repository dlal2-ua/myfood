"""Tests del motor de dietas (documento 2, "Motor de generación de dietas
(determinista)") — puros, sin BD. Cada valor esperado se calcula a mano
antes de escribir el assert, igual que `test_formulas.py`."""

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
