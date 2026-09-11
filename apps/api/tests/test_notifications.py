"""Tests puros de `notifications.py` (sección 9/10, Fase 3) — sin BD/Redis/red."""

import uuid
from datetime import datetime, time

from myfood.db.models import NotificationRule
from myfood.notifications import (
    due_times_for_rule,
    in_quiet_hours,
    is_rule_due,
    message_for_rule,
)


def _rule(
    kind: str, schedule: dict, quiet_from=time(23, 0), quiet_to=time(8, 0)
) -> NotificationRule:
    return NotificationRule(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        kind=kind,
        is_enabled=True,
        schedule=schedule,
        quiet_from=quiet_from,
        quiet_to=quiet_to,
    )


def test_in_quiet_hours_normal_range():
    assert in_quiet_hours(time(14, 0), time(12, 0), time(16, 0)) is True
    assert in_quiet_hours(time(10, 0), time(12, 0), time(16, 0)) is False


def test_in_quiet_hours_crossing_midnight():
    assert in_quiet_hours(time(23, 30), time(23, 0), time(8, 0)) is True
    assert in_quiet_hours(time(3, 0), time(23, 0), time(8, 0)) is True
    assert in_quiet_hours(time(12, 0), time(23, 0), time(8, 0)) is False


def test_due_times_for_water_rule():
    times = due_times_for_rule({"times": ["10:00", "13:30"]}, "water")
    assert times == [time(10, 0), time(13, 30)]


def test_due_times_for_supplement_rule():
    assert due_times_for_rule({"time": "09:00"}, "supplement") == [time(9, 0)]


def test_due_times_for_unimplemented_kind_returns_empty():
    assert due_times_for_rule({"time": "09:00"}, "meal") == []


def test_is_rule_due_within_tolerance():
    rule = _rule("water", {"times": ["10:00"]})
    now = datetime(2026, 1, 15, 10, 1)  # 1 minuto de margen, tolerancia default 2
    due, slot = is_rule_due(rule, now)
    assert due is True
    assert slot == time(10, 0)


def test_is_rule_due_outside_tolerance():
    rule = _rule("water", {"times": ["10:00"]})
    now = datetime(2026, 1, 15, 10, 10)
    due, slot = is_rule_due(rule, now)
    assert due is False
    assert slot is None


def test_is_rule_due_respects_quiet_hours():
    # 07:30 coincide con un horario de las 07:30 pero cae en las horas de
    # silencio por defecto (23:00 -> 08:00) — no debe disparar.
    rule = _rule("water", {"times": ["07:30"]})
    now = datetime(2026, 1, 15, 7, 30)
    due, _slot = is_rule_due(rule, now)
    assert due is False


def test_is_rule_due_disabled_kind_never_fires():
    rule = _rule("weigh_in", {"time": "08:00"}, quiet_from=time(0, 0), quiet_to=time(0, 0))
    now = datetime(2026, 1, 15, 8, 0)
    due, _slot = is_rule_due(rule, now)
    assert due is False


def test_message_for_rule_uses_custom_message():
    rule = _rule("supplement", {"time": "09:00", "message": "Toca la creatina"})
    assert message_for_rule(rule)["body"] == "Toca la creatina"


def test_message_for_rule_default_by_kind():
    rule = _rule("water", {"times": ["10:00"]})
    assert "agua" in message_for_rule(rule)["body"].lower()
