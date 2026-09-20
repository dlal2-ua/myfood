"""Cálculos de suplementos sin BD: cuánto dura el stock y cuánto cuesta al mes."""

from __future__ import annotations

from collections.abc import Sequence

LOW_STOCK_DAYS_THRESHOLD = 5


def doses_per_day(days_of_week_per_schedule: Sequence[Sequence[int]]) -> float:
    """Estimación simple: cada horario aporta una toma en los días que cubre — se promedia esa
    frecuencia semanal a un valor diario. No distingue tamaños de dosis distintos entre sí (todas
    las tomas cuentan como 1 dosis, igual que el registro)."""
    if not days_of_week_per_schedule:
        return 0.0
    return sum(len(days) for days in days_of_week_per_schedule) / 7


def stock_projection(
    doses_remaining: float | None, days_of_week_per_schedule: Sequence[Sequence[int]]
) -> tuple[float | None, bool]:
    """(días que dura el stock, ¿queda poco?). `None` si no hay stock o no hay horarios."""
    if doses_remaining is None:
        return None, False
    per_day = doses_per_day(days_of_week_per_schedule)
    if per_day <= 0:
        return None, False
    days_remaining = round(doses_remaining / per_day, 1)
    return days_remaining, days_remaining <= LOW_STOCK_DAYS_THRESHOLD


def monthly_cost(
    price_per_container: float | None,
    doses_per_container: int | None,
    days_of_week_per_schedule: Sequence[Sequence[int]],
) -> float | None:
    """Coste estimado de 30 días de este suplemento (precio del envase ÷ dosis del envase × dosis
    al día × 30). `None` si falta el precio, las dosis del envase o algún horario: no se inventa."""
    if price_per_container is None or not doses_per_container:
        return None
    per_day = doses_per_day(days_of_week_per_schedule)
    if per_day <= 0:
        return None
    return round(price_per_container / doses_per_container * per_day * 30, 2)
