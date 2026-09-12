import uuid

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from myfood.config import get_settings

settings = get_settings()


@pytest_asyncio.fixture
async def superuser_conn():
    engine = create_async_engine(settings.database_url_superuser)
    async with engine.connect() as conn:
        yield conn
    await engine.dispose()


@pytest_asyncio.fixture
async def app_engine():
    engine = create_async_engine(settings.database_url)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def two_users(superuser_conn):
    """Crea dos usuarios reales (con perfil) directamente en BD para los
    tests de aislamiento — sin pasar por el API, para no acoplar el test
    de RLS al endpoint de registro."""
    user_a = uuid.uuid4()
    user_b = uuid.uuid4()
    await superuser_conn.execute(
        text(
            "INSERT INTO users (id, email, password_hash, display_name) "
            "VALUES (:id, :email, 'x', 'Test User')"
        ),
        [
            {"id": str(user_a), "email": f"a-{user_a}@test.myfood"},
            {"id": str(user_b), "email": f"b-{user_b}@test.myfood"},
        ],
    )
    await superuser_conn.execute(
        text("INSERT INTO profiles (user_id, meals_per_day) VALUES (:id, 3)"),
        [{"id": str(user_a)}, {"id": str(user_b)}],
    )
    await superuser_conn.commit()
    yield user_a, user_b
    await superuser_conn.execute(
        text("DELETE FROM users WHERE id IN (:a, :b)"),
        {"a": str(user_a), "b": str(user_b)},
    )
    await superuser_conn.commit()


@pytest_asyncio.fixture
async def registered_client(superuser_conn):
    """Cliente HTTP real con sesión ya iniciada — para tests de endpoints
    autenticados (profile, calc, log...) sin repetir el flujo de registro."""
    from myfood.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="https://test") as client:
        email = f"test-{uuid.uuid4()}@test.myfood"
        resp = await client.post(
            "/api/auth/register",
            json={"email": email, "password": "correcthorse123", "display_name": "Test User"},
        )
        user_id = resp.json()["id"]
        yield client, uuid.UUID(user_id)

    await superuser_conn.execute(text("DELETE FROM users WHERE id = :id"), {"id": user_id})
    await superuser_conn.commit()


@pytest_asyncio.fixture
async def test_food(superuser_conn):
    """Alimento real en BD (sin pasar por Meilisearch) para tests de /log."""
    food_id = uuid.uuid4()
    await superuser_conn.execute(
        text(
            "INSERT INTO foods (id, kind, source, source_id, license, name_es, quality_rank) "
            "VALUES (:id, 'generic', 'test', :sid, 'CC0', 'Pechuga de pollo de prueba', 1)"
        ),
        {"id": str(food_id), "sid": str(food_id)},
    )
    await superuser_conn.execute(
        text(
            "INSERT INTO food_nutrients "
            "(food_id, kcal_100g, protein_100g, fat_100g, carbs_100g, micros) "
            "VALUES (:id, 165, 31, 3.6, 0, '{\"iron_mg\": 0.7}'::jsonb)"
        ),
        {"id": str(food_id)},
    )
    await superuser_conn.commit()
    yield food_id
    # food_log, shopping_list_items, supplements y recipe_ingredients pueden
    # referenciar este alimento (creado por el propio test) y su teardown
    # puede correr después o antes que el de registered_client según el
    # orden de los fixtures — se borra explícitamente aquí para no depender
    # de ese orden ni de una CASCADE que no existe en ninguna de las cuatro
    # tablas (solo *.user_id tiene ON DELETE CASCADE, no *.food_id).
    await superuser_conn.execute(
        text("DELETE FROM food_log WHERE food_id = :id"), {"id": str(food_id)}
    )
    await superuser_conn.execute(
        text("DELETE FROM shopping_list_items WHERE food_id = :id"), {"id": str(food_id)}
    )
    await superuser_conn.execute(
        text("DELETE FROM supplements WHERE food_id = :id"), {"id": str(food_id)}
    )
    await superuser_conn.execute(
        text("DELETE FROM recipe_ingredients WHERE food_id = :id"), {"id": str(food_id)}
    )
    await superuser_conn.execute(text("DELETE FROM foods WHERE id = :id"), {"id": str(food_id)})
    await superuser_conn.commit()


