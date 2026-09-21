import base64
import json
import os
import tempfile
import uuid
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import pytest
import pytest_asyncio
import redis as redis_sync
from httpx import ASGITransport, AsyncClient
from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import create_async_engine

# Redis LÓGICO aparte para los tests (db 15), fijado ANTES de importar nada de
# `myfood` (los clientes de Redis se crean a nivel de módulo con `REDIS_URL`).
# Los tests corren contra el Redis compartido con producción: sin esto sus
# peticiones incrementaban los contadores REALES de cuota de iafood
# (`iafood:quota:*:instance:*`, límite 30/día) — tras unas cuantas ejecuciones
# locales Smart Log e importar recetas devolvían 429 a los usuarios de verdad
# (y a los propios tests) hasta medianoche.
_TEST_REDIS_DB = 15
_redis_parts = urlsplit(os.environ.get("REDIS_URL", "redis://redis:6379/0"))
os.environ["REDIS_URL"] = urlunsplit(_redis_parts._replace(path=f"/{_TEST_REDIS_DB}"))

from myfood.config import get_settings  # noqa: E402

settings = get_settings()

# --- Protección de la credencial real de iafood -------------------------------
#
# Estos tests corren contra el MISMO Postgres que producción (localmente, con
# POSTGRES_HOST apuntando al contenedor; en CI la BD es una desechable vacía)
# y muchos borran/crean la fila única de `ai_credentials`. Sin esto, un
# `pytest` local destruye en silencio el token real del admin en cuanto lo ha
# pegado en el panel (`claude setup-token`, algo que solo él puede volver a
# generar).
#
# Al empezar la sesión se guarda la fila real (en memoria y en un fichero 0600
# en el directorio temporal — solo contiene el token YA CIFRADO, igual que la
# BD — para sobrevivir a un proceso matado a mitad); antes de cada test la
# tabla se vacía (así ningún test depende de que haya o no un token real); y
# al terminar la sesión se borra lo que hayan dejado los tests y se restaura la
# fila real. Si una sesión anterior murió sin restaurar (fichero presente y
# fila ausente), la siguiente la restaura al arrancar.
_CREDENTIAL_BACKUP_PATH = Path(tempfile.gettempdir()) / "myfood-tests-ai-credential-backup.json"
_SELECT_CREDENTIAL = text(
    "SELECT provider, token_encrypted, updated_by, updated_at FROM ai_credentials WHERE id = 1"
)


