"""TDEE adaptativo (documento 2, secciones 6.7 y 8; Fase 7).

Sustituye la fórmula estática de Mifflin-St Jeor por una estimación basada
en la tendencia real de peso frente a la ingesta realmente registrada, en
cuanto hay suficiente historial (`formulas.adaptive_tdee`). Sin worker ni
cron dedicado: se recalcula on-demand la primera vez que se pide dentro de
una semana (lunes-domingo) y queda cacheado en `tdee_estimates` para el
resto de peticiones de esa semana — mismo principio de "no añadir
infraestructura que los datos ya disponibles no necesitan" que el resto del
backend.
"""

from datetime import date, timedelta
from statistics import mean
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from myfood.db.models import BodyMeasurement, FoodLog, TdeeEstimate
from myfood.domain import formulas

WINDOW_DAYS = 14


async def _daily_weight_series(
    session: AsyncSession, user_id: UUID, start: date, end: date
) -> list[float] | None:
    rows = await session.scalars(
        select(BodyMeasurement)
        .where(
            BodyMeasurement.user_id == user_id,
            BodyMeasurement.measured_on >= start,
            BodyMeasurement.measured_on <= end,
        )
        .order_by(BodyMeasurement.measured_on)
    )
    by_day: dict[date, float] = {}
    for measurement in rows:
        if measurement.weight_kg is not None:
            by_day[measurement.measured_on] = float(measurement.weight_kg)
    if not by_day:
        return None

    earliest = min(by_day)
    series: list[float] = []
    last_known = by_day[earliest]
    for offset in range((end - start).days + 1):
        day = start + timedelta(days=offset)
        if day in by_day:
            last_known = by_day[day]
        series.append(last_known)
    return series


async def _daily_intake_series(
    session: AsyncSession, user_id: UUID, start: date, end: date
) -> list[float | None]:
    rows = await session.execute(
        select(FoodLog.log_date, FoodLog.kcal).where(
            FoodLog.user_id == user_id,
            FoodLog.log_date >= start,
            FoodLog.log_date <= end,
        )
    )
    totals: dict[date, float] = {}
    for log_date, kcal in rows:
        totals[log_date] = totals.get(log_date, 0.0) + float(kcal)

    return [totals.get(start + timedelta(days=offset)) for offset in range((end - start).days + 1)]


def _raw_estimate(
    weight_trend: list[float], intake_series: list[float | None]
) -> tuple[float, float, float]:
    """Mismo cálculo que `formulas.adaptive_tdee`, sin la comprobación de
    fiabilidad: `tdee_estimates.estimated_tdee` es NOT NULL, así que siempre
    hace falta un número — la fiabilidad se guarda aparte en `is_reliable`,
    calculada por `formulas.adaptive_tdee` (fuente única de la regla de
    negocio de los 14/10 días)."""
    delta_kg = weight_trend[-1] - weight_trend[0]
    days = len(weight_trend)
    kcal_delta = (delta_kg * 7700) / days
    logged = [kcal for kcal in intake_series if kcal is not None]
    avg_intake = mean(logged) if logged else 0.0
    return avg_intake - kcal_delta, avg_intake, delta_kg


def _week_start(day: date) -> date:
    return day - timedelta(days=day.weekday())


async def compute_and_store(
    session: AsyncSession, user_id: UUID, as_of: date | None = None
) -> TdeeEstimate | None:
    """Calcula la estimación de la semana de `as_of` y la guarda (upsert).
    Devuelve `None` si el usuario no tiene ningún peso registrado todavía."""
    as_of = as_of or date.today()
    start = as_of - timedelta(days=WINDOW_DAYS - 1)

    weight_series = await _daily_weight_series(session, user_id, start, as_of)
    if weight_series is None:
        return None

    intake_series = await _daily_intake_series(session, user_id, start, as_of)
    weight_trend = formulas.ema_weight_trend(weight_series)
    estimated_tdee, avg_intake, delta_kg = _raw_estimate(weight_trend, intake_series)
    _, is_reliable = formulas.adaptive_tdee(weight_trend, intake_series)
    logging_days = sum(1 for kcal in intake_series if kcal is not None)

    week_start = _week_start(as_of)
    estimate = await session.scalar(
        select(TdeeEstimate).where(
            TdeeEstimate.user_id == user_id, TdeeEstimate.week_start == week_start
        )
    )
    if estimate is None:
        estimate = TdeeEstimate(user_id=user_id, week_start=week_start)
        session.add(estimate)

    estimate.weight_trend_kg = round(weight_trend[-1], 3)
    estimate.weight_change_kg = round(delta_kg, 3)
    estimate.avg_intake_kcal = round(avg_intake, 2)
    estimate.estimated_tdee = round(estimated_tdee, 2)
    estimate.logging_days = logging_days
    estimate.is_reliable = is_reliable
    await session.commit()
    return estimate


async def get_current_estimate(
    session: AsyncSession, user_id: UUID, as_of: date | None = None
) -> TdeeEstimate | None:
    """Estimación vigente para `/calc/targets`. Reutiliza la fila de la
    semana en curso si ya existe (evita recalcular en cada petición) y la
    recalcula si no, o si está desactualizada respecto a `as_of`."""
    as_of = as_of or date.today()
    week_start = _week_start(as_of)
    existing = await session.scalar(
        select(TdeeEstimate).where(
            TdeeEstimate.user_id == user_id, TdeeEstimate.week_start == week_start
        )
    )
    if existing is not None:
        return existing
    return await compute_and_store(session, user_id, as_of)
