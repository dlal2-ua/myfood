import uuid

import pytest_asyncio
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
