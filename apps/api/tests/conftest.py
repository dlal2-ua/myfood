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
    # food_log puede referenciar este alimento (creado por el propio test) y
    # su teardown puede correr después o antes que el de registered_client
    # según el orden de los fixtures — se borra explícitamente aquí para no
    # depender de ese orden ni de la CASCADE de food_log_food_id_fkey (que no
    # existe: solo food_log.user_id tiene ON DELETE CASCADE, no food_id).
    await superuser_conn.execute(
        text("DELETE FROM food_log WHERE food_id = :id"), {"id": str(food_id)}
    )
    await superuser_conn.execute(text("DELETE FROM foods WHERE id = :id"), {"id": str(food_id)})
    await superuser_conn.commit()
