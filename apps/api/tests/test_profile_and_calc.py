"""Endpoints /profile, /measurements y /calc/* (Fase 1, documento 2 sección 7.1/7.4).

Los valores esperados se calculan llamando a myfood.domain.formulas
directamente (el mismo módulo con cobertura 100% y tests unitarios propios en
test_formulas.py) — aquí se verifica que el router los conecta bien al
perfil/medidas reales, no se reimplementa la aritmética a mano otra vez.
"""

from datetime import date

import pytest

from myfood.domain import formulas

pytestmark = pytest.mark.asyncio


async def test_get_profile_returns_defaults_when_not_set(registered_client):
    client, _ = registered_client
    resp = await client.get("/api/profile")
    assert resp.status_code == 200
    body = resp.json()
    assert body["activity_level"] == "moderate"
    assert body["goal"] == "maintain"
    assert body["meals_per_day"] == 4
    assert body["sex"] is None


async def test_put_profile_updates_fields(registered_client):
    client, _ = registered_client
    resp = await client.put(
        "/api/profile",
        json={"sex": "male", "height_cm": 180, "activity_level": "active", "meals_per_day": 5},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["sex"] == "male"
    assert body["height_cm"] == 180
    assert body["activity_level"] == "active"
    assert body["meals_per_day"] == 5

    again = await client.get("/api/profile")
    assert again.json()["sex"] == "male"


async def test_put_profile_rejects_impossible_height(registered_client):
    client, _ = registered_client
    resp = await client.put("/api/profile", json={"height_cm": -10})
    assert resp.status_code == 422


async def test_measurements_create_and_list(registered_client):
    client, _ = registered_client
    today = date.today().isoformat()
    resp = await client.post(
        "/api/measurements", json={"measured_on": today, "weight_kg": 82.4, "source": "manual"}
    )
    assert resp.status_code == 201
    assert resp.json()["weight_kg"] == 82.4

    listed = await client.get("/api/measurements")
    assert listed.status_code == 200
    dates = [m["measured_on"] for m in listed.json()]
    assert today in dates


async def test_measurements_upsert_same_day(registered_client):
    client, _ = registered_client
    today = date.today().isoformat()
    await client.post("/api/measurements", json={"measured_on": today, "weight_kg": 80.0})
    resp = await client.post("/api/measurements", json={"measured_on": today, "weight_kg": 79.5})
    assert resp.status_code == 201

    listed = (await client.get("/api/measurements")).json()
    same_day = [m for m in listed if m["measured_on"] == today]
    assert len(same_day) == 1
    assert same_day[0]["weight_kg"] == 79.5


async def test_calc_bmr_requires_complete_profile(registered_client):
    client, _ = registered_client
    resp = await client.post("/api/calc/bmr", json={})
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "PROFILE_INCOMPLETE"


async def test_calc_bmr_requires_weight_measurement(registered_client):
    client, _ = registered_client
    await client.put(
        "/api/profile",
        json={"sex": "male", "height_cm": 180, "birth_date": "1996-01-01"},
    )
    resp = await client.post("/api/calc/bmr", json={})
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "MISSING_MEASUREMENTS"


async def test_calc_bmr_mifflin_matches_formula(registered_client):
    client, _ = registered_client
    birth_date = "1996-01-01"
    await client.put(
        "/api/profile",
        json={
            "sex": "male",
            "height_cm": 180,
            "birth_date": birth_date,
            "activity_level": "moderate",
        },
    )
    await client.post(
        "/api/measurements", json={"measured_on": date.today().isoformat(), "weight_kg": 80}
    )

    resp = await client.post("/api/calc/bmr", json={"formula": "mifflin"})
    assert resp.status_code == 200
    body = resp.json()

    age_years = (date.today() - date(1996, 1, 1)).days / 365.25
    expected_bmr = formulas.bmr_mifflin("male", 80, 180, age_years)
    expected_tdee = formulas.tdee(expected_bmr, "moderate")
    assert body["bmr"] == pytest.approx(round(expected_bmr, 1), abs=0.2)
    assert body["tdee"] == pytest.approx(round(expected_tdee, 1), abs=0.2)
    assert body["formula_used"] == "mifflin"


async def test_calc_bmr_katch_requires_body_fat(registered_client):
    client, _ = registered_client
    await client.put(
        "/api/profile", json={"sex": "male", "height_cm": 180, "birth_date": "1996-01-01"}
    )
    await client.post(
        "/api/measurements", json={"measured_on": date.today().isoformat(), "weight_kg": 80}
    )
    resp = await client.post("/api/calc/bmr", json={"formula": "katch"})
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "MISSING_MEASUREMENTS"


async def test_calc_bmr_katch_with_body_fat_matches_formula(registered_client):
    client, _ = registered_client
    await client.put(
        "/api/profile", json={"sex": "male", "height_cm": 180, "birth_date": "1996-01-01"}
    )
    await client.post(
        "/api/measurements",
        json={"measured_on": date.today().isoformat(), "weight_kg": 80, "body_fat_pct": 18},
    )
    resp = await client.post("/api/calc/bmr", json={"formula": "katch"})
    assert resp.status_code == 200
    expected_lean = formulas.lean_mass_kg(80, 18)
    expected_bmr = formulas.bmr_katch(expected_lean)
    assert resp.json()["bmr"] == pytest.approx(round(expected_bmr, 1))


async def test_calc_body_fat_navy_male_matches_formula(registered_client):
    client, _ = registered_client
    resp = await client.post(
        "/api/calc/body-fat",
        json={"method": "navy", "sex": "male", "height_cm": 180, "neck_cm": 38, "waist_cm": 85},
    )
    assert resp.status_code == 200
    expected_pct, _ = formulas.body_fat_navy("male", 180, 38, 85)
    assert resp.json()["body_fat_pct"] == pytest.approx(round(expected_pct, 1))
    assert resp.json()["lean_mass_kg"] is None  # sin peso disponible


async def test_calc_body_fat_navy_female_requires_hip(registered_client):
    client, _ = registered_client
    resp = await client.post(
        "/api/calc/body-fat",
        json={"method": "navy", "sex": "female", "height_cm": 165, "neck_cm": 32, "waist_cm": 70},
    )
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "MISSING_HIP_MEASUREMENT"


async def test_calc_body_fat_includes_lean_mass_with_weight(registered_client):
    client, _ = registered_client
    resp = await client.post(
        "/api/calc/body-fat",
        json={
            "method": "navy",
            "sex": "male",
            "height_cm": 180,
            "neck_cm": 38,
            "waist_cm": 85,
            "weight_kg": 80,
        },
    )
    body = resp.json()
    assert body["lean_mass_kg"] is not None
    assert body["ffmi"] is not None


async def test_calc_targets_matches_formulas(registered_client):
    client, _ = registered_client
    birth_date = "1990-06-15"
    await client.put(
        "/api/profile",
        json={
            "sex": "female",
            "height_cm": 165,
            "birth_date": birth_date,
            "activity_level": "light",
            "goal": "maintain",
        },
    )
    await client.post(
        "/api/measurements", json={"measured_on": date.today().isoformat(), "weight_kg": 60}
    )

    resp = await client.get("/api/calc/targets")
    assert resp.status_code == 200
    body = resp.json()

    age_years = (date.today() - date(1990, 6, 15)).days / 365.25
    bmr = formulas.bmr_mifflin("female", 60, 165, age_years)
    tdee_value = formulas.tdee(bmr, "light")
    kcal, _ = formulas.calorie_target(tdee_value, "maintain", 0.5, bmr, "female")
    protein_g, fat_g, carbs_g, _ = formulas.macro_targets(60, kcal, "maintain")

    assert body["kcal"] == pytest.approx(round(kcal, 1), abs=0.2)
    assert body["protein_g"] == pytest.approx(round(protein_g, 1), abs=0.2)
    assert body["fat_g"] == pytest.approx(round(fat_g, 1), abs=0.2)
    assert body["carbs_g"] == pytest.approx(round(carbs_g, 1), abs=0.2)
    assert body["source"] == "formula"


async def test_calc_targets_r6_safety_floor_cannot_be_bypassed_from_api(registered_client):
    """R6: incluso con la tasa de pérdida máxima permitida por la API
    (1.5 kg/semana), el objetivo nunca baja del suelo de seguridad — y no
    existe ningún parámetro en la API para desactivar este comportamiento."""
    client, _ = registered_client
    await client.put(
        "/api/profile",
        json={
            "sex": "female",
            "height_cm": 150,
            "birth_date": "1955-01-01",
            "activity_level": "sedentary",
            "goal": "lose",
            "goal_rate_kg_week": 1.5,  # máximo permitido por el Field(le=1.5)
        },
    )
    await client.post(
        "/api/measurements", json={"measured_on": date.today().isoformat(), "weight_kg": 50}
    )

    resp = await client.get("/api/calc/targets")
    assert resp.status_code == 200
    body = resp.json()

    assert body["kcal"] == pytest.approx(1200.0)
    assert "TARGET_RAISED_TO_SAFETY_FLOOR" in body["warnings"]


async def test_profile_rejects_rate_above_api_maximum(registered_client):
    """No hay forma de pedir una tasa de pérdida mayor a la permitida —
    ninguna vía en la API para saltarse el suelo de seguridad manualmente."""
    client, _ = registered_client
    resp = await client.put("/api/profile", json={"goal_rate_kg_week": 3.0})
    assert resp.status_code == 422


# --- Fase 4/7: fórmulas alternativas, métodos de grasa y objetivos unificados -------------------

import pytest  # noqa: E402


async def _profile_and_weight(client, **profile):
    payload = {"sex": "male", "birth_date": "1995-01-01", "height_cm": 180, "meals_per_day": 3}
    await client.put("/api/profile", json={**payload, **profile})
    await client.post("/api/measurements", json={"measured_on": "2026-01-10", "weight_kg": 80})


async def test_bmr_supports_harris_benedict(registered_client):
    client, _ = registered_client
    await _profile_and_weight(client)
    resp = await client.post("/api/calc/bmr", json={"formula": "harris"})
    assert resp.status_code == 200
    assert resp.json()["formula_used"] == "harris"
    from datetime import date

    age = (date.today() - date(1995, 1, 1)).days / 365.25
    expected = 88.362 + 13.397 * 80 + 4.799 * 180 - 5.677 * age
    assert resp.json()["bmr"] == pytest.approx(expected, abs=0.1)


async def test_targets_honor_the_bmr_formula_chosen_in_the_profile(registered_client):
    client, _ = registered_client
    await _profile_and_weight(client, bmr_formula="harris")
    targets = (await client.get("/api/calc/targets")).json()
    bmr = (await client.post("/api/calc/bmr", json={})).json()
    assert targets["bmr_formula"] == "harris"
    assert bmr["formula_used"] == "harris"

    await client.put("/api/profile", json={"bmr_formula": "mifflin"})
    mifflin_targets = (await client.get("/api/calc/targets")).json()
    assert mifflin_targets["bmr_formula"] == "mifflin"
    assert mifflin_targets["kcal"] != targets["kcal"]


async def test_targets_fall_back_to_mifflin_when_katch_has_no_body_fat(registered_client):
    client, _ = registered_client
    await _profile_and_weight(client, bmr_formula="katch")
    targets = (await client.get("/api/calc/targets")).json()
    assert targets["bmr_formula"] == "mifflin"
    assert "BMR_FORMULA_FALLBACK_MIFFLIN" in targets["warnings"]


async def test_targets_use_katch_once_there_is_a_body_fat_measurement(registered_client):
    client, _ = registered_client
    await _profile_and_weight(client, bmr_formula="katch")
    await client.post(
        "/api/measurements",
        json={"measured_on": "2026-01-11", "weight_kg": 80, "body_fat_pct": 15},
    )
    targets = (await client.get("/api/calc/targets")).json()
    assert targets["bmr_formula"] == "katch"
    assert "BMR_FORMULA_FALLBACK_MIFFLIN" not in targets["warnings"]


async def test_a_generated_plan_starts_from_the_same_targets_the_user_sees(
    registered_client, diet_candidates
):
    client, _ = registered_client
    await _profile_and_weight(client, bmr_formula="harris")
    targets = (await client.get("/api/calc/targets")).json()

    plan = (await client.post("/api/diet-plans/generate", json={"num_days": 1})).json()

    assert plan["target_kcal"] == targets["kcal"]
    assert plan["target_protein_g"] == targets["protein_g"]


@pytest.mark.parametrize(
    ("method", "body", "expected"),
    [
        (
            "jackson3",
            {"age_years": 30, "chest_mm": 10, "abdomen_mm": 20, "thigh_mm": 15},
            13.6,
        ),
        (
            "durnin",
            {
                "age_years": 25,
                "biceps_mm": 6,
                "triceps_mm": 10,
                "subscapular_mm": 12,
                "suprailiac_mm": 14,
            },
            16.8,
        ),
        ("deurenberg", {"age_years": 30, "weight_kg": 77.76, "height_cm": 180}, 19.5),
    ],
)
async def test_body_fat_by_skinfolds_or_bmi(registered_client, method, body, expected):
    client, _ = registered_client
    await client.put("/api/profile", json={"sex": "male"})
    resp = await client.post(
        "/api/calc/body-fat", json={"method": method, "height_cm": 180, **body}
    )
    assert resp.status_code == 200
    assert resp.json()["method"] == method
    assert resp.json()["body_fat_pct"] == pytest.approx(expected, abs=0.1)


async def test_body_fat_by_skinfolds_names_the_missing_sites(registered_client):
    client, _ = registered_client
    await client.put("/api/profile", json={"sex": "male"})
    resp = await client.post(
        "/api/calc/body-fat",
        json={"method": "jackson7", "age_years": 30, "height_cm": 180, "chest_mm": 10},
    )
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "MISSING_SKINFOLDS"
    assert "abdomen_mm" in resp.json()["error"]["details"]["missing"]


async def test_body_fat_navy_still_needs_neck_and_waist(registered_client):
    client, _ = registered_client
    await client.put("/api/profile", json={"sex": "male"})
    resp = await client.post("/api/calc/body-fat", json={"method": "navy", "height_cm": 180})
    assert resp.status_code == 422


async def test_body_fat_also_returns_bmi_and_waist_to_height(registered_client):
    client, _ = registered_client
    await client.put("/api/profile", json={"sex": "male"})
    resp = await client.post(
        "/api/calc/body-fat",
        json={
            "method": "navy",
            "height_cm": 180,
            "weight_kg": 90,
            "neck_cm": 40,
            "waist_cm": 100,
        },
    )
    body = resp.json()
    assert body["bmi"] == pytest.approx(27.8, abs=0.05)
    assert body["whtr"] == pytest.approx(0.56)
    assert "WAIST_TO_HEIGHT_RISK" in body["warnings"]
