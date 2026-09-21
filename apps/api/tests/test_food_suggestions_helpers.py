"""Piezas puras de las sugerencias de alimentos: reparto por grupo y rotación diaria."""

from myfood.domain.food_suggestions import SuggestedFood, pick_balanced, rotate


def _food(i: int) -> SuggestedFood:
    return SuggestedFood(
        id=f"id-{i}", name_es=f"Alimento {i}", brand=None, category=None, source="bedca",
        kcal_100g=100, protein_100g=10, fat_100g=1, carbs_100g=10,
        nutriscore_grade=None, nova_group=None, ecoscore_grade=None,
    )


def test_pick_balanced_caps_each_group_and_the_total():
    ordered = [("meat", _food(i)) for i in range(5)] + [("fish", _food(10 + i)) for i in range(5)]
    picked = pick_balanced(ordered, per_group=2, limit=10)
    assert [f.id for f in picked] == ["id-0", "id-1", "id-10", "id-11"]
    assert len(pick_balanced(ordered, per_group=5, limit=3)) == 3


def test_rotation_is_stable_for_a_day_and_changes_between_days():
    foods = [_food(i) for i in range(12)]
    today = [f.id for f in rotate(foods, "user:2026-09-21")]
    assert today == [f.id for f in rotate(foods, "user:2026-09-21")]
    assert today != [f.id for f in rotate(foods, "user:2026-09-22")]
    assert sorted(today) == sorted(f.id for f in foods)
