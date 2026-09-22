"""Códigos de invitación: generarlos, comprobarlos y quemarlos.

La app está publicada en internet, así que registrarse deja de ser libre. Mismo mecanismo que
openGym: el administrador genera códigos de un solo uso y el registro exige uno válido.

Lo delicado es el momento de gastarlo. El código se comprueba al empezar el registro, pero
entre esa comprobación y el alta pueden pasar cosas (otro registro simultáneo con el mismo
código, o que el administrador lo revoque), así que se vuelve a reclamar de forma atómica en
el último momento: un UPDATE condicional que solo tiene éxito si el código sigue libre.
"""

from __future__ import annotations

import secrets
import string
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from myfood.db.models import Invite

# Sin vocales ni caracteres que se confundan al dictarlos por teléfono (0/O, 1/I/L).
_ALPHABET = "".join(c for c in string.ascii_uppercase + string.digits if c not in "OIL01")
CODE_LENGTH = 10
_GROUP = 5


def generate_code() -> str:
    """`XXXXX-XXXXX`. Se escribe a mano a menudo: en dos grupos se lee mejor."""
    raw = "".join(secrets.choice(_ALPHABET) for _ in range(CODE_LENGTH))
    return f"{raw[:_GROUP]}-{raw[_GROUP:]}"


def normalize_code(raw: str) -> str:
    """Acepta el código como lo escriba el usuario: minúsculas, con o sin guion, con espacios."""
    cleaned = "".join(c for c in (raw or "").upper() if c.isalnum())
    if len(cleaned) != CODE_LENGTH:
        return cleaned
    return f"{cleaned[:_GROUP]}-{cleaned[_GROUP:]}"


async def create_invite(session: AsyncSession, *, created_by: UUID, note: str | None) -> Invite:
    """Genera un código que no exista ya. La colisión es prácticamente imposible con este
    alfabeto, pero la clave primaria es el propio código: una colisión sería un 500."""
    for _ in range(5):
        code = generate_code()
        if await session.scalar(select(Invite.code).where(Invite.code == code)) is None:
            invite = Invite(code=code, note=(note or "").strip() or None, created_by=created_by)
            session.add(invite)
            await session.commit()
            await session.refresh(invite)
            return invite
    raise RuntimeError("no se pudo generar un código de invitación libre")


async def is_usable(session: AsyncSession, code: str) -> bool:
    """`True` si ese código existe, no se ha usado y no está revocado. Solo informativo: lo
    que decide de verdad es `claim`, que lo reclama de forma atómica."""
    return (
        await session.scalar(
            select(Invite.code).where(
                Invite.code == code,
                Invite.used_by.is_(None),
                Invite.revoked_at.is_(None),
            )
        )
    ) is not None


async def claim(session: AsyncSession, code: str, *, user_id: UUID) -> bool:
    """Marca el código como usado por `user_id`. Devuelve `False` si ya no estaba libre.

    El UPDATE lleva las condiciones dentro: dos registros a la vez con el mismo código son dos
    UPDATE contra la misma fila, y solo uno cambia algo. Comprobar antes y escribir después
    dejaría entrar a los dos."""
    result = await session.execute(
        update(Invite)
        .where(
            Invite.code == code,
            Invite.used_by.is_(None),
            Invite.revoked_at.is_(None),
        )
        .values(used_by=user_id, used_at=datetime.now(UTC))
    )
    return result.rowcount == 1


async def revoke(session: AsyncSession, code: str) -> bool:
    """Anula un código que todavía no se ha usado. Uno ya usado no se revoca: eso sería
    borrar de quién vino una cuenta que ya existe."""
    result = await session.execute(
        update(Invite)
        .where(Invite.code == code, Invite.used_by.is_(None), Invite.revoked_at.is_(None))
        .values(revoked_at=datetime.now(UTC))
    )
    return result.rowcount == 1


async def list_invites(session: AsyncSession) -> list[dict]:
    """Los códigos con el nombre de quien los usó, para el panel."""
    rows = (
        await session.execute(
            text("""
                SELECT i.code, i.note, i.created_at, i.used_at, i.revoked_at,
                       u.display_name AS used_by_name
                FROM invites i
                LEFT JOIN users u ON u.id = i.used_by
                ORDER BY i.created_at DESC
            """)
        )
    ).all()
    return [
        {
            "code": r.code,
            "note": r.note,
            "created_at": r.created_at.isoformat(),
            "used_at": r.used_at.isoformat() if r.used_at else None,
            "used_by_name": r.used_by_name,
            "revoked_at": r.revoked_at.isoformat() if r.revoked_at else None,
            "status": (
                "usado" if r.used_at else "revocado" if r.revoked_at else "disponible"
            ),
        }
        for r in rows
    ]


async def count_usable(session: AsyncSession) -> int:
    return (
        await session.scalar(
            select(func.count())
            .select_from(Invite)
            .where(Invite.used_by.is_(None), Invite.revoked_at.is_(None))
        )
    ) or 0
