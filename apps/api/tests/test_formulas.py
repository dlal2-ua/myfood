"""Cobertura 100% de myfood.domain.formulas (documento 2, sección 16).

Cada caso conocido está verificado a mano contra la fórmula del documento 2,
sección 8, antes de escribir el assert.
"""

import pytest

from myfood.domain import formulas as f


def test_bmr_mifflin_male():
    assert f.bmr_mifflin("male", 80, 180, 30) == pytest.approx(1780.0)


def test_bmr_mifflin_female():
    assert f.bmr_mifflin("female", 65, 165, 25) == pytest.approx(1395.25)


def test_bmr_katch():
    assert f.bmr_katch(60) == pytest.approx(1666.0)


def test_bmr_cunningham():
    assert f.bmr_cunningham(60) == pytest.approx(1820.0)


def test_tdee_moderate():
    assert f.tdee(1780, "moderate") == pytest.approx(2759.0)


@pytest.mark.parametrize("level", list(f.ACTIVITY_FACTORS))
def test_tdee_all_activity_levels(level):
    assert f.tdee(1000, level) == pytest.approx(1000 * f.ACTIVITY_FACTORS[level])


def test_body_fat_navy_male_within_range():
    pct, warnings = f.body_fat_navy("male", 180, 38, 85)
    assert pct == pytest.approx(16.1066, abs=1e-3)
    assert warnings == []


def test_body_fat_navy_female_within_range():
    pct, warnings = f.body_fat_navy("female", 165, 32, 70, hip_cm=95)
    assert pct == pytest.approx(24.8562, abs=1e-3)
    assert warnings == []


def test_body_fat_navy_out_of_physiological_range_warns():
    # waist - neck casi nulo: matemáticamente válido, fisiológicamente imposible.
    pct, warnings = f.body_fat_navy("male", 180, 40, 42)
    assert pct < 3
    assert warnings == ["BODY_FAT_OUT_OF_RANGE"]


def test_lean_mass_kg():
    assert f.lean_mass_kg(80, 16.088) == pytest.approx(67.1296, abs=1e-3)


def test_ffmi():
    assert f.ffmi(66, 180) == pytest.approx(20.3704, abs=1e-3)


def test_whtr_risky_above_half():
    ratio, warnings = f.whtr(95, 170)
    assert ratio == pytest.approx(0.5588, abs=1e-3)
    assert warnings == ["WAIST_TO_HEIGHT_RISK"]


def test_whtr_ok_below_half():
    ratio, warnings = f.whtr(75, 170)
    assert ratio == pytest.approx(0.4412, abs=1e-3)
    assert warnings == []


def test_whtr_boundary_exactly_half_does_not_warn():
    ratio, warnings = f.whtr(85, 170)
    assert ratio == pytest.approx(0.5)
    assert warnings == []


def test_bmi():
    assert f.bmi(80, 180) == pytest.approx(24.6914, abs=1e-3)


def test_calorie_target_lose_within_floor():
    target, warnings = f.calorie_target(2759, "lose", 0.5, 1780, "male")
    assert target == pytest.approx(2209.0)
    assert warnings == []


def test_calorie_target_gain():
    target, warnings = f.calorie_target(2500, "gain", 0.25, 1600, "male")
    assert target == pytest.approx(2500 + (0.25 * 7700) / 7)
    assert warnings == []


def test_calorie_target_maintain():
    target, warnings = f.calorie_target(2500, "maintain", 0.5, 1600, "male")
    assert target == pytest.approx(2500)
    assert warnings == []


def test_calorie_target_triggers_safety_floor_r6():
    """R6: nunca por debajo de la TMB ni de 1500 kcal (hombres) / 1200 (mujeres)."""
    target, warnings = f.calorie_target(1600, "lose", 1.5, 1500, "male")
    assert target == pytest.approx(1500)
    assert warnings == ["TARGET_RAISED_TO_SAFETY_FLOOR"]


