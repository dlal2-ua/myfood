"""Objetivo de agua efectivo y lo bebido hoy: lo comparten el control de agua
(`routers/water.py`) y los recordatorios (`notification_content.py`)."""

from __future__ import annotations

from datetime import date
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from myfood.db.models import BodyMeasurement, Profile, WaterLog, WaterSettings
from myfood.domain import formulas

DEFAULT_TARGET_ML = 2500


async def latest_weight_kg(session: AsyncSession, user_id: UUID) -> float | None:
    measurement = await session.scalar(
        select(BodyMeasurement)
        .where(BodyMeasurement.user_id == user_id, BodyMeasurement.weight_kg.is_not(None))
        .order_by(BodyMeasurement.measured_on.desc())
        .limit(1)
    )
    return float(measurement.weight_kg) if measurement else None


async def effective_target_ml(
    session: AsyncSession, user_id: UUID, settings: WaterSettings | None
) -> int:
    """En modo 'auto' recalcula con la fórmula EFSA si hay sexo+peso disponibles; si faltan datos,
    se queda con el último valor guardado (arranca en 2500 ml) en vez de fallar — a diferencia de
    `/calc/targets`, el control de agua debe ser usable antes de completar el perfil."""
    if settings is None:
        return DEFAULT_TARGET_ML
    if settings.mode == "manual":
        return settings.daily_target_ml
    profile = await session.get(Profile, user_id)
    weight_kg = await latest_weight_kg(session, user_id)
    if profile is not None and profile.sex is not None and weight_kg is not None:
        return formulas.water_target_ml(profile.sex, weight_kg)
    return settings.daily_target_ml


async def drunk_ml(session: AsyncSession, user_id: UUID, day: date) -> int:
    total = await session.scalar(
        select(func.coalesce(func.sum(WaterLog.ml), 0)).where(
            WaterLog.user_id == user_id, WaterLog.log_date == day
        )
    )
    return int(total or 0)
