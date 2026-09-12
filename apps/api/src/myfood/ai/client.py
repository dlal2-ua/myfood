"""Credencial de iafood (sección 10.1). Una única fila (`id=1`), cifrada con
`ENCRYPTION_KEY`. El token en claro nunca se registra en logs ni se devuelve
por la API una vez guardado (solo `{configured, updated_at}`)."""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from myfood.db.models import AiCredential
from myfood.db.types import decrypt_from_bytes, encrypt_to_bytes

_ROW_ID = 1


@dataclass
class CredentialStatus:
    configured: bool
    provider: str | None
    updated_at: datetime | None


async def get_credential_status(session: AsyncSession) -> CredentialStatus:
    row = await session.get(AiCredential, _ROW_ID)
    if row is None:
        return CredentialStatus(configured=False, provider=None, updated_at=None)
    return CredentialStatus(configured=True, provider=row.provider, updated_at=row.updated_at)


async def set_credential(
    session: AsyncSession, *, admin_user_id: UUID, token: str, provider: str = "anthropic"
) -> None:
    """Cifra y guarda el token (sustituye cualquier valor anterior)."""
    row = await session.get(AiCredential, _ROW_ID)
    encrypted = encrypt_to_bytes(token)
    if row is None:
        row = AiCredential(id=_ROW_ID, provider=provider, token_encrypted=encrypted)
        session.add(row)
    else:
        row.provider = provider
        row.token_encrypted = encrypted
    row.updated_by = admin_user_id
    await session.commit()


async def get_decrypted_token(session: AsyncSession) -> str | None:
    """Solo para uso interno del `worker` al invocar el Claude Agent SDK
    (sección 10.1/19 — nunca desde el hilo que atiende la petición del
    usuario). Nunca se pasa a un log ni a `ai_sessions`."""
    row = await session.get(AiCredential, _ROW_ID)
    if row is None:
        return None
    return decrypt_from_bytes(row.token_encrypted)
