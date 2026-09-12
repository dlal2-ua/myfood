from collections.abc import AsyncGenerator
from uuid import UUID

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from myfood.db.models import User
from myfood.db.session import SessionLocal, get_admin_session, set_rls_context
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


async def get_admin_user(
    user_id: UUID = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_admin_session),
) -> User:
    """Solo para rutas bajo `/admin/*` (sección 22): sesión autenticada
    normal, pero cargada con el rol de conexión `myfood_admin` (sin RLS) y
    exigiendo `role == 'admin'` en la fila del usuario."""
    user = await session.get(User, user_id)
    if user is None or not user.is_active:
        raise AppError("NOT_AUTHENTICATED", "Se requiere iniciar sesión.", status_code=401)
    if user.role != "admin":
        raise AppError("FORBIDDEN", "Se requiere rol de administrador.", status_code=403)
    return user
