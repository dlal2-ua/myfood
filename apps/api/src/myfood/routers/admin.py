"""Panel de administración (secciones 7.7 y 22 de la especificación).

Solo accesible con `role='admin'` (R `get_admin_user`, deps.py), y siempre a
través del rol de conexión `myfood_admin` — nunca `myfood_app` — según la
sección 22 ("el panel de admin... usa un rol de conexión distinto").
"""

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from myfood.ai import client as ai_client
from myfood.ai.limits import IafoodLimits, load_limits, save_limits
from myfood.db.models import User
from myfood.db.session import get_admin_session
from myfood.deps import get_admin_user
from myfood.errors import AppError

router = APIRouter(prefix="/admin/ai", tags=["admin"])


class CredentialStatusOut(BaseModel):
    configured: bool
    provider: str | None
    updated_at: str | None


class SetCredentialIn(BaseModel):
    # El token real (`claude setup-token`) es del orden de un centenar de
    # caracteres; el límite es solo una cota defensiva, no una validación
    # de formato — no hay forma de verificar un setup-token sin usarlo.
    token: str = Field(min_length=1, max_length=4000)


def _to_status_out(status: ai_client.CredentialStatus) -> CredentialStatusOut:
    return CredentialStatusOut(
        configured=status.configured,
        provider=status.provider,
        updated_at=status.updated_at.isoformat() if status.updated_at else None,
    )


@router.get("/credential", response_model=CredentialStatusOut)
async def get_credential(
    _admin: User = Depends(get_admin_user),
    session: AsyncSession = Depends(get_admin_session),
) -> CredentialStatusOut:
    """Nunca devuelve el token en sí (sección 7.7)."""
    return _to_status_out(await ai_client.get_credential_status(session))


@router.put("/credential", response_model=CredentialStatusOut)
async def put_credential(
    body: SetCredentialIn,
    admin: User = Depends(get_admin_user),
    session: AsyncSession = Depends(get_admin_session),
) -> CredentialStatusOut:
    token = body.token.strip()
    if not token:
        raise AppError(
            "INVALID_TOKEN", "Pega el token que imprime `claude setup-token`.", status_code=400
        )
    await ai_client.set_credential(session, admin_user_id=admin.id, token=token)
    return _to_status_out(await ai_client.get_credential_status(session))


@router.get("/limits", response_model=IafoodLimits)
async def get_limits(_admin: User = Depends(get_admin_user)) -> IafoodLimits:
    return load_limits()


@router.put("/limits", response_model=IafoodLimits)
async def put_limits(body: IafoodLimits, _admin: User = Depends(get_admin_user)) -> IafoodLimits:
    save_limits(body)
    return body
