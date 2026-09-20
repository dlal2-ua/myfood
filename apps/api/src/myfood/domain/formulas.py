"""Fórmulas normativas de MyFood (documento 2, sección 8).

Funciones puras, sin acceso a BD. La IA nunca calcula estos números (R1);
todo pasa siempre por aquí.
"""

from math import log10
from statistics import mean

ACTIVITY_FACTORS = {
    "sedentary": 1.2,
    "light": 1.375,
    "moderate": 1.55,
    "active": 1.725,
    "very_active": 1.9,
}


def bmr_mifflin(sex: str, weight_kg: float, height_cm: float, age_years: float) -> float:
    base = 10 * weight_kg + 6.25 * height_cm - 5 * age_years
    return base + 5 if sex == "male" else base - 161


def bmr_katch(lean_mass_kg: float) -> float:
    return 370 + 21.6 * lean_mass_kg


def bmr_cunningham(lean_mass_kg: float) -> float:
    return 500 + 22 * lean_mass_kg


def tdee(bmr: float, activity_level: str) -> float:
    return bmr * ACTIVITY_FACTORS[activity_level]


def body_fat_navy(
    sex: str, height_cm: float, neck_cm: float, waist_cm: float, hip_cm: float | None = None
) -> tuple[float, list[str]]:
    """Método US Navy (Hodgdon-Beckett). Devuelve (%grasa, warnings)."""
    if sex == "male":
        pct = (
            495 / (1.0324 - 0.19077 * log10(waist_cm - neck_cm) + 0.15456 * log10(height_cm))
        ) - 450
    else:
        pct = (
            495
            / (
                1.29579
                - 0.35004 * log10(waist_cm + (hip_cm or 0) - neck_cm)
                + 0.22100 * log10(height_cm)
            )
        ) - 450
    warnings = [] if 3 <= pct <= 60 else ["BODY_FAT_OUT_OF_RANGE"]
    return pct, warnings


def lean_mass_kg(weight_kg: float, body_fat_pct: float) -> float:
    return weight_kg * (1 - body_fat_pct / 100)


def ffmi(lean_mass_kg_: float, height_cm: float) -> float:
    height_m = height_cm / 100
    return lean_mass_kg_ / (height_m**2)


def whtr(waist_cm: float, height_cm: float) -> tuple[float, list[str]]:
    ratio = waist_cm / height_cm
    warnings = ["WAIST_TO_HEIGHT_RISK"] if ratio > 0.5 else []
    return ratio, warnings


def bmi(weight_kg: float, height_cm: float) -> float:
    height_m = height_cm / 100
    return weight_kg / (height_m**2)


def calorie_target(
    tdee_kcal: float, goal: str, rate_kg_week: float, bmr: float, sex: str
) -> tuple[float, list[str]]:
    """Objetivo calórico con suelo de seguridad (R6)."""
    delta = (rate_kg_week * 7700) / 7  # 7700 kcal ~= 1 kg
    if goal == "lose":
        target = tdee_kcal - delta
    elif goal == "gain":
        target = tdee_kcal + delta
    else:
        target = tdee_kcal

    floor_ = max(bmr, 1200 if sex == "female" else 1500)
    if target < floor_:
        return floor_, ["TARGET_RAISED_TO_SAFETY_FLOOR"]
    return target, []


def macro_targets(
    weight_kg: float,
    target_kcal: float,
    goal: str,
    protein_per_kg: float | None = None,
    fat_pct: float = 0.25,
) -> tuple[float, float, float, list[str]]:
    protein_g = weight_kg * (protein_per_kg or (2.0 if goal == "lose" else 1.8))
    fat_g = (target_kcal * fat_pct) / 9
    fat_g = max(fat_g, weight_kg * 0.5)  # mínimo hormonal
    carbs_g = (target_kcal - protein_g * 4 - fat_g * 9) / 4
    warnings = ["LOW_CARB_WARNING"] if carbs_g < 50 else []
    return protein_g, fat_g, max(carbs_g, 0), warnings


def water_target_ml(sex: str, weight_kg: float, exercise_minutes_today: float = 0) -> int:
    base = 2500 if sex == "male" else 2000  # referencia EFSA, ingesta total
    by_weight = weight_kg * 33
    target = max(base, by_weight)
    return round(target + (exercise_minutes_today / 60) * 600)


def _logging_days(intake_series: list[float | None]) -> int:
    return sum(1 for kcal in intake_series if kcal is not None)


def adaptive_tdee(
    weight_trend_series: list[float], intake_series: list[float | None]
) -> tuple[float | None, bool]:
    """TDEE adaptativo semanal. Requiere >=14 días y >=10 días con registro real."""
    if len(intake_series) < 14 or _logging_days(intake_series) < 10:
        return None, False

    delta_kg = weight_trend_series[-1] - weight_trend_series[0]
    days = len(weight_trend_series)
    kcal_delta = (delta_kg * 7700) / days

    logged = [kcal for kcal in intake_series if kcal is not None]
    return mean(logged) - kcal_delta, True


def ema_weight_trend(daily_weights: list[float], alpha: float = 0.25) -> list[float]:
    """Media móvil exponencial del peso, para amortiguar el ruido de hidratación."""
    if not daily_weights:
        return []
    trend = [daily_weights[0]]
    for weight in daily_weights[1:]:
        trend.append(alpha * weight + (1 - alpha) * trend[-1])
    return trend


