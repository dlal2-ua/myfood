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


def test_due_times_for_meal_and_weigh_in_rules():
    assert due_times_for_rule({"time": "14:00", "meal_type": "lunch"}, "meal") == [time(14, 0)]
    assert due_times_for_rule({"time": "08:00"}, "weigh_in") == [time(8, 0)]


def test_due_times_for_an_unknown_kind_returns_empty():
    assert due_times_for_rule({"time": "09:00"}, "otra_cosa") == []


def test_water_reminders_are_capped_at_eight_a_day():
    schedule = {"times": [f"{h:02d}:00" for h in range(9, 21)]}
    assert len(due_times_for_rule(schedule, "water")) == 8


def test_a_rule_with_days_of_week_only_fires_those_days():
    schedule = {"time": "08:00", "days_of_week": [1, 3, 5]}
    assert due_times_for_rule(schedule, "weigh_in", weekday=3) == [time(8, 0)]
    assert due_times_for_rule(schedule, "weigh_in", weekday=2) == []
    assert due_times_for_rule(schedule, "weigh_in") == [time(8, 0)]  # sin día: no se filtra


def test_is_rule_due_uses_the_weekday_of_now():
    rule = _rule("weigh_in", {"time": "08:00", "days_of_week": [1]})
    monday = datetime(2026, 1, 12, 8, 0)
    tuesday = datetime(2026, 1, 13, 8, 0)
    assert is_rule_due(rule, monday)[0] is True
    assert is_rule_due(rule, tuesday)[0] is False


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


def test_is_rule_due_kind_without_producer_never_fires():
    rule = _rule("otra_cosa", {"time": "08:00"}, quiet_from=time(0, 0), quiet_to=time(0, 0))
    now = datetime(2026, 1, 15, 8, 0)
    due, _slot = is_rule_due(rule, now)
    assert due is False


def test_message_for_rule_uses_custom_message():
    rule = _rule("supplement", {"time": "09:00", "message": "Toca la creatina"})
    assert message_for_rule(rule)["body"] == "Toca la creatina"


def test_message_for_rule_default_by_kind():
    rule = _rule("water", {"times": ["10:00"]})
    assert "agua" in message_for_rule(rule)["body"].lower()
