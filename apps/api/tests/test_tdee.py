"""TDEE adaptativo (`myfood.domain.tdee`, Fase 7, documento 2 secciones 6.7/8).

Igual que `test_profile_and_calc.py`, los valores esperados se recalculan
aquí llamando a `myfood.domain.formulas` directamente — se verifica que
`/calc/targets` conecta bien el historial real (medidas + registro diario)
con esas fórmulas, no se reimplementa la aritmética a mano.
"""

from datetime import date, timedelta

import pytest
from sqlalchemy import text

from myfood.domain import formulas

pytestmark = pytest.mark.asyncio


async def _setup_profile(client, *, weight_today: float) -> None:
    await client.put(
        "/api/profile",
        json={
            "sex": "female",
            "height_cm": 165,
            "birth_date": "1990-06-15",
            "activity_level": "light",
            "goal": "maintain",
        },
    )
    await client.post(
        "/api/measurements",
        json={"measured_on": date.today().isoformat(), "weight_kg": weight_today},
    )


async def _log_weights(client, daily_weights: list[float]) -> None:
    """Registra `daily_weights[0]` hace `len - 1` días y así hasta hoy."""
    days = len(daily_weights)
    for offset, weight in zip(range(days - 1, -1, -1), daily_weights, strict=True):
        day = (date.today() - timedelta(days=offset)).isoformat()
        resp = await client.post(
            "/api/measurements", json={"measured_on": day, "weight_kg": weight}
        )
        assert resp.status_code == 201


async def _log_intake(client, test_food, days_ago: list[int], grams: float) -> None:
    for offset in days_ago:
        day = (date.today() - timedelta(days=offset)).isoformat()
        resp = await client.post(
            "/api/log/food",
            json={
                "log_date": day,
                "meal_type": "breakfast",
                "food_id": str(test_food),
                "grams": grams,
            },
        )
        assert resp.status_code == 201


async def test_targets_stays_on_formula_without_history(registered_client):
    """Con solo la medida de hoy (sin historial de 14 días) sigue en 'formula' —
    caso ya cubierto por test_profile_and_calc.py, repetido aquí como
    ancla explícita del criterio de aceptación de la Fase 7."""
    client, _ = registered_client
    await _setup_profile(client, weight_today=60)

    resp = await client.get("/api/calc/targets")
    assert resp.status_code == 200
    assert resp.json()["source"] == "formula"


async def test_targets_stay_on_formula_with_fewer_than_10_logging_days(
    registered_client, test_food
):
    """Criterio de aceptación de la Fase 7: 'Se marca no fiable con menos de
    10 días de registro' — aquí hay 14 días de peso pero solo 5 de comida."""
    client, user_id = registered_client
    weights = [90.0 - 0.1 * i for i in range(14)]  # 90.0 .. 88.7, monótona
    await _setup_profile(client, weight_today=weights[-1])
    await _log_weights(client, weights)
    await _log_intake(client, test_food, days_ago=[0, 2, 4, 6, 8], grams=1000)  # 5 días

    resp = await client.get("/api/calc/targets")
    assert resp.status_code == 200
    assert resp.json()["source"] == "formula"


async def test_targets_switch_to_adaptive_tdee_with_enough_history(
    registered_client, superuser_conn, test_food
):
    """Criterio de aceptación de la Fase 7: el TDEE adaptativo se calcula
    tras 14 días (con >=10 días de registro real) y sustituye a la fórmula."""
    client, user_id = registered_client
    weights = [90.0 - 0.1 * i for i in range(14)]  # 90.0 .. 88.7
    await _setup_profile(client, weight_today=weights[-1])
    await _log_weights(client, weights)
    # 12 de los 14 días con comida (>=10 exigidos), 1650 kcal/día constantes
    # (test_food: 165 kcal/100 g × 1000 g).
    await _log_intake(client, test_food, days_ago=list(range(12)), grams=1000)

    resp = await client.get("/api/calc/targets")
    assert resp.status_code == 200
    body = resp.json()
    assert body["source"] == "adaptive_tdee"

    # Recálculo independiente, mismo criterio que test_calc_targets_matches_formulas.
    trend = formulas.ema_weight_trend(weights)
    delta_kg = trend[-1] - trend[0]
    kcal_delta = (delta_kg * 7700) / 14
    avg_intake = 1650.0  # constante en los 12 días registrados
    estimated_tdee = avg_intake - kcal_delta

    age_years = (date.today() - date(1990, 6, 15)).days / 365.25
    bmr = formulas.bmr_mifflin("female", weights[-1], 165, age_years)
    kcal, _ = formulas.calorie_target(estimated_tdee, "maintain", 0.5, bmr, "female")

    assert body["kcal"] == pytest.approx(round(kcal, 1), abs=0.2)

    # La estimación queda persistida (no solo calculada al vuelo).
    row = (
        await superuser_conn.execute(
            text(
                "SELECT is_reliable, logging_days, estimated_tdee "
                "FROM tdee_estimates WHERE user_id = :uid"
            ),
            {"uid": str(user_id)},
        )
    ).one()
    assert row.is_reliable is True
    assert row.logging_days == 12
    assert float(row.estimated_tdee) == pytest.approx(estimated_tdee, abs=0.01)
