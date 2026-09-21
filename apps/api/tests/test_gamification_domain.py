"""domain/gamification.py — funciones puras (R10, documento 2 sección 23)."""

from datetime import date, timedelta

from myfood.domain.gamification import build_achievements, compute_streaks


def _d(offset: int, today: date) -> date:
    return today - timedelta(days=offset)


def test_compute_streaks_empty_history():
    today = date(2026, 9, 18)
    assert compute_streaks(set(), today=today) == (0, 0)


def test_compute_streaks_current_streak_counts_consecutive_days_ending_today():
    today = date(2026, 9, 18)
    dates = {_d(0, today), _d(1, today), _d(2, today)}
    current, longest = compute_streaks(dates, today=today)
    assert current == 3
    assert longest == 3


def test_compute_streaks_today_missing_does_not_break_streak_yet():
    """Todavía no ha terminado el día — no registrar hoy no rompe la racha
    hasta que empiece un día nuevo sin registro."""
    today = date(2026, 9, 18)
    dates = {_d(1, today), _d(2, today), _d(3, today)}
    current, _ = compute_streaks(dates, today=today)
    assert current == 3


def test_compute_streaks_gap_breaks_current_streak():
    today = date(2026, 9, 18)
    dates = {_d(0, today), _d(1, today), _d(5, today), _d(6, today)}
    current, longest = compute_streaks(dates, today=today)
    assert current == 2  # hoy y ayer
    assert longest == 2  # el hueco entre día -1 y día -5 rompe cualquier racha mayor


def test_compute_streaks_longest_can_be_in_the_past_even_if_current_is_broken():
    today = date(2026, 9, 18)
    old_streak = {_d(30, today), _d(29, today), _d(28, today), _d(27, today), _d(26, today)}
    dates = old_streak | {_d(0, today)}
    current, longest = compute_streaks(dates, today=today)
    assert current == 1
    assert longest == 5


def test_build_achievements_none_earned_with_no_activity():
    achievements = build_achievements(longest_streak=0, water_logging_days=0, distinct_recipes=0)
    assert all(not a.earned for a in achievements)


def test_build_achievements_streak_thresholds():
    achievements = build_achievements(longest_streak=30, water_logging_days=0, distinct_recipes=0)
    by_key = {a.key: a for a in achievements}
    assert by_key["streak_7"].earned is True
    assert by_key["streak_30"].earned is True
    assert by_key["streak_100"].earned is False
    assert by_key["streak_100"].progress == 30


def test_build_achievements_water_and_recipes():
    achievements = build_achievements(
        longest_streak=0, water_logging_days=45, distinct_recipes=10
    )
    by_key = {a.key: a for a in achievements}
    assert by_key["water_30_days"].earned is True
    assert by_key["water_30_days"].progress == 30  # tope en el objetivo, no 45
    assert by_key["recipes_10"].earned is True


def test_no_achievement_ever_mentions_weight_or_calories():
    """R10: los logros premian consistencia y variedad, nunca resultado
    corporal — comprobación explícita de que ninguna descripción usa
    lenguaje de peso/calorías/déficit."""
    achievements = build_achievements(
        longest_streak=100, water_logging_days=30, distinct_recipes=10
    )
    banned_words = ["peso", "kcal", "calor", "déficit", "deficit", "grasa"]
    for a in achievements:
        text = f"{a.title} {a.description}".lower()
        for word in banned_words:
            assert word not in text


def test_every_achievement_has_a_badge():
    """Cada logro lleva su insignia: sin `icon`/`tier`/`family` la pared de insignias
    no sabría qué dibujar ni dónde agruparlo."""
    from myfood.domain.gamification import TIERS

    for a in build_achievements():
        assert a.icon
        assert a.tier in TIERS
        assert a.family


def test_build_achievements_tolerates_missing_counters():
    """Un contador que no se pase cuenta como 0 — añadir un logro nuevo no puede romper
    a quien llame con los contadores de antes."""
    achievements = build_achievements(longest_streak=7)
    by_key = {a.key: a for a in achievements}
    assert by_key["streak_7"].earned is True
    assert by_key["water_7_days"].earned is False
    assert by_key["water_7_days"].progress == 0


def test_new_families_thresholds():
    achievements = build_achievements(
        logging_days=30, distinct_foods=50, complete_days=10, water_logging_days=7
    )
    by_key = {a.key: a for a in achievements}
    assert by_key["first_log"].earned is True
    assert by_key["logging_30_days"].earned is True
    assert by_key["logging_180_days"].earned is False
    assert by_key["variety_50_foods"].earned is True
    assert by_key["variety_200_foods"].earned is False
    assert by_key["complete_days_10"].earned is True
    assert by_key["water_7_days"].earned is True


def test_no_achievement_mentions_weight_or_calories_even_with_the_new_ones():
    """Misma comprobación de R10 que arriba, pero sobre la lista COMPLETA: ninguna
    insignia nueva puede colarse premiando resultado corporal."""
    banned_words = ["peso", "kcal", "calor", "déficit", "deficit", "grasa", "báscula", "adelgaz"]
    for a in build_achievements():
        text = f"{a.title} {a.description}".lower()
        for word in banned_words:
            assert word not in text, f"{a.key} menciona «{word}»"