def _write_credential_backup(row, path: Path = _CREDENTIAL_BACKUP_PATH) -> dict:
    payload = {
        "provider": row.provider,
        "token_encrypted": base64.b64encode(bytes(row.token_encrypted)).decode(),
        "updated_by": str(row.updated_by) if row.updated_by is not None else None,
        "updated_at": row.updated_at.isoformat(),
    }
    # Se borra antes de crear para que el 0600 se aplique de verdad (el modo de
    # os.open solo cuenta al crear el fichero).
    path.unlink(missing_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(payload, f)
    return payload


def _restore_credential(conn, payload: dict) -> None:
    conn.execute(text("DELETE FROM ai_credentials"))
    conn.execute(
        text(
            "INSERT INTO ai_credentials (id, provider, token_encrypted, updated_by, updated_at) "
            "VALUES (1, :provider, :token, "
            # Si el usuario que la guardó ya no existe, mejor sin `updated_by`
            # que perder el token por una violación de la FK.
            "(SELECT id FROM users WHERE id = CAST(:updated_by AS uuid)), "
            "CAST(:updated_at AS timestamptz))"
        ),
        {
            "provider": payload["provider"],
            "token": base64.b64decode(payload["token_encrypted"]),
            "updated_by": payload["updated_by"],
            "updated_at": payload["updated_at"],
        },
    )


def _flush_test_redis() -> None:
    """Vacía solo la db lógica de tests (nunca la 0, que es la de producción):
    los contadores de cuota de una ejecución anterior no deben dar 429 a la
    siguiente."""
    try:
        client = redis_sync.Redis.from_url(settings.redis_url)
        assert client.connection_pool.connection_kwargs.get("db") == _TEST_REDIS_DB
        client.flushdb()
        client.close()
    except (redis_sync.RedisError, AssertionError):
        pass


@pytest.fixture(scope="session", autouse=True)
def isolated_test_redis():
    _flush_test_redis()
    yield
    _flush_test_redis()


_TEST_EMAIL_DOMAIN = "@test.myfood"


def _real_users_present(conn) -> int:
    """Usuarios que NO son de test: si hay alguno, esta BD es una instalación real."""
    return conn.execute(
        text("SELECT count(*) FROM users WHERE email NOT LIKE :pattern"),
        {"pattern": f"%{_TEST_EMAIL_DOMAIN}"},
    ).scalar_one()


@pytest.fixture(scope="session", autouse=True)
def protect_real_ai_credential():
    engine = create_engine(settings.database_url_superuser_sync)
    payload: dict | None = None
    try:
        with engine.begin() as conn:
            # La suite crea y borra usuarios, alimentos y planes a mansalva: contra la BD de
            # producción dejaba restos (decenas de usuarios y alimentos de test) y rozaba
            # datos reales. Se niega a correr donde haya usuarios reales.
            if _real_users_present(conn) and os.environ.get("MYFOOD_TESTS_ALLOW_REAL_DB") != "1":
                pytest.exit(
                    "Esta base de datos tiene usuarios reales: la suite no corre contra ella. "
                    "Usa scripts/test-api.sh (crea una BD desechable), o define "
                    "MYFOOD_TESTS_ALLOW_REAL_DB=1 si sabes lo que haces.",
                    returncode=2,
                )
            row = conn.execute(_SELECT_CREDENTIAL).first()
            if row is None and _CREDENTIAL_BACKUP_PATH.exists():
                _restore_credential(conn, json.loads(_CREDENTIAL_BACKUP_PATH.read_text()))
                row = conn.execute(_SELECT_CREDENTIAL).first()
            if row is not None:
                payload = _write_credential_backup(row)
            else:
                _CREDENTIAL_BACKUP_PATH.unlink(missing_ok=True)
    except SQLAlchemyError:
        # Sin BD alcanzable (o sin migrar) no hay nada que proteger — los tests
        # que la necesiten fallarán por su cuenta.
        engine.dispose()
        yield None
        return

    yield engine

    try:
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM ai_credentials"))
            if payload is not None:
                _restore_credential(conn, payload)
        _CREDENTIAL_BACKUP_PATH.unlink(missing_ok=True)
    finally:
        engine.dispose()


@pytest.fixture(autouse=True)
def clean_ai_credentials_before_each_test(protect_real_ai_credential):
    if protect_real_ai_credential is not None:
        with protect_real_ai_credential.begin() as conn:
            conn.execute(text("DELETE FROM ai_credentials"))
    yield


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
        # R4: sin el consentimiento de datos de salud no se puede guardar perfil ni
        # medidas; los tests que necesitan un usuario SIN él usan `fresh_client`.
        await client.post("/api/consents", json={"kind": "health_data", "version": "v1"})
        yield client, uuid.UUID(user_id)

    await superuser_conn.execute(text("DELETE FROM users WHERE id = :id"), {"id": user_id})
    await superuser_conn.commit()


@pytest_asyncio.fixture
async def fresh_client(superuser_conn):
    """Usuario recién registrado que todavía NO ha aceptado ningún consentimiento."""
    from myfood.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="https://test") as client:
        resp = await client.post(
            "/api/auth/register",
            json={
                "email": f"fresh-{uuid.uuid4()}@test.myfood",
                "password": "correcthorse123",
                "display_name": "Fresh",
            },
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
    # food_log, shopping_list_items, supplements, recipe_ingredients y
    # pantry_items pueden referenciar este alimento (creado por el propio
    # test) y su teardown puede correr después o antes que el de
    # registered_client según el orden de los fixtures — se borra
    # explícitamente aquí para no depender de ese orden ni de una CASCADE
    # que no existe en ninguna de estas tablas (solo *.user_id tiene
    # ON DELETE CASCADE, no *.food_id). `plan_items`/`plan_item_alternatives`
    # /`food_vectors` entran en la misma categoría: en un entorno con el
    # catálogo vacío (CI, o esta BD de prueba), `select_candidates` escanea
    # TODA la tabla `foods` — este alimento puede colar como candidato real
    # del generador de dietas (bug real encontrado: quality_rank=1 y 31 g de
    # proteína/100 g lo hacían competitivo) en cualquier test que además
    # genere un plan, no solo en los tests de /log.
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
    await superuser_conn.execute(
        text("DELETE FROM pantry_items WHERE food_id = :id"), {"id": str(food_id)}
    )
    await superuser_conn.execute(
        text("DELETE FROM plan_items WHERE food_id = :id"), {"id": str(food_id)}
    )
    await superuser_conn.execute(
        text("DELETE FROM plan_item_alternatives WHERE food_id = :id"), {"id": str(food_id)}
    )
    await superuser_conn.execute(
        text("DELETE FROM food_vectors WHERE food_id = :id"), {"id": str(food_id)}
    )
    await superuser_conn.execute(text("DELETE FROM foods WHERE id = :id"), {"id": str(food_id)})
    await superuser_conn.commit()


@pytest_asyncio.fixture
async def diet_candidates(superuser_conn):
    """Un mini catálogo español realista (con alimentos de todos los grupos que piden las
    plantillas de comida: proteína principal, verdura, hidrato, lácteo, fruta…) insertado con
    `source='bedca'`, la fuente que usa el motor. Con la BD de test vacía (CI, o la BD
    desechable `myfood_test`) estos son los únicos candidatos posibles; los valores son
    coherentes con sus propios macros para pasar los filtros de plausibilidad de
    `select_candidates`.

    Los índices 0, 1 y 2 (pollo, arroz, huevo) son los que los tests tratan como «los más
    competitivos» del pool: vetarlos o marcarlos como alérgenos no debe dejar el plan vacío.
    """
    foods = [
        ("Pollo, pechuga, a la plancha (test)", 165, 31, 3.6, 0),
        ("Arroz, hervido (test)", 130, 2.7, 0.3, 28),
        ("Huevo de gallina, cocido (test)", 155, 13, 11, 1.1),
        ("Ternera, solomillo, asado (test)", 156, 28.4, 4.5, 0),
        ("Pavo, pechuga, a la plancha (test)", 135, 30, 1.5, 0),
        ("Merluza, cruda (test)", 71, 16, 0.8, 0),
        ("Salmón, a la plancha (test)", 208, 20, 13, 0),
        ("Lenteja, cocida (test)", 116, 9, 0.4, 20),
        ("Garbanzo, cocido (test)", 164, 8.9, 2.6, 27),
        ("Brócoli, cocido (test)", 35, 2.4, 0.4, 7),
        ("Tomate, crudo (test)", 22, 1, 0.2, 3.5),
        ("Espinaca, cruda (test)", 23, 2.9, 0.4, 3.6),
        ("Judías verdes, cocidas (test)", 31, 1.8, 0.2, 7),
        ("Pasta alimenticia, hervida (test)", 131, 5, 1.1, 25),
        ("Patata, hervida (test)", 87, 1.9, 0.1, 20),
        ("Pan integral (test)", 250, 9, 3.3, 43),
        ("Copos de avena (test)", 372, 13.5, 7, 60),
        ("Leche semidesnatada (test)", 46, 3.4, 1.6, 4.8),
        ("Yogur natural (test)", 61, 3.5, 3.3, 4.7),
        ("Queso fresco (test)", 174, 18, 10, 3),
        ("Plátano (test)", 90, 1.1, 0.3, 21),
        ("Manzana (test)", 52, 0.3, 0.2, 14),
        ("Nueces (test)", 654, 15, 65, 7),
        ("Aceite de oliva virgen extra (test)", 884, 0, 100, 0),
    ]
    ids = []
    for name, kcal, protein, fat, carbs in foods:
        food_id = uuid.uuid4()
        ids.append(food_id)
        await superuser_conn.execute(
            text(
                "INSERT INTO foods (id, kind, source, source_id, license, name_es, category, "
                "quality_rank) VALUES (:id, 'generic', 'bedca', :sid, 'CC0', :name, NULL, 4)"
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
        # Fase 7: generar la lista de la compra desde un plan (o añadir a la
        # despensa) puede haber creado filas que referencian estos alimentos
        # de prueba — igual que en `test_food`, no depender del orden de
        # teardown entre fixtures (el `ON DELETE CASCADE` de `user_id` en
        # `registered_client` podría no haber corrido todavía).
        await superuser_conn.execute(
            text("DELETE FROM shopping_list_items WHERE food_id = :id"), {"id": str(food_id)}
        )
        await superuser_conn.execute(
            text("DELETE FROM pantry_items WHERE food_id = :id"), {"id": str(food_id)}
        )
        await superuser_conn.execute(
            text("DELETE FROM food_log WHERE food_id = :id"), {"id": str(food_id)}
        )
    await superuser_conn.execute(
        text("DELETE FROM foods WHERE id = ANY(:ids)"), {"ids": [str(i) for i in ids]}
    )
    await superuser_conn.commit()
