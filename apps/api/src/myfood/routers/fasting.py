"""Ayuno intermitente (sección 6.6, `/ayuno`): temporizador y ventana de alimentación, con
historial y adherencia. Sigue la regla R10: «adherencia» = ayunos que llegaron a su objetivo entre
los que se hicieron; no hay rachas que castiguen romper un ayuno.

No es una recomendación médica: la interfaz lo dice y avisa cuando el objetivo pasa de 24 h."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from myfood.db.models import FastingWindow
from myfood.deps import get_current_user_id, get_db
from myfood.errors import AppError
from myfood.routers.consents import require_health_data_consent

router = APIRouter(prefix="/fasting", tags=["fasting"])

LONG_FAST_HOURS = 24


class FastingOut(BaseModel):
    id: UUID
    started_at: datetime
    ended_at: datetime | None
    target_hours: float
    elapsed_hours: float
    remaining_hours: float
    eating_window_hours: float
    reached_target: bool
    warnings: list[str]


def _now() -> datetime:
    return datetime.now(UTC)


def _to_out(window: FastingWindow, now: datetime) -> FastingOut:
    end = window.ended_at or now
    elapsed = max((end - window.started_at).total_seconds() / 3600, 0.0)
    target = float(window.target_hours)
    return FastingOut(
        id=window.id,
        started_at=window.started_at,
        ended_at=window.ended_at,
        target_hours=target,
        elapsed_hours=round(elapsed, 2),
        remaining_hours=round(max(target - elapsed, 0.0), 2),
        eating_window_hours=round(max(24 - target, 0.0), 1),
        reached_target=elapsed >= target,
        warnings=["LONG_FAST_WARNING"] if target > LONG_FAST_HOURS else [],
    )


class StartFastingIn(BaseModel):
    target_hours: float = Field(default=16, ge=1, le=72)
    started_at: datetime | None = None


@router.post("/start", status_code=201, dependencies=[Depends(require_health_data_consent)])
async def start_fasting(
    body: StartFastingIn,
    user_id: UUID = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_db),
) -> FastingOut:
    now = _now()
    started_at = body.started_at or now
    if started_at.tzinfo is None:
        started_at = started_at.replace(tzinfo=UTC)
    if started_at > now + timedelta(minutes=5):
        raise AppError("FASTING_IN_THE_FUTURE", "Un ayuno no puede empezar en el futuro.", 422)

    window = FastingWindow(user_id=user_id, started_at=started_at, target_hours=body.target_hours)
    session.add(window)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise AppError(
            "FASTING_ALREADY_ACTIVE", "Ya tienes un ayuno en curso: termínalo primero.", 409
        ) from exc
    await session.refresh(window)
    return _to_out(window, now)


class EndFastingIn(BaseModel):
    ended_at: datetime | None = None


@router.post("/{window_id}/end", dependencies=[Depends(require_health_data_consent)])
async def end_fasting(
    window_id: UUID,
    body: EndFastingIn,
    user_id: UUID = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_db),
) -> FastingOut:
    window = await session.get(FastingWindow, window_id)
    if window is None or window.user_id != user_id:
        raise AppError("FASTING_NOT_FOUND", "No existe ese ayuno.", status_code=404)
    if window.ended_at is not None:
        raise AppError("FASTING_ALREADY_ENDED", "Ese ayuno ya está terminado.", status_code=409)

    now = _now()
    ended_at = body.ended_at or now
    if ended_at.tzinfo is None:
        ended_at = ended_at.replace(tzinfo=UTC)
    if ended_at < window.started_at:
        raise AppError(
            "FASTING_ENDS_BEFORE_START", "El ayuno no puede terminar antes de empezar.", 422
        )
    window.ended_at = min(ended_at, now)
    await session.commit()
    await session.refresh(window)
    return _to_out(window, now)


@router.get("/current")
async def get_current_fasting(
    user_id: UUID = Depends(get_current_user_id), session: AsyncSession = Depends(get_db)
) -> FastingOut | None:
    window = await session.scalar(
        select(FastingWindow).where(
            FastingWindow.user_id == user_id, FastingWindow.ended_at.is_(None)
        )
    )
    return _to_out(window, _now()) if window is not None else None


@router.get("/history")
async def get_fasting_history(
    limit: Annotated[int, Query(ge=1, le=200)] = 30,
    user_id: UUID = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_db),
) -> list[FastingOut]:
    rows = await session.scalars(
        select(FastingWindow)
        .where(FastingWindow.user_id == user_id, FastingWindow.ended_at.is_not(None))
        .order_by(FastingWindow.started_at.desc())
        .limit(limit)
    )
    now = _now()
    return [_to_out(w, now) for w in rows]


class FastingStats(BaseModel):
    period_days: int
    fasts: int
    reached_target: int
    adherence_pct: float | None
    avg_hours: float | None
    longest_hours: float | None


@router.get("/stats")
async def get_fasting_stats(
    days: Annotated[int, Query(ge=7, le=365)] = 30,
    user_id: UUID = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_db),
) -> FastingStats:
    now = _now()
    rows = await session.scalars(
        select(FastingWindow).where(
            FastingWindow.user_id == user_id,
            FastingWindow.ended_at.is_not(None),
            FastingWindow.started_at >= now - timedelta(days=days),
        )
    )
    fasts = [_to_out(w, now) for w in rows]
    reached = sum(f.reached_target for f in fasts)
    return FastingStats(
        period_days=days,
        fasts=len(fasts),
        reached_target=reached,
        adherence_pct=round(100 * reached / len(fasts), 1) if fasts else None,
        avg_hours=round(sum(f.elapsed_hours for f in fasts) / len(fasts), 1) if fasts else None,
        longest_hours=round(max(f.elapsed_hours for f in fasts), 1) if fasts else None,
    )


@router.delete("/{window_id}", status_code=204)
async def delete_fasting(
    window_id: UUID,
    user_id: UUID = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_db),
) -> None:
    window = await session.get(FastingWindow, window_id)
    if window is None or window.user_id != user_id:
        raise AppError("FASTING_NOT_FOUND", "No existe ese ayuno.", status_code=404)
    await session.delete(window)
    await session.commit()
