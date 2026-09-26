"""Candidatos de un plan, alternativas del mismo grupo con los gramos ajustados y muestreo del pool
de cada día (`domain/food_candidates.py`)."""

import random
import uuid

import pytest
import pytest_asyncio
from sqlalchemy import text

from myfood.db.session import AdminSessionLocal
from myfood.domain import food_groups as fg
from myfood.domain.diet_engine import CandidateFood
from myfood.domain.food_candidates import (
    PLAN_SOURCES,
    _is_the_same_food,
    _significant_words,
    find_alternatives,
    sample_day_pool,
    select_candidates,
)

pytestmark = pytest.mark.asyncio


async def _insert(
    conn, name, kcal, protein, fat, carbs, *, source="bedca", category=None, vec=None
):
    food_id = uuid.uuid4()
    await conn.execute(
        text(
            "INSERT INTO foods (id, kind, source, source_id, license, name_es, category, "
            "quality_rank) VALUES (:id, 'generic', :source, :sid, 'CC0', :name, :category, 4)"
        ),
        {
            "id": str(food_id),
            "sid": str(food_id),
            "source": source,
            "name": name,
            "category": category,
        },
    )
    await conn.execute(
        text(
            "INSERT INTO food_nutrients (food_id, kcal_100g, protein_100g, fat_100g, carbs_100g) "
            "VALUES (:id, :kcal, :protein, :fat, :carbs)"
        ),
        {"id": str(food_id), "kcal": kcal, "protein": protein, "fat": fat, "carbs": carbs},
    )
    if vec is not None:
        literal = "[" + ",".join(str(v) for v in vec) + "]"
        await conn.execute(
            text(f"INSERT INTO food_vectors (food_id, vec) VALUES (:id, '{literal}'::vector)"),
            {"id": str(food_id)},
        )
    return food_id


async def _cleanup(conn, ids):
    for table in ("food_vectors", "food_nutrients", "food_allergens"):
        await conn.execute(text(f"DELETE FROM {table} WHERE food_id = ANY(:ids)"), {"ids": ids})
    await conn.execute(text("DELETE FROM foods WHERE id = ANY(:ids)"), {"ids": ids})
    await conn.commit()


@pytest_asyncio.fixture
async def catalog(superuser_conn):
    """Un pollo con vecinos de todos los tipos, con vectores sintéticos para que el orden por
    distancia sea el que interesa a cada test (mismo truco que `test_foods_similar.py`)."""
    conn = superuser_conn
    ids = {
        "pollo": await _insert(
            conn, "Pechuga de pollo (alt)", 165, 31, 3.6, 0, vec=[0.5, 0.9, 0.1, 0, 0, 0]
        ),
        # el más cercano, pero es un pescado: no es un sustituto de un pollo
        "merluza": await _insert(
            conn, "Merluza, cruda (alt)", 71, 16, 0.8, 0, vec=[0.5, 0.9, 0.1, 0, 0, 0.01]
        ),
        "queso": await _insert(
            conn, "Queso curado (alt)", 390, 26, 32, 1, vec=[0.5, 0.9, 0.1, 0, 0, 0.02]
        ),
        "pavo": await _insert(
            conn, "Pavo, pechuga (alt)", 135, 30, 1.5, 0, vec=[0.5, 0.9, 0.1, 0, 0, 0.03]
        ),
        "ternera": await _insert(
            conn, "Ternera, solomillo (alt)", 156, 28.4, 4.5, 0, vec=[0.5, 0.9, 0.1, 0, 0, 0.04]
        ),
        # carne, pero con tan pocas kcal que igualar las del pollo exigiría comer casi un kilo
        "magra": await _insert(
            conn, "Carne magra imposible (alt)", 40, 8, 0.5, 0, vec=[0.5, 0.9, 0.1, 0, 0, 0.05]
        ),
        # USDA, ya traducido: desde la migración 0021 sí se ofrece como alternativa. Otro
        # alimento de verdad, no otro nombre del pavo: el filtro de duplicados lo tumbaría.
        "usda": await _insert(
            conn,
            "Lomo de cerdo (alt)",
            135,
            30,
            1.5,
            0,
            source="usda_sr",
            vec=[0.5, 0.9, 0.1, 0, 0, 0.06],
        ),
        # Una fuente que NO arma planes: los alimentos de prueba nunca se ofrecen.
        "fuera_del_plan": await _insert(
            conn,
            "Conejo de prueba (alt)",
            136,
            30,
            1.5,
            0,
            source="test",
            vec=[0.5, 0.9, 0.1, 0, 0, 0.065],
        ),
        "pavo_repetido": await _insert(
            conn, "Pavo, pechuga (alt)", 140, 29, 2, 0, vec=[0.5, 0.9, 0.1, 0, 0, 0.07]
        ),
    }
    await conn.commit()
    yield ids
    await _cleanup(conn, [str(i) for i in ids.values()])


