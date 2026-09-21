"""GET /foods/search con filtros (supermercado, tipo de alimento, nutrición), ordenación y
facetas, contra Meilisearch real. Indexa alimentos de prueba con un texto único para no mezclarse
con lo que hayan dejado otros tests en el índice de pruebas."""

import asyncio
import uuid

import httpx
import pytest
import pytest_asyncio

from myfood.config import get_settings

settings = get_settings()
pytestmark = pytest.mark.asyncio


def _headers() -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if settings.meili_master_key:
        headers["Authorization"] = f"Bearer {settings.meili_master_key}"
    return headers


async def _wait(client: httpx.AsyncClient, response: httpx.Response) -> None:
    uid = response.json()["taskUid"]
    for _ in range(100):
        if (await client.get(f"/tasks/{uid}")).json()["status"] in ("succeeded", "failed"):
            return
        await asyncio.sleep(0.1)


def _doc(token: str, name: str, **over) -> dict:
    doc = {
        "id": str(uuid.uuid4()),
        "name_es": f"{token} {name}",
        "name_en": None,
        "brand": None,
        "kind": "generic",
        "category": None,
        "quality_rank": 4,
        "source": "bedca",
        "kcal_100g": 100.0,
        "protein_100g": 5.0,
        "fat_100g": 1.0,
        "carbs_100g": 10.0,
        "has_image": False,
        "supermarket": None,
        "food_group": None,
        "nutrition_tags": [],
    }
    doc.update(over)
    return doc


@pytest_asyncio.fixture
async def catalog():
    token = f"zzq{uuid.uuid4().hex[:8]}"
    docs = {
        "chicken": _doc(token, "pollo", food_group="meat", protein_100g=23.0, kcal_100g=110.0,
                        nutrition_tags=["high_protein", "low_carb"]),
        "mercadona_yogurt": _doc(token, "yogur hacendado", kind="branded", source="off",
                                 brand="Hacendado, MERCADONA", supermarket="mercadona",
                                 food_group="dairy", protein_100g=4.0,
                                 nutrition_tags=["low_sugar", "nutriscore_ab"]),
        "lidl_yogurt": _doc(token, "yogur milbona", kind="branded", source="off",
                            brand="Milbona, Lidl", supermarket="lidl", food_group="dairy",
                            protein_100g=10.0, nutrition_tags=["high_protein"]),
        "usda_chicken": _doc(token, "chicken breast", source="usda_sr", quality_rank=2,
                             food_group="meat", protein_100g=20.0,
                             nutrition_tags=["high_protein"]),
    }
    async with httpx.AsyncClient(base_url=settings.meili_url, headers=_headers(), timeout=15) as c:
        index = f"/indexes/{settings.meili_index}"
        # Estos tests reconfiguran el índice: nunca sobre un catálogo real. En CI y con
        # `scripts/test-api.sh` el índice está vacío o no existe.
        stats = await c.get(f"{index}/stats")
        if stats.status_code == 200 and stats.json()["numberOfDocuments"] >= 500:
            pytest.skip("El índice tiene un catálogo real: solo corren en uno de pruebas.")
        await _wait(c, await c.patch(f"{index}/settings", json={
            "filterableAttributes": ["kind", "category", "quality_rank", "has_image", "source",
                                     "supermarket", "food_group", "nutrition_tags"],
            "sortableAttributes": ["quality_rank", "kcal_100g", "protein_100g"],
        }))
        await _wait(c, await c.post(f"{index}/documents?primaryKey=id", json=list(docs.values())))
        yield token, docs
        await c.post(f"{index}/documents/delete-batch", json=[d["id"] for d in docs.values()])


async def _search(client, **params):
    resp = await client.get("/api/foods/search", params=params)
    assert resp.status_code == 200, resp.text
    return resp.json()


def _ids(body) -> set[str]:
    return {item["id"] for item in body["items"]}


async def test_supermarket_options_add_up(registered_client, catalog):
    client, _ = registered_client
    token, docs = catalog
    body = await _search(client, q=token, supermarket=["mercadona", "lidl"])
    assert _ids(body) == {docs["mercadona_yogurt"]["id"], docs["lidl_yogurt"]["id"]}