def test_calorie_target_floor_uses_female_minimum():
    # BMR baja + déficit agresivo: el suelo debe ser max(bmr, 1200), no bmr solo.
    target, warnings = f.calorie_target(1400, "lose", 2.0, 1100, "female")
    assert target == pytest.approx(1200)
    assert warnings == ["TARGET_RAISED_TO_SAFETY_FLOOR"]


def test_macro_targets_lose_no_warning():
    protein, fat, carbs, warnings = f.macro_targets(80, 2200, "lose")
    assert protein == pytest.approx(160.0)
    assert fat == pytest.approx(61.111, abs=1e-3)
    assert carbs == pytest.approx(252.5, abs=1e-3)
    assert warnings == []


def test_macro_targets_low_carb_warning():
    protein, fat, carbs, warnings = f.macro_targets(90, 1200, "lose")
    assert protein == pytest.approx(180.0)
    assert fat == pytest.approx(45.0)
    assert carbs == pytest.approx(18.75)
    assert warnings == ["LOW_CARB_WARNING"]


def test_macro_targets_carbs_never_negative():
    # Objetivo calórico extremadamente bajo: los carbohidratos no deben quedar negativos.
    _, _, carbs, _ = f.macro_targets(100, 400, "lose")
    assert carbs == 0


def test_macro_targets_custom_protein_per_kg():
    protein, _, _, _ = f.macro_targets(70, 2000, "maintain", protein_per_kg=1.6)
    assert protein == pytest.approx(112.0)


def test_water_target_ml_male_base_floor():
    assert f.water_target_ml("male", 60) == 2500  # 60*33=1980 < base 2500


def test_water_target_ml_female_by_weight():
    assert f.water_target_ml("female", 50) == 2000  # 50*33=1650 < base 2000


def test_water_target_ml_scales_with_weight():
    assert f.water_target_ml("male", 100) == 3300  # 100*33=3300 > base 2500


def test_water_target_ml_adds_exercise_bonus():
    assert f.water_target_ml("male", 80, exercise_minutes_today=60) == 3240


def test_adaptive_tdee_insufficient_days_returns_not_reliable():
    value, is_reliable = f.adaptive_tdee([80.0] * 10, [2000.0] * 10)
    assert value is None
    assert is_reliable is False


def test_adaptive_tdee_enough_days_but_not_enough_logged_meals():
    intake = (
        [2000.0, None, None, None, None]
        + [2000.0, 2000.0, 2000.0, 2000.0, 2000.0]
        + [None, None, None, None]
    )
    value, is_reliable = f.adaptive_tdee([80.0] * 14, intake)
    assert value is None
    assert is_reliable is False


def test_adaptive_tdee_reliable_with_enough_data():
    weight_trend = [80.0 - i * 0.1 for i in range(14)]
    intake = [2000, 2100, None, 1950, 2050, 2000, None, 2100, 1980, 2020, None, 2000, 1990, 2010]
    value, is_reliable = f.adaptive_tdee(weight_trend, intake)
    assert is_reliable is True
    assert value == pytest.approx(2733.1818, abs=1e-3)


def test_adaptive_tdee_boundary_exactly_14_days_and_10_logged():
    intake = [2000.0] * 10 + [None] * 4
    value, is_reliable = f.adaptive_tdee([80.0] * 14, intake)
    assert is_reliable is True
    assert value == pytest.approx(2000.0)


def test_ema_weight_trend_empty():
    assert f.ema_weight_trend([]) == []


def test_ema_weight_trend_smooths_noise():
    trend = f.ema_weight_trend([80, 79.8, 79.5, 79.9, 79.6])
    assert trend == pytest.approx([80, 79.95, 79.8375, 79.853125, 79.78984375])
    # La EMA amortigua el pico de 79.9: la tendencia sube menos que el dato bruto.
    assert trend[3] < 79.9


# --- Harris-Benedict y métodos de grasa corporal por pliegues -----------------------------------
# Los valores esperados están calculados aparte con los coeficientes de cada publicación.

