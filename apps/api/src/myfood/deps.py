from collections.abc import AsyncGenerator
from uuid import UUID

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from myfood.db.session import SessionLocal, set_rls_context
from myfood.errors import AppError
from myfood.security import SESSION_COOKIE_NAME, get_session_user_id


async def get_current_user_id(request: Request) -> UUID:
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if token is None:
        raise AppError("NOT_AUTHENTICATED", "Se requiere iniciar sesión.", status_code=401)
    user_id = await get_session_user_id(token)
    if user_id is None:
        raise AppError("SESSION_EXPIRED", "La sesión ha caducado.", status_code=401)
    return user_id


async def get_db(request: Request) -> AsyncGenerator[AsyncSession]:
    """Sesión con el contexto RLS ya establecido para el usuario autenticado (R11)."""
    user_id = await get_current_user_id(request)
    async with SessionLocal() as session:
        # SQLAlchemy 2.0 autobegin: este SET LOCAL abre la transacción y su
        # alcance dura hasta el commit/rollback que haga el propio endpoint.
        await set_rls_context(session, user_id)
        yield session
