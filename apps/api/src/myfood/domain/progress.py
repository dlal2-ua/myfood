"""Cálculos puros del resumen de progreso (sin BD): media móvil del peso y tendencia."""

from __future__ import annotations

from datetime import date, timedelta

MOVING_AVERAGE_DAYS = 7


def moving_average(points: list[tuple[date, float]], window_days: int = MOVING_AVERAGE_DAYS):
    """Media móvil sobre ventana de calendario: para cada medida, la media de las medidas de los
    `window_days` días que terminan ese día. Con pocas pesadas (no todos los días) sigue siendo
    válida, y una sola pesada devuelve ella misma."""
    ordered = sorted(points)
    result: list[tuple[date, float, float]] = []
    for index, (day, weight) in enumerate(ordered):
        start = day - timedelta(days=window_days - 1)
        window = [w for d, w in ordered[: index + 1] if d >= start]
        result.append((day, weight, sum(window) / len(window)))
    return result


def trend_kg_per_week(smoothed: list[tuple[date, float]], min_span_days: int = 7) -> float | None:
    """Pendiente (regresión lineal por mínimos cuadrados) de la serie suavizada, en kg/semana.
    `None` si no hay al menos dos puntos separados `min_span_days` días: con menos, la pendiente
    sería ruido."""
    if len(smoothed) < 2:
        return None
    ordered = sorted(smoothed)
    first = ordered[0][0]
    if (ordered[-1][0] - first).days < min_span_days:
        return None
    xs = [(d - first).days for d, _ in ordered]
    ys = [w for _, w in ordered]
    mean_x = sum(xs) / len(xs)
    mean_y = sum(ys) / len(ys)
    denominator = sum((x - mean_x) ** 2 for x in xs)
    if denominator == 0:
        return None
    slope_per_day = (
        sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys, strict=True)) / denominator
    )
    return slope_per_day * 7