@pytest_asyncio.fixture
async def diet_candidates(superuser_conn):
    """Un puñado de alimentos reales y nutricionalmente diversos (proteína,
    carbohidrato, grasa, verdura) — sin esto el candidate pool real (que
    excluye 'user'/'recipe' y filtra por macros) podría no tener suficiente
    variedad en una BD de test, dejando el plan infactible por falta de
    materia prima, no por un fallo real.

    La selección de candidatos del router pilla los N mejores de cada
    macronutriente (`ORDER BY protein_100g DESC LIMIT 40`, etc.) sobre TODA
    `foods` — en este entorno esa tabla ya tiene el catálogo real completo
    (miles de alimentos de USDA/CIQUAL/BEDCA/OFF), así que un valor "normal"
    de macros no garantiza en absoluto que estos alimentos de prueba entren
    en el candidate pool, y el router también exige `kcal_100g` en un rango
    "realista" (20-600, ver `_MIN/MAX_REALISTIC_KCAL_100G`) para dejar fuera
    aceites puros y productos casi sin calorías. En CI, en cambio, `foods`
    está vacía (la migración no carga el ETL) — estos alimentos son ahí los
    únicos candidatos posibles, así que también deben pasar esos mismos
    filtros por sí solos para que `select_candidates` no devuelva vacío.

    Los dos primeros usan un valor justo por encima de 100 g/100 g en
    proteína/carbohidrato — imposible para cualquier alimento real (las
    reglas de descarte del ETL exigen proteína+grasa+carbohidratos ≤100 g,
    sección 11.2) pero con `kcal_100g` calculado de forma coherente con esa
    macro (4 kcal/g) para quedar dentro del rango realista — garantizados en
    la cabeza de su bucket sin depender de qué haya en el catálogo real, y
    sin desbordar el objetivo del día ni siquiera con la cantidad mínima del
    solver (20 g). El mismo truco no es posible para grasa (9 kcal/g × 100 g
    ya son 900 kcal, siempre por encima del rango realista) — para ese
    bucket se usa un valor alto pero no "imposible" (60 g/100 g), razonable
    porque los alimentos con más grasa dentro del rango realista (aceites
    puros excluidos) rara vez lo superan.

    Se detectó en la práctica, en este orden: (1) un valor de macro
    "imposible" pero con kcal declarado bajo e inconsistente (400 kcal con
    900 g de proteína) le da al solver un "chollo" que no existe en ningún
    alimento real; (2) corregido eso, un valor todavía demasiado alto
    (900 g/100 g) desborda el objetivo del día incluso en la cantidad
    mínima (20 g) por sí solo; (3) ya con 101 g/100 g SÍ funcionaba para
    proteína/carbohidrato, pero reveló que el propio candidate pool real
    (antes de este fixture) arrastraba salvado de maíz, algas deshidratadas
    y aceites/mantecas puras por su densidad de macro — de ahí el filtro de
    `kcal_100g` en rango realista y la eliminación del cubo de fibra en
    `routers/diet_plans.py` (la fibra no es un objetivo del solver).

    También hay un filtro de "ningún macro por sí solo pasa del 90% de las
    kcal" (mismo módulo) — un alimento sintético de un solo macro puro
    (p. ej. proteína=101, todo lo demás 0) lo incumple de sobra (100% de
    sus kcal vienen de ese único macro). Se añade un segundo macro
    secundario modesto a cada uno para quedar por debajo del 90% sin dejar
    de superar los 100 g/100 g "imposibles" en el macro dominante."""
    foods = [
        ("Súper-proteína (test)", round((101 + 20) * 4), 101, 0, 20),
        ("Súper-carbohidrato (test)", round((101 + 20) * 4), 20, 0, 101),
        ("Alto en grasa (test)", round(50 * 9 + 15 * 4 + 5 * 4), 15, 50, 5),
        ("Verdura de prueba (test)", 40, 3, 0.4, 7),
        ("Huevo (test)", 155, 13, 11, 1.1),
        ("Lentejas cocidas (test)", 116, 9, 0.4, 20),
    ]
    ids = []
    for name, kcal, protein, fat, carbs in foods:
        food_id = uuid.uuid4()
        ids.append(food_id)
        await superuser_conn.execute(
            text(
                "INSERT INTO foods (id, kind, source, source_id, license, name_es, quality_rank) "
                "VALUES (:id, 'generic', 'test', :sid, 'CC0', :name, 1)"
            ),
            {"id": str(food_id), "sid": str(food_id), "name": name},
        )
        await superuser_conn.execute(
            text(
                "INSERT INTO food_nutrients "
                "(food_id, kcal_100g, protein_100g, fat_100g, carbs_100g) "
                "VALUES (:id, :kcal, :protein, :fat, :carbs)"
            ),
            {
                "id": str(food_id),
                "kcal": kcal,
                "protein": protein,
                "fat": fat,
                "carbs": carbs,
            },
        )
    await superuser_conn.commit()
    yield ids
    for food_id in ids:
        await superuser_conn.execute(
            text("DELETE FROM plan_items WHERE food_id = :id"), {"id": str(food_id)}
        )
        await superuser_conn.execute(
            text("DELETE FROM plan_item_alternatives WHERE food_id = :id"), {"id": str(food_id)}
        )
        await superuser_conn.execute(
            text("DELETE FROM food_vectors WHERE food_id = :id"), {"id": str(food_id)}
        )
    await superuser_conn.execute(
        text("DELETE FROM foods WHERE id = ANY(:ids)"), {"ids": [str(i) for i in ids]}
    )
    await superuser_conn.commit()
