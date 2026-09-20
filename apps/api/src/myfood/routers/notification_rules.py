"""Reglas de recordatorio (sección 9, Fase 3) — CRUD simple; la lógica de
"cuándo dispara" vive en `myfood/notifications.py` y el envío en el worker.
"""

import re
from datetime import time
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from myfood.db.models import NotificationRule
from myfood.deps import get_current_user_id, get_db
from myfood.errors import AppError
from myfood.notification_rules_defaults import default_quiet_hours
from myfood.notifications import MAX_WATER_REMINDERS_PER_DAY

router = APIRouter(prefix="/notification-rules", tags=["notification-rules"])

NotificationKind = Literal["water", "supplement", "meal", "weigh_in"]


_HHMM = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
_MEAL_TYPES = {
    "breakfast", "morning_snack", "lunch", "afternoon_snack", "dinner", "supper",
}


def _invalid(message: str) -> AppError:
    return AppError("INVALID_SCHEDULE", message, status_code=422)


def validate_schedule(kind: str, schedule: dict) -> None:
    """La forma de `schedule` depende de `kind` (sección 9); un horario mal formado no debe llegar
    al worker, que lo ignoraría en silencio y el usuario creería que tiene un recordatorio."""
    days = schedule.get("days_of_week")
    if days is not None and (
        not isinstance(days, list) or not days or any(d not in range(1, 8) for d in days)
    ):
        raise _invalid("days_of_week debe ser una lista de días entre 1 (lunes) y 7 (domingo).")
    if kind == "water":
        times = schedule.get("times")
        if not isinstance(times, list) or not times:
            raise _invalid("Un recordatorio de agua necesita al menos una hora en `times`.")
        if len(times) > MAX_WATER_REMINDERS_PER_DAY:
            raise _invalid(
                f"Como máximo {MAX_WATER_REMINDERS_PER_DAY} recordatorios de agua al día."
            )
        if not all(isinstance(t, str) and _HHMM.match(t) for t in times):
            raise _invalid("Las horas deben tener el formato HH:MM.")
        return
    raw = schedule.get("time")
    if not isinstance(raw, str) or not _HHMM.match(raw):
        raise _invalid("Este recordatorio necesita una hora `time` con el formato HH:MM.")
    if kind == "meal" and schedule.get("meal_type") not in _MEAL_TYPES:
        raise _invalid("Un recordatorio de comida necesita un `meal_type` válido.")


class NotificationRuleIn(BaseModel):
    kind: NotificationKind
    schedule: dict
    is_enabled: bool = True
    # Sin indicar, la regla nueva hereda el «no molestar» que el usuario ya tiene.
    quiet_from: time | None = None
    quiet_to: time | None = None


class NotificationRulePatch(BaseModel):
    schedule: dict | None = None
    is_enabled: bool | None = None
    quiet_from: time | None = None
    quiet_to: time | None = None


class NotificationRuleOut(BaseModel):
    id: UUID
    kind: str
    is_enabled: bool
    schedule: dict
    quiet_from: time
    quiet_to: time


def _to_out(rule: NotificationRule) -> NotificationRuleOut:
    return NotificationRuleOut(
        id=rule.id,
        kind=rule.kind,
        is_enabled=rule.is_enabled,
        schedule=rule.schedule,
        quiet_from=rule.quiet_from,
        quiet_to=rule.quiet_to,
    )


async def _get_rule(session: AsyncSession, user_id: UUID, rule_id: UUID) -> NotificationRule:
    rule = await session.get(NotificationRule, rule_id)
    if rule is None or rule.user_id != user_id:
        raise AppError("RULE_NOT_FOUND", "No existe esa regla de recordatorio.", status_code=404)
    return rule


class QuietHours(BaseModel):
    quiet_from: time
    quiet_to: time


@router.get("/quiet-hours")
async def get_quiet_hours(
    user_id: UUID = Depends(get_current_user_id), session: AsyncSession = Depends(get_db)
) -> QuietHours:
    """Las horas de «no molestar» del usuario (las de sus reglas; 23:00–08:00 si no tiene)."""
    quiet_from, quiet_to = await default_quiet_hours(session, user_id)
    return QuietHours(quiet_from=quiet_from, quiet_to=quiet_to)


@router.put("/quiet-hours")
async def set_quiet_hours(
    body: QuietHours,
    user_id: UUID = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_db),
) -> QuietHours:
    """Aplica esas horas de «no molestar» a TODAS las reglas del usuario: fuera de ese tramo se
    envían los recordatorios, dentro se silencian."""
    await session.execute(
        update(NotificationRule)
        .where(NotificationRule.user_id == user_id)
        .values(quiet_from=body.quiet_from, quiet_to=body.quiet_to)
    )
    await session.commit()
    return body


@router.post("", status_code=201)
async def create_rule(
    body: NotificationRuleIn,
    user_id: UUID = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_db),
) -> NotificationRuleOut:
    validate_schedule(body.kind, body.schedule)
    default_from, default_to = await default_quiet_hours(session, user_id)
    rule = NotificationRule(
        user_id=user_id,
        kind=body.kind,
        schedule=body.schedule,
        is_enabled=body.is_enabled,
        quiet_from=body.quiet_from or default_from,
        quiet_to=body.quiet_to or default_to,
    )
    session.add(rule)
    await session.commit()
    await session.refresh(rule)
    return _to_out(rule)


@router.get("")
async def list_rules(
    kind: NotificationKind | None = None,
    user_id: UUID = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_db),
) -> list[NotificationRuleOut]:
    stmt = select(NotificationRule).where(NotificationRule.user_id == user_id)
    if kind is not None:
        stmt = stmt.where(NotificationRule.kind == kind)
    rules = await session.scalars(stmt)
    return [_to_out(r) for r in rules]


@router.patch("/{rule_id}")
async def update_rule(
    rule_id: UUID,
    body: NotificationRulePatch,
    user_id: UUID = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_db),
) -> NotificationRuleOut:
    rule = await _get_rule(session, user_id, rule_id)
    if body.schedule is not None:
        validate_schedule(rule.kind, body.schedule)
        rule.schedule = body.schedule
    if body.is_enabled is not None:
        rule.is_enabled = body.is_enabled
    if body.quiet_from is not None:
        rule.quiet_from = body.quiet_from
    if body.quiet_to is not None:
        rule.quiet_to = body.quiet_to
    await session.commit()
    await session.refresh(rule)
    return _to_out(rule)


@router.delete("/{rule_id}", status_code=204)
async def delete_rule(
    rule_id: UUID,
    user_id: UUID = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_db),
) -> None:
    rule = await _get_rule(session, user_id, rule_id)
    await session.delete(rule)
    await session.commit()
