"""Panel de administración: quién entra, quién puede usar la IA y cómo va la instancia.

Mismo criterio que `routers/admin.py` (sección 22): solo con `role='admin'` y siempre con el
rol de conexión `myfood_admin`, que no pasa por RLS — es la única forma de ver datos de todos
los usuarios, y por eso estas rutas no devuelven nunca el contenido de nadie (ni comidas, ni
medidas, ni mensajes), solo recuentos y fechas.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from uuid import UUID

import redis.asyncio as redis
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from myfood.ai.limits import load_limits
from myfood.app_settings import AppSettings, load_app_settings, save_app_settings
from myfood.config import get_settings
from myfood.db.models import User
from myfood.db.session import get_admin_session
from myfood.deps import get_admin_user
from myfood.domain import invites as invites_domain
from myfood.errors import AppError

router = APIRouter(prefix="/admin", tags=["admin"])

_redis = redis.from_url(get_settings().redis_url, decode_responses=True)

# Ámbitos de cuota que se cuentan por persona en el panel (los mismos que consume el código).
AI_SCOPES = (
    "smart_log", "chat", "diet_plan", "supplement_suggestion", "receipt_scan", "plate_photo",
)  # fmt: skip


# --------------------------------------------------------------------------- ajustes


class AppSettingsOut(BaseModel):
    invite_only: bool
    ai_enabled_by_default: bool


@router.get("/settings")
async def get_app_settings(_admin: User = Depends(get_admin_user)) -> AppSettingsOut:
    return AppSettingsOut(**load_app_settings().model_dump())


@router.put("/settings")
async def put_app_settings(
    body: AppSettingsOut, _admin: User = Depends(get_admin_user)
) -> AppSettingsOut:
    save_app_settings(AppSettings(**body.model_dump()))
    return body


# --------------------------------------------------------------------------- invitaciones


class InviteOut(BaseModel):
    code: str
    note: str | None
    created_at: str
    used_at: str | None
    used_by_name: str | None
    revoked_at: str | None
    status: str


class CreateInviteIn(BaseModel):
    """`note` es para acordarse de a quién se le dio el código."""

    note: str | None = Field(default=None, max_length=80)


@router.get("/invites")
async def get_invites(
    _admin: User = Depends(get_admin_user),
    session: AsyncSession = Depends(get_admin_session),
) -> list[InviteOut]:
    return [InviteOut(**row) for row in await invites_domain.list_invites(session)]


@router.post("/invites", status_code=201)
async def post_invite(
    body: CreateInviteIn,
    admin: User = Depends(get_admin_user),
    session: AsyncSession = Depends(get_admin_session),
) -> InviteOut:
    invite = await invites_domain.create_invite(session, created_by=admin.id, note=body.note)
    return InviteOut(
        code=invite.code,
        note=invite.note,
        created_at=invite.created_at.isoformat(),
        used_at=None,
        used_by_name=None,
        revoked_at=None,
        status="disponible",
    )


@router.delete("/invites/{code}", status_code=204)
async def delete_invite(
    code: str,
    _admin: User = Depends(get_admin_user),
    session: AsyncSession = Depends(get_admin_session),
) -> None:
    if not await invites_domain.revoke(session, invites_domain.normalize_code(code)):
        raise AppError(
            "INVITE_NOT_REVOCABLE",
            "Ese código no existe, ya se usó o ya estaba revocado.",
            status_code=404,
        )
    await session.commit()


# --------------------------------------------------------------------------- usuarios


class AdminUserOut(BaseModel):
    id: str
    display_name: str
    email: str
    role: str
    is_active: bool
    ai_enabled: bool
    created_at: str
    last_seen_at: str | None
    invited_with: str | None
    # Actividad, sin enseñar nada de lo registrado.
    logging_days: int
    last_log_date: str | None
    ai_used_today: int
    ai_used_30d: int


class UpdateUserIn(BaseModel):
    is_active: bool | None = None
    ai_enabled: bool | None = None


async def _ai_usage_today(user_ids: list[UUID]) -> dict[str, int]:
    """Peticiones de IA gastadas hoy por cada usuario, sumando todos los ámbitos.

    Sale de los mismos contadores de Redis que aplica la cuota, no de `ai_sessions`: la cuota
    se descuenta al encolar, así que un intento que falló también cuenta — es lo que el
    administrador necesita ver para decidir a quién deja usar la IA."""
    today = datetime.now(UTC).date().isoformat()
    keys = [f"iafood:quota:{scope}:{uid}:{today}" for uid in user_ids for scope in AI_SCOPES]
    if not keys:
        return {}
    values = await _redis.mget(keys)
    usage: dict[str, int] = {}
    for (uid, _scope), value in zip(
        [(u, s) for u in user_ids for s in AI_SCOPES], values, strict=True
    ):
        usage[str(uid)] = usage.get(str(uid), 0) + int(value or 0)
    return usage


@router.get("/users")
async def get_users(
    _admin: User = Depends(get_admin_user),
    session: AsyncSession = Depends(get_admin_session),
) -> list[AdminUserOut]:
    rows = (
        await session.execute(
            text("""
                SELECT u.id, u.display_name, u.email, u.role, u.is_active, u.ai_enabled,
                       u.created_at, u.last_seen_at, u.invited_with,
                       COALESCE(l.logging_days, 0) AS logging_days,
                       l.last_log_date,
                       COALESCE(s.ai_30d, 0) AS ai_30d
                FROM users u
                LEFT JOIN (
                  SELECT user_id, COUNT(DISTINCT log_date) AS logging_days,
                         MAX(log_date) AS last_log_date
                  FROM food_log GROUP BY user_id
                ) l ON l.user_id = u.id
                LEFT JOIN (
                  SELECT user_id, COUNT(*) AS ai_30d FROM ai_sessions
                  WHERE created_at >= now() - interval '30 days' GROUP BY user_id
                ) s ON s.user_id = u.id
                ORDER BY u.created_at
            """)
        )
    ).all()
    usage = await _ai_usage_today([r.id for r in rows])
    return [
        AdminUserOut(
            id=str(r.id),
            display_name=r.display_name,
            email=r.email,
            role=r.role,
            is_active=r.is_active,
            ai_enabled=r.ai_enabled,
            created_at=r.created_at.isoformat(),
            last_seen_at=r.last_seen_at.isoformat() if r.last_seen_at else None,
            invited_with=r.invited_with,
            logging_days=r.logging_days,
            last_log_date=r.last_log_date.isoformat() if r.last_log_date else None,
            ai_used_today=usage.get(str(r.id), 0),
            ai_used_30d=r.ai_30d,
        )
        for r in rows
    ]


@router.patch("/users/{user_id}")
async def patch_user(
    user_id: UUID,
    body: UpdateUserIn,
    admin: User = Depends(get_admin_user),
    session: AsyncSession = Depends(get_admin_session),
) -> AdminUserOut:
    user = await session.get(User, user_id)
    if user is None:
        raise AppError("USER_NOT_FOUND", "No existe ese usuario.", status_code=404)
    if body.is_active is False and user.id == admin.id:
        # Desactivarse a uno mismo deja la instancia sin administrador que pueda entrar.
        raise AppError(
            "CANNOT_DISABLE_SELF", "No puedes desactivar tu propia cuenta.", status_code=422
        )
    if body.is_active is not None:
        user.is_active = body.is_active
    if body.ai_enabled is not None:
        user.ai_enabled = body.ai_enabled
    await session.commit()
    users = await get_users(admin, session)
    return next(u for u in users if u.id == str(user_id))


# --------------------------------------------------------------------------- resumen


class OverviewOut(BaseModel):
    users_total: int
    users_active: int
    users_with_ai: int
    users_logging_last_7d: int
    invites_usable: int
    invite_only: bool
    # Uso de la app
    food_entries_today: int
    food_entries_7d: int
    new_users_30d: int
    top_foods_7d: list[dict]
    # Gasto de IA
    ai_used_today: int
    ai_instance_limit: int
    ai_sessions_30d: int
    ai_failed_7d: int
    # Salud
    foods_total: int
    database_size: str
    last_food_ingested_at: str | None


@router.get("/overview")
async def get_overview(
    _admin: User = Depends(get_admin_user),
    session: AsyncSession = Depends(get_admin_session),
) -> OverviewOut:
    counts = (
        await session.execute(
            text("""
                SELECT
                  (SELECT count(*) FROM users) AS users_total,
                  (SELECT count(*) FROM users WHERE is_active) AS users_active,
                  (SELECT count(*) FROM users WHERE ai_enabled AND is_active) AS users_with_ai,
                  (SELECT count(DISTINCT user_id) FROM food_log
                     WHERE log_date >= CURRENT_DATE - 6) AS users_logging_last_7d,
                  (SELECT count(*) FROM users
                     WHERE created_at >= now() - interval '30 days') AS new_users_30d,
                  (SELECT count(*) FROM food_log WHERE log_date = CURRENT_DATE)
                    AS food_entries_today,
                  (SELECT count(*) FROM food_log WHERE log_date >= CURRENT_DATE - 6)
                    AS food_entries_7d,
                  (SELECT count(*) FROM ai_sessions
                     WHERE created_at >= now() - interval '30 days') AS ai_sessions_30d,
                  (SELECT count(*) FROM ai_sessions
                     WHERE status = 'failed' AND created_at >= now() - interval '7 days')
                    AS ai_failed_7d,
                  (SELECT count(*) FROM foods) AS foods_total,
                  (SELECT pg_size_pretty(pg_database_size(current_database()))) AS db_size,
                  (SELECT max(created_at) FROM foods) AS last_food
            """)
        )
    ).one()

    top = (
        await session.execute(
            text("""
                SELECT f.name_es AS name, count(*) AS uses
                FROM food_log l JOIN foods f ON f.id = l.food_id
                WHERE l.log_date >= CURRENT_DATE - 6
                GROUP BY f.name_es ORDER BY uses DESC LIMIT 5
            """)
        )
    ).all()

    today = date.today().isoformat()
    instance_used = 0
    for scope in AI_SCOPES:
        instance_used += int(await _redis.get(f"iafood:quota:{scope}:instance:{today}") or 0)

    return OverviewOut(
        users_total=counts.users_total,
        users_active=counts.users_active,
        users_with_ai=counts.users_with_ai,
        users_logging_last_7d=counts.users_logging_last_7d,
        invites_usable=await invites_domain.count_usable(session),
        invite_only=load_app_settings().invite_only,
        food_entries_today=counts.food_entries_today,
        food_entries_7d=counts.food_entries_7d,
        new_users_30d=counts.new_users_30d,
        top_foods_7d=[{"name": r.name, "uses": r.uses} for r in top],
        ai_used_today=instance_used,
        ai_instance_limit=load_limits().instance_daily,
        ai_sessions_30d=counts.ai_sessions_30d,
        ai_failed_7d=counts.ai_failed_7d,
        foods_total=counts.foods_total,
        database_size=counts.db_size,
        last_food_ingested_at=counts.last_food.isoformat() if counts.last_food else None,
    )


class ActivityDay(BaseModel):
    date: str
    entries: int
    users: int


@router.get("/activity")
async def get_activity(
    days: int = 30,
    _admin: User = Depends(get_admin_user),
    session: AsyncSession = Depends(get_admin_session),
) -> list[ActivityDay]:
    """Registros y personas activas por día, para la gráfica del panel."""
    days = max(7, min(days, 365))
    rows = (
        await session.execute(
            text("""
                SELECT log_date, count(*) AS entries, count(DISTINCT user_id) AS users
                FROM food_log WHERE log_date >= CURRENT_DATE - (:back)::int
                GROUP BY log_date
            """),
            {"back": days - 1},
        )
    ).all()
    by_day = {r.log_date: (r.entries, r.users) for r in rows}
    start = date.today() - timedelta(days=days - 1)
    return [
        ActivityDay(
            date=(start + timedelta(days=i)).isoformat(),
            entries=by_day.get(start + timedelta(days=i), (0, 0))[0],
            users=by_day.get(start + timedelta(days=i), (0, 0))[1],
        )
        for i in range(days)
    ]
