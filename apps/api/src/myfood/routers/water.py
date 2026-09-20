"""Control de agua (sección 6.6, Fase 3). Objetivo diario en modo 'auto'
(fórmula EFSA de `domain/formulas.py`, sección 12.6) o 'manual' (el usuario
fija su propia cifra), registro rápido por contenedores predefinidos.
"""

from datetime import date
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from myfood.db.models import BodyMeasurement, Profile, WaterLog, WaterSettings
from myfood.deps import get_current_user_id, get_db
from myfood.domain import formulas
from myfood.errors import AppError

router = APIRouter(prefix="/water", tags=["water"])


class WaterContainer(BaseModel):
    label: str = Field(min_length=1, max_length=50)
    ml: int = Field(gt=0, le=5000)


class WaterSettingsOut(BaseModel):
    mode: Literal["auto", "manual"]
    daily_target_ml: int
    containers: list[WaterContainer]


class WaterSettingsUpdate(BaseModel):
    mode: Literal["auto", "manual"] | None = None
    daily_target_ml: int | None = Field(default=None, gt=0, le=10000)
    containers: list[WaterContainer] | None = None


async def _get_or_create_settings(session: AsyncSession, user_id: UUID) -> WaterSettings:
    settings = await session.get(WaterSettings, user_id)
    if settings is None:
        settings = WaterSettings(user_id=user_id)
        session.add(settings)
        await session.flush()
    return settings


async def _latest_weight_kg(session: AsyncSession, user_id: UUID) -> float | None:
    stmt = (
        select(BodyMeasurement)
        .where(BodyMeasurement.user_id == user_id, BodyMeasurement.weight_kg.is_not(None))
        .order_by(BodyMeasurement.measured_on.desc())
        .limit(1)
    )
    measurement = await session.scalar(stmt)
    return float(measurement.weight_kg) if measurement else None


async def _effective_target_ml(
    session: AsyncSession, user_id: UUID, settings: WaterSettings
) -> int:
    """En modo 'auto' recalcula con la fórmula EFSA si hay sexo+peso
    disponibles; si faltan datos, se queda con el último valor guardado
    (arranca en el default de la migración, 2500 ml) en vez de fallar —
    a diferencia de `/calc/targets`, el control de agua debe ser usable
    antes de completar el perfil."""
    if settings.mode == "manual":
        return settings.daily_target_ml
    profile = await session.get(Profile, user_id)
    weight_kg = await _latest_weight_kg(session, user_id)
    if profile is not None and profile.sex is not None and weight_kg is not None:
        return formulas.water_target_ml(profile.sex, weight_kg)
    return settings.daily_target_ml


def _settings_to_out(settings: WaterSettings, target_ml: int) -> WaterSettingsOut:
    return WaterSettingsOut(
        mode=settings.mode, daily_target_ml=target_ml, containers=settings.containers
    )


@router.get("/settings")
async def get_settings(
    user_id: UUID = Depends(get_current_user_id), session: AsyncSession = Depends(get_db)
) -> WaterSettingsOut:
    settings = await _get_or_create_settings(session, user_id)
    await session.commit()
    target_ml = await _effective_target_ml(session, user_id, settings)
    return _settings_to_out(settings, target_ml)


@router.put("/settings")
async def update_settings(
    body: WaterSettingsUpdate,
    user_id: UUID = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_db),
) -> WaterSettingsOut:
    settings = await _get_or_create_settings(session, user_id)
    if body.mode is not None:
        settings.mode = body.mode
    if body.daily_target_ml is not None:
        settings.daily_target_ml = body.daily_target_ml
    if body.containers is not None:
        settings.containers = [c.model_dump() for c in body.containers]
    await session.commit()
    await session.refresh(settings)
    target_ml = await _effective_target_ml(session, user_id, settings)
    return _settings_to_out(settings, target_ml)


class WaterLogIn(BaseModel):
    log_date: date
    ml: int = Field(gt=0, le=5000)
    # Ver `LogFoodIn.client_id`: hace idempotente el reenvío de un registro hecho sin conexión.
    client_id: UUID | None = None


class WaterLogEntry(BaseModel):
    id: UUID
    log_date: date
    ml: int


def _log_to_out(entry: WaterLog) -> WaterLogEntry:
    return WaterLogEntry(id=entry.id, log_date=entry.log_date, ml=entry.ml)


@router.post("/log", status_code=201)
async def log_water(
    body: WaterLogIn,
    user_id: UUID = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_db),
) -> WaterLogEntry:
    if body.client_id is not None:
        existing = await session.get(WaterLog, body.client_id)
        if existing is not None and existing.user_id == user_id:
            return _log_to_out(existing)
    entry = WaterLog(
        **({"id": body.client_id} if body.client_id is not None else {}),
        user_id=user_id,
        log_date=body.log_date,
        ml=body.ml,
    )
    session.add(entry)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise AppError(
            "CLIENT_ID_CONFLICT", "Ese identificador de registro ya está en uso.", status_code=409
        ) from exc
    await session.refresh(entry)
    return _log_to_out(entry)


@router.delete("/log/{entry_id}", status_code=204)
async def delete_water_log(
    entry_id: UUID,
    user_id: UUID = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_db),
) -> None:
    entry = await session.get(WaterLog, entry_id)
    if entry is None or entry.user_id != user_id:
        raise AppError("WATER_LOG_NOT_FOUND", "No existe ese registro de agua.", status_code=404)
    await session.delete(entry)
    await session.commit()


class WaterDayOut(BaseModel):
    date: date
    entries: list[WaterLogEntry]
    total_ml: int
    target_ml: int


@router.get("/log")
async def get_water_day(
    date: date,
    user_id: UUID = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_db),
) -> WaterDayOut:
    entries = list(
        await session.scalars(
            select(WaterLog)
            .where(WaterLog.user_id == user_id, WaterLog.log_date == date)
            .order_by(WaterLog.logged_at)
        )
    )
    settings = await _get_or_create_settings(session, user_id)
    await session.commit()
    target_ml = await _effective_target_ml(session, user_id, settings)
    return WaterDayOut(
        date=date,
        entries=[_log_to_out(e) for e in entries],
        total_ml=sum(e.ml for e in entries),
        target_ml=target_ml,
    )