async def test_food_type_and_nutrition_are_combined(registered_client, catalog):
    client, _ = registered_client
    token, docs = catalog
    body = await _search(client, q=token, food_type=["dairy"], nutrition=["high_protein"])
    assert _ids(body) == {docs["lidl_yogurt"]["id"]}


async def test_several_nutrition_tags_must_all_apply(registered_client, catalog):
    client, _ = registered_client
    token, docs = catalog
    body = await _search(client, q=token, nutrition=["high_protein", "low_carb"])
    assert _ids(body) == {docs["chicken"]["id"]}


async def test_browsing_without_text_only_shows_spanish_named_sources(registered_client, catalog):
    client, _ = registered_client
    _, docs = catalog
    body = await _search(client, nutrition=["high_protein"], limit=100)
    ids = _ids(body)
    assert {docs["chicken"]["id"], docs["lidl_yogurt"]["id"]} <= ids
    assert docs["usda_chicken"]["id"] not in ids


async def test_typing_searches_every_source(registered_client, catalog):
    client, _ = registered_client
    token, docs = catalog
    body = await _search(client, q=token)
    assert docs["usda_chicken"]["id"] in _ids(body)


async def test_sort_by_protein(registered_client, catalog):
    client, _ = registered_client
    token, docs = catalog
    body = await _search(client, q=token, sort="protein_desc")
    order = [item["id"] for item in body["items"]]
    assert order == [
        docs["chicken"]["id"],
        docs["usda_chicken"]["id"],
        docs["lidl_yogurt"]["id"],
        docs["mercadona_yogurt"]["id"],
    ]


async def test_items_carry_readable_supermarket_and_type(registered_client, catalog):
    client, _ = registered_client
    token, docs = catalog
    body = await _search(client, q=token, supermarket=["mercadona"])
    item = body["items"][0]
    assert item["supermarket"] == "Mercadona"
    assert item["food_type"] == "Lácteos"
    assert item["fat_100g"] == 1.0 and item["carbs_100g"] == 10.0


async def test_facets_count_each_option_without_hiding_the_others(registered_client, catalog):
    client, _ = registered_client
    token, _ = catalog
    body = await _search(client, q=token, food_type=["dairy"], facets="true")
    facets = body["facets"]
    counts = lambda key: {o["code"]: o["count"] for o in facets[key]}  # noqa: E731
    # Tipo de alimento: su propia selección no esconde las demás opciones.
    assert counts("food_type")["meat"] == 2 and counts("food_type")["dairy"] == 2
    # Supermercado: se cuenta dentro de lo que ya se eligió (lácteos).
    assert counts("supermarket")["mercadona"] == 1 and counts("supermarket")["lidl"] == 1
    assert counts("supermarket")["aldi"] == 0
    # Nutrición: cada etiqueta cuenta lo que quedaría al añadirla.
    assert counts("nutrition")["high_protein"] == 1 and counts("nutrition")["low_sugar"] == 1
    # Todas las opciones de la taxonomía aparecen aunque tengan 0, con su etiqueta.
    assert {o["code"] for o in facets["nutrition"]} >= {"high_protein", "low_fat", "sugar_free"}
    assert all(o["label"] for key in facets for o in facets[key])
    assert next(o for o in facets["nutrition"] if o["code"] == "high_protein")["description"]


async def test_facets_are_not_computed_unless_asked(registered_client, catalog):
    client, _ = registered_client
    token, _ = catalog
    assert (await _search(client, q=token))["facets"] is None


async def test_unknown_filter_values_are_rejected(registered_client):
    client, _ = registered_client
    bad = ({"supermarket": "carrefoo"}, {"food_type": "cheese; DROP"}, {"nutrition": 'x" OR 1=1'})
    for params in bad:
        resp = await client.get("/api/foods/search", params={"q": "a", **params})
        assert resp.status_code == 422
        assert resp.json()["error"]["code"] == "INVALID_FILTER"


async def test_empty_text_is_allowed_now(registered_client, catalog):
    client, _ = registered_client
    resp = await client.get("/api/foods/search", params={"nutrition": "low_fat"})
    assert resp.status_code == 200
