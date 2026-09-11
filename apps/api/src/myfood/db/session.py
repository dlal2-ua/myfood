from collections.abc import AsyncGenerator
from uuid import UUID

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session as SyncSession

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

_RLS_INFO_KEY = "rls_user_id"


@event.listens_for(SyncSession, "after_begin")
def _reapply_rls_context(session: SyncSession, transaction, connection) -> None:
    """Reaplica `app.current_user_id` en CADA transacción de la sesión, no solo la primera.

    `SET LOCAL` sobre un GUC personalizado (uno nunca declarado a nivel de
    servidor) vuelve a cadena vacía tras el COMMIT que lo abrió — no a NULL —
    y `current_setting(...)::uuid` revienta con esa cadena vacía. Como
    SQLAlchemy 2.0 reabre una transacción nueva (autobegin) en la siguiente
    query tras cada commit, cualquier endpoint que haga más de una
    transacción por petición (p. ej. `commit()` seguido de `refresh()`)
    perdía el contexto RLS a mitad de la petición. Este listener se dispara
    en cada `BEGIN` de la sesión (incluida la primera) y no hace nada si la
    sesión no tiene contexto de usuario (p. ej. `get_session`, admin).
    """
    user_id = session.info.get(_RLS_INFO_KEY)
    if user_id is not None:
        connection.execute(text(f"SET LOCAL app.current_user_id = '{user_id}'"))


async def set_rls_context(session: AsyncSession, user_id: UUID) -> None:
    """Fija el `user_id` de la sesión para RLS (sección 22) — ver `_reapply_rls_context`.

    Postgres no admite parámetros bind en `SET` (es una sentencia de
    utilidad, no una query). `user_id` es siempre un `uuid.UUID` ya
    validado por el tipo — nunca texto crudo de la petición — así que
    interpolar su `str()` en el listener no abre una vía de inyección SQL.
    """
    session.sync_session.info[_RLS_INFO_KEY] = user_id
    if session.sync_session.in_transaction():
        # Autobegin ya abrió la transacción antes de que pudiéramos fijar
        # session.info (p. ej. tras un `session.get()` previo) — aplica ya.
        await session.execute(text(f"SET LOCAL app.current_user_id = '{user_id}'"))


async def get_session() -> AsyncGenerator[AsyncSession]:
    """Sesión SIN contexto de usuario — solo para endpoints públicos (auth, health)."""
    async with SessionLocal() as session:
        yield session


async def get_admin_session() -> AsyncGenerator[AsyncSession]:
    async with AdminSessionLocal() as session:
        yield session
