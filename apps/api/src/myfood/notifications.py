"""Lógica pura de cuándo dispara un `notification_rule` (sección 10, Fase 3)
— sin I/O, testeable sin BD/Redis/red. El worker (`myfood/worker.py`) solo
añade el bucle, la deduplicación en Redis y el envío real.
"""

from datetime import datetime, time

from myfood.db.models import NotificationRule


def in_quiet_hours(now_time: time, quiet_from: time, quiet_to: time) -> bool:
    if quiet_from <= quiet_to:
        return quiet_from <= now_time < quiet_to
    return now_time >= quiet_from or now_time < quiet_to  # rango que cruza medianoche


def _parse_time(value: str) -> time:
    hh, mm = value.split(":")
    return time(int(hh), int(mm))


def due_times_for_rule(schedule: dict, kind: str) -> list[time]:
    """Extrae los horarios programados de `schedule` — su forma depende de
    `kind` (sección 9): 'water' trae varias horas al día, 'supplement' una
    sola. 'meal'/'weigh_in' no tienen productor todavía (llegan en fases
    posteriores) — devuelve lista vacía, nunca inventa un horario."""
    if kind == "water":
        return [_parse_time(t) for t in schedule.get("times", [])]
    if kind == "supplement":
        raw = schedule.get("time")
        return [_parse_time(raw)] if raw else []
    return []


def is_rule_due(
    rule: NotificationRule, now: datetime, tolerance_minutes: int = 2
) -> tuple[bool, time | None]:
    """¿Hay algún horario de esta regla dentro de `tolerance_minutes` de
    `now`, fuera de las horas de silencio? Devuelve `(debido, slot)` — el
    `slot` (horario programado exacto, no `now`) sirve de clave de
    deduplicación: una regla con varios horarios al día no debe confundir
    "ya enviado el de las 10:00" con "ya enviado el de las 13:00"."""
    now_time = now.time()
    if in_quiet_hours(now_time, rule.quiet_from, rule.quiet_to):
        return False, None

    now_minutes = now_time.hour * 60 + now_time.minute
    for slot in due_times_for_rule(rule.schedule, rule.kind):
        slot_minutes = slot.hour * 60 + slot.minute
        if abs(now_minutes - slot_minutes) <= tolerance_minutes:
            return True, slot
    return False, None


def message_for_rule(rule: NotificationRule) -> dict:
    """Payload de la notificación — título/cuerpo por defecto según `kind`,
    o el mensaje explícito de `schedule.message` si lo trae (p. ej. un
    suplemento con nombre propio: "Toca la creatina")."""
    custom = rule.schedule.get("message")
    if custom:
        return {"title": "MyFood", "body": custom}
    if rule.kind == "water":
        return {"title": "MyFood", "body": "Hora de beber agua."}
    if rule.kind == "supplement":
        return {"title": "MyFood", "body": "Toca un suplemento."}
    return {"title": "MyFood", "body": "Tienes un recordatorio pendiente."}
