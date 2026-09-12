"""`domain/food_vector.py` — funciones puras, sin BD."""

from myfood.domain.food_vector import GRAMS_SCALE, KCAL_SCALE, normalize_food_vector


def test_normalize_typical_food():
    # Pechuga de pollo: 165 kcal, 31g proteína, 3.6g grasa, 0g carbos,
    # sin fibra ni sal reportadas.
    vec = normalize_food_vector(
        kcal_100g=165, protein_100g=31, fat_100g=3.6, carbs_100g=0,
        fiber_100g=None, salt_100g=None,
    )
    assert len(vec) == 6
    assert vec[0] == 165 / KCAL_SCALE
    assert vec[1] == 31 / GRAMS_SCALE
    assert vec[2] == 3.6 / GRAMS_SCALE
    assert vec[3] == 0
    # NULL se trata como 0, no como "desconocido".
    assert vec[4] == 0
    assert vec[5] == 0


def test_normalize_none_treated_as_zero_not_missing():
    with_none = normalize_food_vector(100, 10, 5, 20, None, None)
    with_zero = normalize_food_vector(100, 10, 5, 20, 0, 0)
    assert with_none == with_zero


def test_normalize_all_dimensions_in_unit_range():
    vec = normalize_food_vector(
        kcal_100g=884, protein_100g=0, fat_100g=100, carbs_100g=0,
        fiber_100g=0, salt_100g=0.05,
    )
    assert all(0.0 <= v <= 1.0 for v in vec)


def test_normalize_clamps_values_above_scale():
    # No debería pasar con datos reales, pero la función no debe devolver
    # nada fuera de [0, 1] ni reventar si algún dato llega fuera de rango.
    vec = normalize_food_vector(
        kcal_100g=2000, protein_100g=150, fat_100g=150, carbs_100g=150,
        fiber_100g=150, salt_100g=150,
    )
    assert vec == [1.0, 1.0, 1.0, 1.0, 1.0, 1.0]


def test_normalize_zero_food_is_zero_vector():
    vec = normalize_food_vector(0, 0, 0, 0, 0, 0)
    assert vec == [0.0, 0.0, 0.0, 0.0, 0.0, 0.0]


def test_similar_macros_are_closer_than_different_macros():
    """Dos alimentos con macros parecidos deben quedar más cerca (distancia
    euclídea sobre el vector normalizado) que uno muy distinto — es la
    propiedad que hace útil el vector para "alimentos similares"."""
    chicken = normalize_food_vector(165, 31, 3.6, 0, 0, 0.1)
    turkey = normalize_food_vector(160, 30, 3.0, 0, 0, 0.1)
    oil = normalize_food_vector(884, 0, 100, 0, 0, 0)

    def l2(a, b):
        return sum((x - y) ** 2 for x, y in zip(a, b, strict=True)) ** 0.5

    assert l2(chicken, turkey) < l2(chicken, oil)
