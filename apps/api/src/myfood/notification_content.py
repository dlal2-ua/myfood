"""Contenido de cada aviso (sección 13): corto, en español y accionable, calculado con los datos
de hoy del usuario. Si el aviso ya no tiene sentido (ya bebió su agua, ya tomó el suplemento, ya
registró esa comida, ya se pesó), devuelve `None` y no se envía nada — sin insistir.

Cada payload lleva `data` (qué tipo de aviso es y a qué se refiere) y `actions` (botones de la
notificación: el service worker los ejecuta contra el API sin abrir la app)."""

from __future__ import annotations

import math
from datetime import date, datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from myfood.db.models import (
    BodyMeasurement,
    FoodLog,
    NotificationRule,
    Supplement,
    SupplementLog,
    SupplementSchedule,
    SupplementStock,
    WaterSettings,
)
from myfood.domain import supplements as supplements_calc
from myfood.domain.water import drunk_ml, effective_target_ml
from myfood.notifications import message_for_rule

MEAL_LABELS = {
    "breakfast": "el desayuno",
    "morning_snack": "el tentempié de media mañana",
    "lunch": "la comida",
    "afternoon_snack": "la merienda",
    "dinner": "la cena",
    "supper": "la cena tardía",
}

_DEFAULT_GLASS_ML = 200


def _round_to_50(ml: int) -> int:
    return max(50, int(round(ml / 50) * 50))


async def _water(session: AsyncSession, rule: NotificationRule, today: date) -> dict | None:
    settings = await session.get(WaterSettings, rule.user_id)
    target = await effective_target_ml(session, rule.user_id, settings)
    remaining = target - await drunk_ml(session, rule.user_id, today)
    if remaining <= 0:
        return None  # objetivo cumplido: no se insiste
    glass = _DEFAULT_GLASS_ML
    if settings is not None and settings.containers:
        glass = int(settings.containers[0].get("ml", _DEFAULT_GLASS_ML))
    return {
        "title": "MyFood",
        "body": f"Te faltan {_round_to_50(remaining)} ml para tu objetivo de hoy.",
        "data": {"kind": "water", "ml": glass, "url": "/water"},
        "actions": [{"action": "add-water", "title": f"+{glass} ml"}],
    }


async def _supplement(
    session: AsyncSession, rule: NotificationRule, now: datetime
) -> dict | None:
    supplement_id = rule.schedule.get("supplement_id")
    if not supplement_id:
        return message_for_rule(rule)
    supplement = await session.get(Supplement, UUID(supplement_id))
    if supplement is None or not supplement.is_active:
        return None

    # Tomas de hoy de este suplemento, en orden: si ya hay tantos registros como tomas hasta la
    # de este aviso (inclusive), esta toma ya está resuelta.
    weekday = now.isoweekday()
    slots = [
        s
        for s in await session.scalars(
            select(SupplementSchedule)
            .where(SupplementSchedule.supplement_id == supplement.id)
            .order_by(SupplementSchedule.time_of_day)
        )
        if weekday in s.days_of_week
    ]
    schedule_id = rule.schedule.get("schedule_id")
    position = next(
        (i for i, s in enumerate(slots) if str(s.id) == schedule_id),
        len(slots) - 1,
    )
    logged = await session.scalar(
        select(func.count()).where(
            SupplementLog.supplement_id == supplement.id, SupplementLog.log_date == now.date()
        )
    )
    if (logged or 0) > position:
        return None
    dose = f"{float(supplement.dose_amount):g} {supplement.dose_unit}"
    return {
        "title": "MyFood",
        "body": f"Toca {supplement.name} ({dose}).",
        "data": {"kind": "supplement", "supplement_id": str(supplement.id), "url": "/supplements"},
        "actions": [
            {"action": "supplement-taken", "title": "Tomada"},
            {"action": "supplement-skip", "title": "Saltar"},
        ],
    }