import pytest  # noqa: E402

from myfood.domain import formulas  # noqa: E402


def test_harris_benedict_revised_male_and_female():
    assert formulas.bmr_harris_benedict("male", 80, 180, 30) == pytest.approx(1853.632, abs=0.01)
    assert formulas.bmr_harris_benedict("female", 60, 165, 30) == pytest.approx(1383.683, abs=0.01)


def test_bmr_for_dispatches_by_formula():
    kwargs = dict(sex="male", weight_kg=80, height_cm=180, age_years=30)
    assert formulas.bmr_for("mifflin", **kwargs) == formulas.bmr_mifflin("male", 80, 180, 30)
    assert formulas.bmr_for("harris", **kwargs) == formulas.bmr_harris_benedict("male", 80, 180, 30)
    assert formulas.bmr_for("katch", lean_mass=65, **kwargs) == formulas.bmr_katch(65)
    assert formulas.bmr_for("cunningham", lean_mass=65, **kwargs) == formulas.bmr_cunningham(65)


def test_katch_and_cunningham_need_the_lean_mass():
    with pytest.raises(ValueError):
        formulas.bmr_for("katch", sex="male", weight_kg=80, height_cm=180, age_years=30)


def test_jackson_pollock_3_sites_male_and_female():
    male = {"chest": 10, "abdomen": 20, "thigh": 15, "triceps": 99}
    female = {"triceps": 15, "suprailiac": 12, "thigh": 20, "chest": 99}
    assert formulas.body_fat_jackson3("male", 30, male)[0] == pytest.approx(13.61, abs=0.05)
    assert formulas.body_fat_jackson3("female", 28, female)[0] == pytest.approx(19.64, abs=0.05)


def test_jackson_pollock_7_sites_male_and_female():
    male = dict(
        chest=10, midaxillary=12, triceps=10, subscapular=14, abdomen=20, suprailiac=15, thigh=15
    )
    female = dict(
        chest=12, midaxillary=10, triceps=15, subscapular=14, abdomen=18, suprailiac=16, thigh=20
    )
    assert formulas.body_fat_jackson7("male", 35, male)[0] == pytest.approx(14.69, abs=0.05)
    assert formulas.body_fat_jackson7("female", 40, female)[0] == pytest.approx(22.0, abs=0.05)


@pytest.mark.parametrize(
    ("sex", "age", "folds", "expected"),
    [
        ("male", 25, dict(biceps=6, triceps=10, subscapular=12, suprailiac=14), 16.76),
        ("male", 55, dict(biceps=6, triceps=10, subscapular=12, suprailiac=14), 23.66),
        ("female", 45, dict(biceps=8, triceps=15, subscapular=14, suprailiac=16), 31.62),
    ],
)
def test_durnin_womersley_uses_the_coefficients_of_the_age_group(sex, age, folds, expected):
    pct, warnings = formulas.body_fat_durnin(sex, age, folds)
    assert pct == pytest.approx(expected, abs=0.05)
    assert warnings == []


def test_durnin_warns_under_seventeen():
    folds = dict(biceps=6, triceps=10, subscapular=12, suprailiac=14)
    assert "DURNIN_NOT_VALIDATED_UNDER_17" in formulas.body_fat_durnin("male", 15, folds)[1]


def test_deurenberg_from_bmi_and_always_says_it_is_an_estimate():
    male, warnings = formulas.body_fat_deurenberg("male", 30, 24.0)
    female, _ = formulas.body_fat_deurenberg("female", 30, 24.0)
    assert male == pytest.approx(19.5)
    assert female == pytest.approx(30.3)
    assert "BMI_BASED_ESTIMATE" in warnings


def test_an_impossible_body_fat_is_flagged():
    _, warnings = formulas.body_fat_deurenberg("male", 20, 10.0)
    assert "BODY_FAT_OUT_OF_RANGE" in warnings