# --- Más fórmulas de metabolismo basal (`bmr_formula`) y de grasa corporal (`bf_method`) ---


def bmr_harris_benedict(sex: str, weight_kg: float, height_cm: float, age_years: float) -> float:
    """Harris-Benedict revisada (Roza y Shizgal, 1984)."""
    if sex == "male":
        return 88.362 + 13.397 * weight_kg + 4.799 * height_cm - 5.677 * age_years
    return 447.593 + 9.247 * weight_kg + 3.098 * height_cm - 4.330 * age_years


def bmr_for(
    formula: str,
    *,
    sex: str,
    weight_kg: float,
    height_cm: float,
    age_years: float,
    lean_mass: float | None = None,
) -> float:
    """BMR con la fórmula elegida. Katch y Cunningham necesitan la masa magra."""
    if formula == "mifflin":
        return bmr_mifflin(sex, weight_kg, height_cm, age_years)
    if formula == "harris":
        return bmr_harris_benedict(sex, weight_kg, height_cm, age_years)
    if lean_mass is None:
        raise ValueError(f"La fórmula {formula} necesita la masa magra")
    return bmr_katch(lean_mass) if formula == "katch" else bmr_cunningham(lean_mass)


def _siri(body_density: float) -> float:
    """% de grasa a partir de la densidad corporal (ecuación de Siri)."""
    return 495 / body_density - 450


def _body_fat_result(pct: float) -> tuple[float, list[str]]:
    return pct, ([] if 3 <= pct <= 60 else ["BODY_FAT_OUT_OF_RANGE"])


JACKSON3_SITES = {
    "male": ("chest", "abdomen", "thigh"),
    "female": ("triceps", "suprailiac", "thigh"),
}
JACKSON7_SITES = (
    "chest",
    "midaxillary",
    "triceps",
    "subscapular",
    "abdomen",
    "suprailiac",
    "thigh",
)
DURNIN_SITES = ("biceps", "triceps", "subscapular", "suprailiac")


def body_fat_jackson3(
    sex: str, age_years: float, skinfolds_mm: dict[str, float]
) -> tuple[float, list[str]]:
    """Jackson-Pollock de 3 pliegues: pecho, abdomen y muslo (hombres); tríceps, suprailíaco y
    muslo (mujeres)."""
    total = sum(skinfolds_mm[site] for site in JACKSON3_SITES[sex])
    if sex == "male":
        density = 1.10938 - 0.0008267 * total + 0.0000016 * total**2 - 0.0002574 * age_years
    else:
        density = 1.0994921 - 0.0009929 * total + 0.0000023 * total**2 - 0.0001392 * age_years
    return _body_fat_result(_siri(density))


def body_fat_jackson7(
    sex: str, age_years: float, skinfolds_mm: dict[str, float]
) -> tuple[float, list[str]]:
    """Jackson-Pollock de 7 pliegues: pecho, axilar medio, tríceps, subescapular, abdomen,
    suprailíaco y muslo."""
    total = sum(skinfolds_mm[site] for site in JACKSON7_SITES)
    if sex == "male":
        density = 1.112 - 0.00043499 * total + 0.00000055 * total**2 - 0.00028826 * age_years
    else:
        density = 1.097 - 0.00046971 * total + 0.00000056 * total**2 - 0.00012828 * age_years
    return _body_fat_result(_siri(density))


# Coeficientes (c, m) de Durnin y Womersley (1974): densidad = c - m * log10(suma de 4 pliegues).
_DURNIN = {
    "male": [
        (19, 1.1620, 0.0630),
        (29, 1.1631, 0.0632),
        (39, 1.1422, 0.0544),
        (49, 1.1620, 0.0700),
        (200, 1.1715, 0.0779),
    ],
    "female": [
        (19, 1.1549, 0.0678),
        (29, 1.1599, 0.0717),
        (39, 1.1423, 0.0632),
        (49, 1.1333, 0.0612),
        (200, 1.1339, 0.0645),
    ],
}


def body_fat_durnin(
    sex: str, age_years: float, skinfolds_mm: dict[str, float]
) -> tuple[float, list[str]]:
    """Durnin-Womersley: bíceps, tríceps, subescapular y suprailíaco. Válida a partir de 17 años."""
    total = sum(skinfolds_mm[site] for site in DURNIN_SITES)
    _upper, c, m = next(row for row in _DURNIN[sex] if age_years <= row[0])
    pct, warnings = _body_fat_result(_siri(c - m * log10(total)))
    if age_years < 17:
        warnings = [*warnings, "DURNIN_NOT_VALIDATED_UNDER_17"]
    return pct, warnings


def body_fat_deurenberg(sex: str, age_years: float, bmi_value: float) -> tuple[float, list[str]]:
    """Deurenberg: estimación a partir del IMC, la edad y el sexo (sin pliegues ni cinta). Es la
    menos precisa: infravalora la grasa en personas musculadas y la sobrevalora en mayores."""
    pct = 1.20 * bmi_value + 0.23 * age_years - 10.8 * (1 if sex == "male" else 0) - 5.4
    pct, warnings = _body_fat_result(pct)
    return pct, [*warnings, "BMI_BASED_ESTIMATE"]