async def _meal(session: AsyncSession, rule: NotificationRule, today: date) -> dict | None:
    meal_type = rule.schedule.get("meal_type")
    logged = await session.scalar(
        select(func.count()).where(
            FoodLog.user_id == rule.user_id,
            FoodLog.log_date == today,
            FoodLog.meal_type == meal_type,
        )
    )
    if logged:
        return None
    label = MEAL_LABELS.get(meal_type, "tu comida")
    return {
        "title": "MyFood",
        "body": f"Cuando termines, apunta {label}.",
        "data": {"kind": "meal", "meal_type": meal_type, "url": "/log"},
        "actions": [],
    }


async def _weigh_in(session: AsyncSession, rule: NotificationRule, today: date) -> dict | None:
    weighed = await session.scalar(
        select(func.count()).where(
            BodyMeasurement.user_id == rule.user_id,
            BodyMeasurement.measured_on == today,
            BodyMeasurement.weight_kg.is_not(None),
        )
    )
    if weighed:
        return None
    return {
        "title": "MyFood",
        "body": "Cuando quieras, apunta tu peso de hoy.",
        "data": {"kind": "weigh_in", "url": "/profile"},
        "actions": [],
    }


async def build_notification(
    session: AsyncSession, rule: NotificationRule, now_local: datetime
) -> dict | None:
    """Payload del aviso de `rule` para `now_local` (hora del usuario), o `None` si no procede."""
    custom = rule.schedule.get("message")
    today = now_local.date()
    if rule.kind == "water":
        payload = await _water(session, rule, today)
    elif rule.kind == "supplement":
        payload = await _supplement(session, rule, now_local)
    elif rule.kind == "meal":
        payload = await _meal(session, rule, today)
    elif rule.kind == "weigh_in":
        payload = await _weigh_in(session, rule, today)
    else:
        payload = message_for_rule(rule)
    if payload is not None and custom:
        payload = {**payload, "body": custom}
    return payload


async def low_stock_notifications(session: AsyncSession) -> list[tuple[UUID, UUID, dict]]:
    """Avisos de stock bajo (≤ 5 días): «Te quedan 4 días de magnesio». Devuelve
    `(user_id, supplement_id, payload)`; el worker los envía una vez al día."""
    rows = (
        await session.execute(
            select(Supplement, SupplementStock)
            .join(SupplementStock, SupplementStock.supplement_id == Supplement.id)
            .where(Supplement.is_active.is_(True))
        )
    ).all()
    if not rows:
        return []
    schedules_by_supplement: dict[UUID, list[list[int]]] = {}
    for schedule in await session.scalars(
        select(SupplementSchedule).where(
            SupplementSchedule.supplement_id.in_([s.id for s, _ in rows])
        )
    ):
        schedules_by_supplement.setdefault(schedule.supplement_id, []).append(
            list(schedule.days_of_week)
        )

    notifications = []
    for supplement, stock in rows:
        days_remaining, low = supplements_calc.stock_projection(
            float(stock.doses_remaining), schedules_by_supplement.get(supplement.id, [])
        )
        if days_remaining is None or not low:
            continue
        if days_remaining < 1:
            body = f"Se te está acabando {supplement.name}: reponlo pronto."
        else:
            days = math.floor(days_remaining)
            body = f"Te quedan {days} {'día' if days == 1 else 'días'} de {supplement.name}."
        notifications.append(
            (
                supplement.user_id,
                supplement.id,
                {
                    "title": "MyFood",
                    "body": body,
                    "data": {"kind": "low_stock", "url": "/supplements"},
                    "actions": [],
                },
            )
        )
    return notifications


def achievement_notification(title: str) -> dict:
    """Aviso de logro conseguido. Celebra constancia de registro, nunca un resultado
    corporal ni calórico (R10) — el texto no menciona peso, calorías ni objetivos."""
    return {
        "title": "¡Logro conseguido!",
        "body": f"{title} — échale un vistazo a tu progreso.",
        "data": {"kind": "achievement", "url": "/progress"},
        "actions": [],
    }
