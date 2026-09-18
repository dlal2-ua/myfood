"""Panel de privacidad — ver, exportar y borrar los propios datos (Fase 7,
documento 2 sección 17, RGPD art. 15/17/20)."""

from datetime import date

import pytest
from sqlalchemy import text

pytestmark = pytest.mark.asyncio

_REGISTERED_PASSWORD = "correcthorse123"  # ver conftest.py::registered_client


async def _seed_some_data(client, test_food):
    await client.put(
        "/api/profile",
        json={"sex": "female", "height_cm": 168, "birth_date": "1992-03-20"},
    )
    await client.post(
        "/api/measurements", json={"measured_on": date.today().isoformat(), "weight_kg": 61.5}
    )
    await client.post(
        "/api/log/food",
        json={
            "log_date": date.today().isoformat(),
            "meal_type": "lunch",
            "food_id": str(test_food),
            "grams": 150,
        },
    )
    await client.post("/api/pantry", json={"food_id": str(test_food), "quantity_g": 200})


async def test_summary_reflects_real_counts(registered_client, test_food):
    client, _ = registered_client
    await _seed_some_data(client, test_food)

    resp = await client.get("/api/privacy/summary")
    assert resp.status_code == 200
    body = resp.json()
    assert body["measurements_count"] == 1
    assert body["food_log_entries"] == 1
    assert body["supplements_count"] == 0
    assert "account_created_at" in body


async def test_export_contains_full_history_and_decrypts_health_data(
    registered_client, test_food
):
    """R4: sex/height_cm/birth_date (perfil) y weight_kg (medidas) están
    cifrados en reposo — el export tiene que devolverlos en claro, no como
    el texto cifrado ilegible que hay en la columna."""
    client, _ = registered_client
    await _seed_some_data(client, test_food)

    resp = await client.get("/api/privacy/export")
    assert resp.status_code == 200
    assert "attachment" in resp.headers["content-disposition"]
    body = resp.json()

    assert body["profile"]["sex"] == "female"
    assert body["profile"]["height_cm"] == 168.0
    assert body["profile"]["birth_date"] == "1992-03-20"
    assert len(body["body_measurements"]) == 1
    assert body["body_measurements"][0]["weight_kg"] == 61.5
    assert len(body["food_log"]) == 1
    assert len(body["pantry_items"]) == 1
    assert body["account"]["email"]

    # Nunca debe salir el hash de la contraseña.
    assert "password_hash" not in resp.text


async def test_delete_account_wrong_password_is_401(registered_client):
    client, _ = registered_client
    resp = await client.post("/api/privacy/delete-account", json={"password": "incorrecta"})
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "INVALID_CREDENTIALS"

    # La cuenta sigue intacta — el perfil se puede seguir consultando.
    still_there = await client.get("/api/profile")
    assert still_there.status_code == 200


async def test_delete_account_removes_user_and_cascades(
    registered_client, superuser_conn, test_food
):
    client, user_id = registered_client
    await _seed_some_data(client, test_food)

    resp = await client.post(
        "/api/privacy/delete-account", json={"password": _REGISTERED_PASSWORD}
    )
    assert resp.status_code == 204

    # La sesión queda invalidada — ya no se puede usar el mismo cliente autenticado.
    after = await client.get("/api/profile")
    assert after.status_code == 401

    # Y de verdad ha desaparecido de la base de datos (no solo la sesión).
    row = (
        await superuser_conn.execute(
            text("SELECT 1 FROM users WHERE id = :id"), {"id": str(user_id)}
        )
    ).first()
    assert row is None
    measurements = (
        await superuser_conn.execute(
            text("SELECT 1 FROM body_measurements WHERE user_id = :id"), {"id": str(user_id)}
        )
    ).first()
    assert measurements is None
