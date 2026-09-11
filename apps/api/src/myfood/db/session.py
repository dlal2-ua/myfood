from collections.abc import AsyncGenerator
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from myfood.config import get_settings

settings = get_settings()

# Motor con el rol de aplicación (myfood_app), sujeto a las políticas RLS (R11, sección 22).
engine = create_async_engine(settings.database_url, pool_pre_ping=True)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)

# Motor con el rol de admin (myfood_admin), sin políticas RLS — solo para /admin/*.
admin_engine = create_async_engine(
    settings.database_url.replace(
        f"{settings.postgres_app_role}:{settings.postgres_app_password}",
        f"{settings.postgres_admin_role}:{settings.postgres_admin_password}",
    ),
    pool_pre_ping=True,
)
AdminSessionLocal = async_sessionmaker(admin_engine, expire_on_commit=False)


async def set_rls_context(session: AsyncSession, user_id: UUID) -> None:
    """Establece `app.current_user_id` para esta transacción (sección 22).

    Debe ejecutarse ANTES de cualquier otra query en la sesión de una
    petición autenticada. Las políticas RLS de Postgres filtran por esta
    variable de sesión, como segunda capa independiente del filtrado
    `WHERE user_id = ...` en código (R3 + R11).

    Postgres no admite parámetros bind en `SET` (es una sentencia de
    utilidad, no una query). `user_id` es siempre un `uuid.UUID` ya
    validado por el tipo — nunca texto crudo de la petición — así que
    interpolar su `str()` aquí no abre una vía de inyección SQL.
    """
    await session.execute(text(f"SET LOCAL app.current_user_id = '{user_id}'"))


async def get_session() -> AsyncGenerator[AsyncSession]:
    """Sesión SIN contexto de usuario — solo para endpoints públicos (auth, health)."""
    async with SessionLocal() as session:
        yield session


async def get_admin_session() -> AsyncGenerator[AsyncSession]:
    async with AdminSessionLocal() as session:
        yield session