async def _alternatives(user_id, catalog, keep="kcal", grams=200.0, limit=10):
    async with AdminSessionLocal() as session:
        return await find_alternatives(
            session, catalog["pollo"], grams, user_id, keep=keep, limit=limit
        )


async def test_alternatives_are_of_the_same_group_and_never_a_fish_or_a_cheese(
    registered_client, catalog
):
    _client, user_id = registered_client
    found = {a.food_id: a for a in await _alternatives(user_id, catalog)}

    assert catalog["merluza"] not in found
    assert catalog["queso"] not in found
    assert catalog["pavo"] in found
    assert catalog["ternera"] in found


async def test_alternatives_come_with_the_grams_that_keep_the_kcal(registered_client, catalog):
    _client, user_id = registered_client
    found = {a.food_id: a for a in await _alternatives(user_id, catalog, grams=200)}

    # 200 g de pollo = 330 kcal -> 330 / 1,35 = 244,4 g de pavo (múltiplo de 5: 245)
    assert found[catalog["pavo"]].grams == 245
    assert found[catalog["ternera"]].grams == 210
    for alternative in found.values():
        original_kcal = 165 * 200 / 100
        assert (
            abs(alternative.kcal_100g * alternative.grams / 100 - original_kcal)
            <= original_kcal * 0.03
        )


async def test_alternatives_can_keep_the_protein_instead(registered_client, catalog):
    _client, user_id = registered_client
    found = {a.food_id: a for a in await _alternatives(user_id, catalog, keep="protein", grams=200)}

    # 200 g de pollo = 62 g de proteína -> 62 / 0,30 = 206,7 g de pavo
    assert found[catalog["pavo"]].grams == 205


async def test_an_alternative_that_would_need_an_absurd_amount_is_not_offered(
    registered_client, catalog
):
    _client, user_id = registered_client
    found = {a.food_id for a in await _alternatives(user_id, catalog)}
    assert catalog["magra"] not in found


async def test_a_source_that_does_not_build_plans_is_not_offered_as_an_alternative(
    registered_client, catalog
):
    _client, user_id = registered_client
    found = {a.food_id for a in await _alternatives(user_id, catalog)}
    assert catalog["fuera_del_plan"] not in found


async def test_usda_is_offered_now_that_its_names_are_in_spanish(registered_client, catalog):
    """Entró en `PLAN_SOURCES` al traducirse (migración 0021). Sin sus 10.171 genéricos, las
    alternativas a un producto de marca eran otras tres marcas del mismo producto: por cercanía
    nutricional, lo más parecido a una pechuga de pollo envasada es otra pechuga envasada."""
    _client, user_id = registered_client
    found = {a.food_id for a in await _alternatives(user_id, catalog)}
    assert catalog["usda"] in found


async def test_two_alternatives_with_the_same_name_are_not_both_offered(registered_client, catalog):
    _client, user_id = registered_client
    names = [a.name_es for a in await _alternatives(user_id, catalog)]
    assert len(names) == len(set(n.lower() for n in names))


async def test_alternatives_never_include_a_food_the_user_cannot_eat(registered_client, catalog):
    client, user_id = registered_client
    await client.post(
        "/api/restrictions", json={"kind": "banned_food", "food_id": str(catalog["pavo"])}
    )
    found = {a.food_id for a in await _alternatives(user_id, catalog)}
    assert catalog["pavo"] not in found
    assert catalog["ternera"] in found


async def test_the_similar_endpoint_returns_adjusted_grams(registered_client, catalog):
    client, _ = registered_client
    resp = await client.get(
        f"/api/foods/{catalog['pollo']}/similar", params={"grams": 200, "keep": "kcal", "limit": 5}
    )
    assert resp.status_code == 200
    by_id = {item["id"]: item for item in resp.json()["items"]}
    assert by_id[str(catalog["pavo"])]["grams"] == 245
    assert str(catalog["merluza"]) not in by_id


async def test_the_similar_endpoint_validates_keep(registered_client, catalog):
    client, _ = registered_client
    resp = await client.get(f"/api/foods/{catalog['pollo']}/similar", params={"keep": "sodium"})
    assert resp.status_code == 422


# --- select_candidates -------------------------------------------------------------------------


