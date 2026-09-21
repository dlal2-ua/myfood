"""GET /foods/suggestions: qué se enseña al entrar en «Alimentos»."""

from datetime import date

import pytest

pytestmark = pytest.mark.asyncio


async def _suggest(client, **params):
    resp = await client.get("/api/foods/suggestions", params=params)
    assert resp.status_code == 200, resp.text
    return {section["key"]: section for section in resp.json()["sections"]}


async def _complete_profile(client, weight_kg=70):
    await client.put(
        "/api/profile",
        json={"sex": "female", "birth_date": "1994-06-12", "height_cm": 168, "meals_per_day": 3,
              "activity_level": "moderate", "goal": "maintain"},
    )
    await client.post(
        "/api/measurements", json={"measured_on": date.today().isoformat(), "weight_kg": weight_kg}
    )


async def test_requires_authentication():
    from httpx import ASGITransport, AsyncClient

    from myfood.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://test") as client:
        assert (await client.get("/api/foods/suggestions")).status_code == 401


async def test_rejects_an_unknown_meal(registered_client):
    client, _ = registered_client
    resp = await client.get("/api/foods/suggestions", params={"meal_type": "elevenses"})
    assert resp.status_code == 422


async def test_a_new_user_gets_staples_for_the_meal(registered_client, diet_candidates):
    client, _ = registered_client
    sections = await _suggest(client, meal_type="breakfast")
    assert list(sections) == ["staples"]
    staples = sections["staples"]
    assert staples["title"] == "Básicos para el desayuno"
    names = " ".join(item["name_es"] for item in staples["items"])
    assert 0 < len(staples["items"]) <= 10
    # Un desayuno: nada de carne ni de pescado.
    assert not any(word in names for word in ("Pollo", "Ternera", "Merluza", "Salmón"))
    assert all(item["image_url"] for item in staples["items"])


async def test_no_meal_means_no_staples(registered_client, diet_candidates):
    client, _ = registered_client
    assert "staples" not in await _suggest(client)


async def test_staples_never_include_a_banned_food(registered_client, diet_candidates):
    client, _ = registered_client
    first = (await _suggest(client, meal_type="lunch"))["staples"]["items"]
    banned = first[0]["id"]
    resp = await client.post(
        "/api/restrictions", json={"kind": "banned_food", "food_id": banned}
    )
    assert resp.status_code == 201
    again = (await _suggest(client, meal_type="lunch"))["staples"]["items"]
    assert banned not in [item["id"] for item in again]


async def test_history_sections_come_first_without_repeating_a_food(
    registered_client, diet_candidates
):
    client, _ = registered_client
    # Índices de `diet_candidates`: 0 pollo, 2 huevo, 18 yogur, 20 plátano.
    chicken, egg, yogurt, banana = (str(diet_candidates[i]) for i in (0, 2, 18, 20))
    await client.post("/api/favorites", json={"food_id": banana})
    today = date.today().isoformat()
    for food_id in (yogurt, yogurt, chicken):  # el yogur dos veces, el pollo una
        await client.post(
            "/api/log/food",
            json={"log_date": today, "meal_type": "breakfast", "food_id": food_id, "grams": 100},
        )
    await client.post("/api/pantry", json={"food_id": egg, "quantity_g": 300})

    sections = await _suggest(client, meal_type="breakfast", date=today)
    order = list(sections)
    # Primero lo del usuario y lo que tiene en casa; los básicos, al final.
    assert order[:4] == ["favorites", "frequent", "recent", "pantry"]
    assert order[-1] == "staples"
    assert [i["id"] for i in sections["favorites"]["items"]] == [banana]
    # Habitual = apuntado varias veces; lo apuntado una sola vez sale en «recientes».
    assert [i["id"] for i in sections["frequent"]["items"]] == [yogurt]
    assert [i["id"] for i in sections["recent"]["items"]] == [chicken]
    assert [i["id"] for i in sections["pantry"]["items"]] == [egg]
    shown = [item["id"] for s in sections.values() for item in s["items"]]
    assert len(shown) == len(set(shown))


async def test_protein_gap_suggests_protein_rich_foods_until_it_is_covered(
    registered_client, diet_candidates
):
    client, _ = registered_client
    await _complete_profile(client)
    today = date.today().isoformat()

    sections = await _suggest(client, date=today)
    protein = sections["protein"]
    assert protein["title"].startswith("Hoy te faltan unos ")
    assert protein["items"] and all(item["protein_100g"] >= 15 for item in protein["items"])

    await client.post(
        "/api/log/food",
        json={
            "log_date": today,
            "meal_type": "lunch",
            "food_id": str(diet_candidates[0]),
            "grams": 1500,
        },
    )
    assert "protein" not in await _suggest(client, date=today)


async def test_without_a_profile_there_is_no_protein_section_but_no_error(
    registered_client, diet_candidates
):
    client, _ = registered_client
    assert "protein" not in await _suggest(client, meal_type="dinner")


async def test_protein_suggestions_put_lean_sources_before_fatty_ones(
    registered_client, diet_candidates
):
    client, _ = registered_client
    await _complete_profile(client)
    items = (await _suggest(client, date=date.today().isoformat()))["protein"]["items"]
    shares = [i["protein_100g"] * 4 / i["kcal_100g"] for i in items]
    assert len(items) >= 2
    # Los grupos se reparten (máx. 3 por grupo) pero, dentro de lo elegido, la proteína
    # magra no va detrás de los frutos secos: la primera no es menos magra que la última.
    assert shares[0] >= shares[-1]
    assert "Nueces" not in items[0]["name_es"]
