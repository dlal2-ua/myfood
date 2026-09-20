"""Horas de silencio por defecto de un usuario («no molestar»): las de sus reglas de recordatorio
existentes, o 23:00–08:00 si todavía no tiene ninguna. Así una regla nueva nace con el mismo «no
molestar» que las demás sin necesitar una columna propia."""

from __future__ import annotations

from datetime import time
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from myfood.db.models import NotificationRule

DEFAULT_QUIET_FROM = time(23, 0)
DEFAULT_QUIET_TO = time(8, 0)


async def default_quiet_hours(session: AsyncSession, user_id: UUID) -> tuple[time, time]:
    rule = await session.scalar(
        select(NotificationRule)
        .where(NotificationRule.user_id == user_id)
        .order_by(NotificationRule.id)
        .limit(1)
    )
    if rule is None:
        return DEFAULT_QUIET_FROM, DEFAULT_QUIET_TO
    return rule.quiet_from, rule.quiet_to