@pytest_asyncio.fixture
async def pool_foods(superuser_conn):
    conn = superuser_conn
    ids = {
        "pollo": await _insert(conn, "Pollo, pechuga (pool)", 165, 31, 3.6, 0),
        "oliva": await _insert(conn, "Aceite de oliva virgen extra (pool)", 884, 0, 100, 0),
        "nueces": await _insert(conn, "Nueces (pool)", 654, 15, 65, 7),
        "galletas": await _insert(conn, "Galletas María (pool)", 430, 7, 10, 75),
        "zumo": await _insert(conn, "Zumo de naranja (pool)", 45, 0.7, 0.2, 10),
        "usda": await _insert(
            conn, "Pechuga de pollo, cruda (pool)", 165, 31, 3.6, 0, source="usda_sr"
        ),
        "dato_malo": await _insert(conn, "Pollo con datos malos (pool)", 6, 55, 36, 0),
        "azucar_puro": await _insert(conn, "Arroz que es todo almidón (pool)", 400, 0, 0, 100),
    }
    await conn.commit()
    yield ids
    await _cleanup(conn, [str(i) for i in ids.values()])


async def _pool(user_id):
    async with AdminSessionLocal() as session:
        return {c.id: c for c in await select_candidates(session, user_id)}


async def test_the_pool_uses_only_spanish_named_sources(registered_client, pool_foods):
    """Las cinco fuentes del catálogo tienen ya el nombre en español; las de prueba y las altas
    manuales del usuario no arman planes."""
    _client, user_id = registered_client
    assert set(PLAN_SOURCES) == {"bedca", "off", "usda_foundation", "usda_sr", "ciqual"}
    pool = await _pool(user_id)
    assert str(pool_foods["usda"]) in pool
    assert str(pool_foods["pollo"]) in pool


async def test_the_pool_leaves_out_what_is_not_food_for_a_meal(registered_client, pool_foods):
    _client, user_id = registered_client
    pool = await _pool(user_id)
    assert str(pool_foods["galletas"]) not in pool  # dulce
    assert str(pool_foods["zumo"]) not in pool  # bebida


async def test_the_pool_leaves_out_data_that_does_not_add_up(registered_client, pool_foods):
    _client, user_id = registered_client
    pool = await _pool(user_id)
    assert str(pool_foods["dato_malo"]) not in pool  # 6 kcal con 55 g de proteína y 36 de grasa
    assert str(pool_foods["azucar_puro"]) not in pool  # >90 % de las kcal de un solo macro


async def test_cooking_fats_and_nuts_are_allowed_despite_their_energy_density(
    registered_client, pool_foods
):
    _client, user_id = registered_client
    pool = await _pool(user_id)
    assert pool[str(pool_foods["oliva"])].group == fg.OIL_FAT
    assert pool[str(pool_foods["oliva"])].max_grams == 20
    assert pool[str(pool_foods["nueces"])].group == fg.NUTS


async def test_candidates_carry_their_group_bounds_source_and_staple_flag(
    registered_client, pool_foods
):
    _client, user_id = registered_client
    pollo = (await _pool(user_id))[str(pool_foods["pollo"])]
    assert pollo.group == fg.MEAT
    assert (pollo.min_grams, pollo.max_grams) == (100, 220)
    assert pollo.source == "bedca"
    assert pollo.staple is True


async def test_an_allergen_keeps_a_tagged_food_out_of_the_pool(
    registered_client, pool_foods, superuser_conn
):
    client, user_id = registered_client
    await superuser_conn.execute(
        text("INSERT INTO food_allergens (food_id, allergen_code) VALUES (:id, 'gluten')"),
        {"id": str(pool_foods["pollo"])},
    )
    await superuser_conn.commit()
    await client.post("/api/restrictions", json={"kind": "allergen", "allergen_code": "gluten"})
    assert str(pool_foods["pollo"]) not in await _pool(user_id)


# --- sample_day_pool ---------------------------------------------------------------------------


def _c(id_, group, *, source="bedca", staple=True, complete=True, name=None):
    return CandidateFood(
        id_,
        name or id_,
        100,
        10,
        5,
        10,
        group=group,
        source=source,
        staple=staple,
        complete_data=complete,
    )


def test_the_day_pool_prefers_official_everyday_foods():
    members = [_c(f"oficial{i}", fg.MEAT) for i in range(10)]
    members += [_c(f"raro{i}", fg.MEAT, staple=False) for i in range(10)]
    members += [_c(f"super{i}", fg.MEAT, source="off", name=f"Pollo {i}x") for i in range(10)]
    # `name` con dígito no es «sencillo»: hay que ir a por los que no lo tienen
    simple = [
        _c(f"simple{i}", fg.MEAT, source="off", name=f"Pollo asado {'a' * i}") for i in range(5)
    ]

    pool = sample_day_pool(members + simple, random.Random(1))

    ids = {c.id for c in pool}
    assert len(pool) == 6
    assert not any(i.startswith("raro") for i in ids)
    assert not any(i.startswith("super") for i in ids)
    assert sum(i.startswith("simple") for i in ids) <= 2


def test_non_everyday_foods_only_fill_a_group_that_has_too_few():
    poor = [_c("uno", fg.FISH), _c("dos", fg.FISH)] + [
        _c(f"raro{i}", fg.FISH, staple=False) for i in range(10)
    ]
    ids = {c.id for c in sample_day_pool(poor, random.Random(1))}
    assert {"uno", "dos"} <= ids
    assert any(i.startswith("raro") for i in ids)


