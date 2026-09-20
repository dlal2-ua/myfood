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


async def test_export_contains_full_history_and_decrypts_health_data(registered_client, test_food):
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

    resp = await client.post("/api/privacy/delete-account", json={"password": _REGISTERED_PASSWORD})
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


# --- Exportación completa: planes con contenido, restricciones, ayuno, chat, stock y CSV --------

import csv  # noqa: E402
import io  # noqa: E402
import json  # noqa: E402
import zipfile  # noqa: E402


async def _seed_everything(client, test_food, diet_candidates):
    await client.put(
        "/api/profile",
        json={
            "sex": "male",
            "birth_date": "1992-03-20",
            "height_cm": 180,
            "meals_per_day": 3,
        },
    )
    await client.post(
        "/api/measurements", json={"measured_on": date.today().isoformat(), "weight_kg": 80}
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
    await client.post("/api/restrictions", json={"kind": "allergen", "allergen_code": "gluten"})
    await client.post("/api/fasting/start", json={"target_hours": 16})
    supplement = await client.post(
        "/api/supplements",
        json={"name": "Creatina", "type": "sports", "dose_amount": 5, "dose_unit": "g"},
    )
    assert supplement.status_code == 201, supplement.text
    restock = await client.post(
        f"/api/supplements/{supplement.json()['id']}/restock", json={"doses_added": 30}
    )
    assert restock.status_code == 200, restock.text
    return (await client.post("/api/diet-plans/generate", json={"num_days": 1})).json()


async def test_the_json_export_includes_plan_contents_restrictions_fasting_and_more(
    registered_client, test_food, diet_candidates, superuser_conn
):
    client, user_id = registered_client
    plan = await _seed_everything(client, test_food, diet_candidates)
    await superuser_conn.execute(
        text(
            "INSERT INTO chat_messages (user_id, role, content, source) "
            "VALUES (:u, 'user', 'hola', 'text')"
        ),
        {"u": str(user_id)},
    )
    await superuser_conn.commit()

    body = (await client.get("/api/privacy/export")).json()

    exported_plan = next(p for p in body["diet_plans"] if p["id"] == plan["id"])
    assert len(exported_plan["days"]) == 1
    meals = exported_plan["days"][0]["meals"]
    assert {m["meal_type"] for m in meals} == {"breakfast", "lunch", "dinner"}
    assert all(m["items"] for m in meals)
    assert body["restrictions"][0]["allergen_code"] == "gluten"
    assert len(body["fasting_windows"]) == 1
    assert body["supplement_stock"][0]["doses_remaining"] == 30
    assert [m["content"] for m in body["chat_messages"]] == ["hola"]


async def test_the_zip_export_has_the_json_and_a_csv_per_table_with_rows(
    registered_client, test_food, diet_candidates
):
    client, _ = registered_client
    await _seed_everything(client, test_food, diet_candidates)

    resp = await client.get("/api/privacy/export", params={"format": "zip"})

    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/zip"
    assert resp.headers["content-disposition"].endswith('.zip"')
    with zipfile.ZipFile(io.BytesIO(resp.content)) as archive:
        names = set(archive.namelist())
        assert {
            "LEEME.txt",
            "myfood-export.json",
            "csv/food_log.csv",
            "csv/diet_plans.csv",
        } <= names
        assert "csv/fasting_windows.csv" in names
        # las tablas sin filas no generan hoja vacía
        assert "csv/pantry_items.csv" not in names
        exported = json.loads(archive.read("myfood-export.json"))
        rows = list(csv.DictReader(io.StringIO(archive.read("csv/food_log.csv").decode())))
        plan_rows = list(csv.DictReader(io.StringIO(archive.read("csv/diet_plans.csv").decode())))
    assert exported["account"]["email"]
    assert len(rows) == 1
    assert rows[0]["grams"] == "150.0" or float(rows[0]["grams"]) == 150
    assert rows[0]["meal_type"] == "lunch"
    assert json.loads(plan_rows[0]["days"])[0]["meals"]


async def test_no_export_format_leaks_credentials(registered_client, test_food, diet_candidates):
    client, _ = registered_client
    await _seed_everything(client, test_food, diet_candidates)
    as_json = (await client.get("/api/privacy/export")).text
    with zipfile.ZipFile(
        io.BytesIO((await client.get("/api/privacy/export", params={"format": "zip"})).content)
    ) as archive:
        as_zip = "".join(archive.read(name).decode() for name in archive.namelist())
    for text_ in (as_json, as_zip):
        assert "password_hash" not in text_
        assert "push_subscriptions" not in text_


async def test_an_unknown_export_format_is_rejected(registered_client):
    client, _ = registered_client
    assert (await client.get("/api/privacy/export", params={"format": "xml"})).status_code == 422
