"""Tests puros de `off_client.py` (documento 2, sección 11.2) — mismo estilo
que `etl/tests/test_off.py`: `parse_product` sin I/O, `fetch_product` con un
`httpx.MockTransport` inyectado (nunca se toca la red real)."""

import httpx

from myfood.off_client import fetch_product, parse_product


def test_parse_product_maps_macros():
    raw = {
        "code": "8410297121104",
        "product_name": "Nata Montada Azucarada",
        "nutriments": {
            "energy-kcal_100g": 306,
            "proteins_100g": 2.4,
            "fat_100g": 28,
            "carbohydrates_100g": 11,
            "salt_100g": 0.08,
        },
        "nutriscore_grade": "d",
        "nova_group": 4,
    }
    result = parse_product(raw, "8410297121104")
    assert result is not None
    assert result.name_es == "Nata Montada Azucarada"
    assert result.kcal_100g == 306
    assert result.protein_100g == 2.4
    assert result.nutriscore_grade == "d"
    assert result.nova_group == 4


def test_parse_product_missing_name_returns_none():
    raw = {"code": "123", "nutriments": {"energy-kcal_100g": 100}}
    assert parse_product(raw, "123") is None


def test_parse_product_missing_kcal_returns_none():
    raw = {"code": "123", "product_name": "Sin nutrientes", "nutriments": {}}
    assert parse_product(raw, "123") is None


def test_parse_product_kcal_out_of_range_returns_none():
    raw = {
        "code": "123",
        "product_name": "Imposible",
        "nutriments": {"energy-kcal_100g": 950},
    }
    assert parse_product(raw, "123") is None


def test_parse_product_macros_exceeding_100g_returns_none():
    raw = {
        "code": "123",
        "product_name": "Macros imposibles",
        "nutriments": {
            "energy-kcal_100g": 400,
            "proteins_100g": 60,
            "fat_100g": 30,
            "carbohydrates_100g": 30,
        },
    }
    assert parse_product(raw, "123") is None


def test_parse_product_rejects_garbage_grade():
    raw = {
        "code": "123",
        "product_name": "Con nota desconocida",
        "nutriscore_grade": "unknown",
        "nutriments": {"energy-kcal_100g": 100},
    }
    result = parse_product(raw, "123")
    assert result is not None
    assert result.nutriscore_grade is None


async def test_fetch_product_returns_none_when_not_found():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"status": 0, "status_verbose": "product not found"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    result = await fetch_product("0000000000000", client=client)
    assert result is None


async def test_fetch_product_parses_real_shaped_response():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "status": 1,
                "product": {
                    "code": "8436547770137",
                    "product_name": "Kefir",
                    "nutriments": {"energy-kcal_100g": 74, "proteins_100g": 3.9},
                },
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    result = await fetch_product("8436547770137", client=client)
    assert result is not None
    assert result.kcal_100g == 74


async def test_fetch_product_returns_none_on_http_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    result = await fetch_product("123", client=client)
    assert result is None