def test_supermarket_products_need_complete_data_and_a_simple_name():
    only_market = [
        _c("incompleto", fg.EGG, source="off", complete=False, name="Huevos"),
        _c("con_numero", fg.EGG, source="off", name="12 huevos frescos"),
        _c("bueno", fg.EGG, source="off", name="Huevos frescos"),
    ]
    assert [c.id for c in sample_day_pool(only_market, random.Random(1))] == ["bueno"]


def test_the_day_pool_is_deterministic_per_seed_and_varies_between_seeds():
    members = [_c(f"c{i}", fg.VEGETABLE) for i in range(30)]
    first = [c.id for c in sample_day_pool(members, random.Random("plan:0"))]
    again = [c.id for c in sample_day_pool(members, random.Random("plan:0"))]
    other = [c.id for c in sample_day_pool(members, random.Random("plan:1"))]
    assert first == again
    assert set(first) != set(other)


def test_the_day_pool_keeps_every_candidate_without_a_group_and_can_be_widened():
    ungrouped = [_c(f"g{i}", None) for i in range(3)]
    members = [_c(f"m{i}", fg.MEAT) for i in range(30)]
    pool = sample_day_pool(ungrouped + members, random.Random(1), per_group=12)
    assert {c.id for c in pool} >= {"g0", "g1", "g2"}
    assert sum(c.group == fg.MEAT for c in pool) == 12


# --- una alternativa es otro alimento, no otra marca del mismo -------------------------------


def test_un_nombre_que_contiene_al_otro_es_el_mismo_alimento():
    """Por cercanía nutricional, lo primero que sale como «alternativa» a un producto envasado
    es el mismo producto envasado por otro: «Pechuga De Pollo» proponía «Filete de pechuga de
    pollo» y «Pechuga entera de pollo»."""
    pollo = _significant_words("Pechuga De Pollo")
    assert _is_the_same_food(pollo, _significant_words("Filete de pechuga de pollo"))
    assert _is_the_same_food(pollo, _significant_words("Pechuga entera de pollo"))
    assert _is_the_same_food(
        _significant_words("Yogur natural"), _significant_words("Yogur natural desnatado")
    )


def test_una_alternativa_de_verdad_sobrevive_aunque_comparta_palabras():
    """La regla es de subconjunto y no de parecido a propósito: «Pavo, pechuga» comparte
    «pechuga» con «Pechuga de pollo» y es justo la alternativa que se busca."""
    pollo = _significant_words("Pechuga De Pollo")
    assert not _is_the_same_food(pollo, _significant_words("Pavo, pechuga"))
    assert not _is_the_same_food(pollo, _significant_words("Merluza, cruda"))
    assert not _is_the_same_food(_significant_words("Yogur natural"), _significant_words("Kéfir"))


def test_las_palabras_que_no_distinguen_no_cuentan():
    """«Fresco», «crudo» o «de» no diferencian un alimento de otro, y los acentos tampoco."""
    assert _significant_words("Pollo, pechuga fresca cruda") == _significant_words("pechuga pollo")
    assert _significant_words("Kéfir") == _significant_words("kefir")


async def test_no_se_ofrecen_dos_marcas_del_mismo_producto(registered_client, superuser_conn):
    """El filtro compara también contra las alternativas ya aceptadas: si no, dos marcas del
    mismo producto pasaban las dos porque solo se miraban contra el original."""
    conn = superuser_conn
    ids = {
        "original": await _insert(
            conn, "Pechuga de pollo (dup)", 108, 22, 2, 0, vec=[0.5, 0.9, 0.1, 0, 0, 0]
        ),
        "marca_a": await _insert(
            conn, "Filete de pechuga de pollo (dup)", 108, 22, 2, 0, vec=[0.5, 0.9, 0.1, 0, 0, 0.01]
        ),
        "marca_b": await _insert(
            conn, "Pechuga de pollo entera (dup)", 109, 22, 2, 0, vec=[0.5, 0.9, 0.1, 0, 0, 0.02]
        ),
        "pavo": await _insert(
            conn, "Pavo, pechuga (dup)", 135, 30, 1.5, 0, vec=[0.5, 0.9, 0.1, 0, 0, 0.03]
        ),
    }
    await conn.commit()
    try:
        _client, user_id = registered_client
        async with AdminSessionLocal() as session:
            found = await find_alternatives(session, ids["original"], 150.0, user_id, limit=10)
        nombres = [a.name_es for a in found]
        assert "Pavo, pechuga (dup)" in nombres
        assert not any("pechuga de pollo" in n.lower() for n in nombres)
    finally:
        await _cleanup(conn, [str(i) for i in ids.values()])
