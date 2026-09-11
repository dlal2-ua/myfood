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
