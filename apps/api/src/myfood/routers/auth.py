from datetime import UTC, datetime
from uuid import UUID

import pyotp
from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from myfood.app_settings import load_app_settings
from myfood.db.models import Consent, User
from myfood.db.session import get_session
from myfood.deps import get_current_user_id, get_db
from myfood.domain import invites
from myfood.errors import AppError
from myfood.ratelimit import (
    client_ip,
    guard,
    login_rules,
    password_confirm_rules,
    record_failure,
    reset,
    totp_rules,
)
from myfood.routers.consents import REQUIRED_CONSENTS
from myfood.security import (
    SESSION_COOKIE_NAME,
    create_mfa_challenge,
    create_session,
    destroy_mfa_challenge,
    destroy_session,
    get_mfa_challenge_user_id,
    hash_password,
    verify_password,
)

_TOTP_ISSUER = "MyFood"

router = APIRouter(prefix="/auth", tags=["auth"])


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)
    display_name: str = Field(min_length=1, max_length=200)
    # Obligatorio mientras la instancia esté en «solo con invitación».
    invite_code: str | None = None


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


def _set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        httponly=True,
        secure=True,
        samesite="lax",
        max_age=30 * 24 * 60 * 60,
    )


@router.post("/register", status_code=201)
async def register(
    body: RegisterRequest, response: Response, session: AsyncSession = Depends(get_session)
) -> dict:
    settings = load_app_settings()
    code = invites.normalize_code(body.invite_code or "")
    if settings.invite_only:
        if not code or not await invites.is_usable(session, code):
            raise AppError(
                "INVITE_REQUIRED",
                "Esta app es por invitación: pide un código al administrador.",
                403,
            )

    existing = await session.scalar(select(User).where(User.email == body.email))
    if existing is not None:
        raise AppError("EMAIL_ALREADY_REGISTERED", "Ya existe una cuenta con ese email.", 409)

    user = User(
        email=body.email,
        password_hash=hash_password(body.password),
        display_name=body.display_name,
        ai_enabled=settings.ai_enabled_by_default,
    )
    session.add(user)
    await session.flush()

    if settings.invite_only:
        # Se reclama en el último momento y de forma atómica: entre la comprobación de
        # arriba y este punto, otro registro simultáneo puede haberlo gastado.
        if not await invites.claim(session, code, user_id=user.id):
            await session.rollback()
            raise AppError(
                "INVITE_REQUIRED",
                "Ese código ya no es válido: pide uno nuevo al administrador.",
                403,
            )
        user.invited_with = code
    await session.commit()

    token = await create_session(user.id)
    _set_session_cookie(response, token)
    return {"id": str(user.id), "email": user.email, "display_name": user.display_name}


@router.post("/login")
async def login(
    body: LoginRequest,
    request: Request,
    response: Response,
    session: AsyncSession = Depends(get_session),
) -> dict:
    rules = login_rules(body.email, client_ip(request))
    await guard(*rules)
    user = await session.scalar(select(User).where(User.email == body.email))
    if user is None or not verify_password(body.password, user.password_hash):
        await record_failure(*rules)
        raise AppError("INVALID_CREDENTIALS", "Email o contraseña incorrectos.", 401)
    if not user.is_active:
        raise AppError("ACCOUNT_DISABLED", "Esta cuenta está desactivada.", 403)
    # Un acierto reinicia solo el contador del par (email, IP): los fallos de otras IPs
    # contra esta misma cuenta siguen contando.
    await reset(rules[0])
    # Se anota aquí y no en cada petición: el panel necesita saber quién sigue usando la app,
    # y escribir en `users` en cada llamada sería un INSERT/UPDATE por request.
    user.last_seen_at = datetime.now(UTC)
    await session.commit()

    if user.totp_enabled:
        # Contraseña correcta, pero no se emite sesión todavía: hace falta
        # el código TOTP en /auth/2fa/verify-login dentro de los próximos
        # 5 minutos (ver security.py: create_mfa_challenge).
        challenge = await create_mfa_challenge(user.id)
        return {"mfa_required": True, "mfa_token": challenge}

    token = await create_session(user.id)
    _set_session_cookie(response, token)
    return {"id": str(user.id), "email": user.email, "display_name": user.display_name}


class Verify2faLoginRequest(BaseModel):
    mfa_token: str
    code: str = Field(min_length=6, max_length=6)


@router.post("/2fa/verify-login")
async def verify_2fa_login(
    body: Verify2faLoginRequest,
    response: Response,
    session: AsyncSession = Depends(get_session),
) -> dict:
    user_id = await get_mfa_challenge_user_id(body.mfa_token)
    if user_id is None:
        raise AppError(
            "MFA_CHALLENGE_EXPIRED", "El código ha caducado, inicia sesión de nuevo.", 401
        )
    user = await session.get(User, user_id)
    if user is None or not user.totp_enabled or user.totp_secret is None:
        raise AppError(
            "MFA_CHALLENGE_EXPIRED", "El código ha caducado, inicia sesión de nuevo.", 401
        )
    # Un TOTP tiene solo un millón de combinaciones: sin límite se puede adivinar.
    rules = totp_rules(body.mfa_token, user.id)
    await guard(*rules)
    if not pyotp.TOTP(user.totp_secret).verify(body.code, valid_window=1):
        await record_failure(*rules)
        raise AppError("INVALID_TOTP_CODE", "Código incorrecto.", 401)
    await reset(*rules)

    # Un solo uso: si no se invalidara, un código válido reenviado (o el
    # mismo mfa_token reutilizado) podría canjearse varias veces dentro de
    # la ventana de 5 minutos.
    await destroy_mfa_challenge(body.mfa_token)
    token = await create_session(user.id)
    _set_session_cookie(response, token)
    return {"id": str(user.id), "email": user.email, "display_name": user.display_name}


class TotpSetupResponse(BaseModel):
    secret: str
    otpauth_uri: str


@router.post("/2fa/setup")
async def setup_totp(
    user_id: UUID = Depends(get_current_user_id), session: AsyncSession = Depends(get_db)
) -> TotpSetupResponse:
    """Genera (o regenera) un secreto TOTP sin activarlo todavía — hace
    falta confirmar un código real en /auth/2fa/confirm para activarlo, así
    que llamar esto dos veces seguidas sin confirmar es seguro (invalida el
    anterior sin más efecto)."""
    user = await session.get(User, user_id)
    secret = pyotp.random_base32()
    user.totp_secret = secret
    user.totp_enabled = False
    await session.commit()
    uri = pyotp.TOTP(secret).provisioning_uri(name=user.email, issuer_name=_TOTP_ISSUER)
    return TotpSetupResponse(secret=secret, otpauth_uri=uri)


class TotpConfirmRequest(BaseModel):
    code: str = Field(min_length=6, max_length=6)


@router.post("/2fa/confirm")
async def confirm_totp(
    body: TotpConfirmRequest,
    user_id: UUID = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_db),
) -> dict:
    user = await session.get(User, user_id)
    if user.totp_secret is None:
        raise AppError("TOTP_NOT_SETUP", "Genera un secreto en /auth/2fa/setup primero.", 422)
    rules = password_confirm_rules("2fa-confirm", user_id)
    await guard(*rules)
    if not pyotp.TOTP(user.totp_secret).verify(body.code, valid_window=1):
        await record_failure(*rules)
        raise AppError("INVALID_TOTP_CODE", "Código incorrecto.", 401)
    await reset(*rules)
    user.totp_enabled = True
    await session.commit()
    return {"totp_enabled": True}


class TotpDisableRequest(BaseModel):
    password: str


@router.post("/2fa/disable")
async def disable_totp(
    body: TotpDisableRequest,
    user_id: UUID = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_db),
) -> dict:
    user = await session.get(User, user_id)
    rules = password_confirm_rules("2fa-disable", user_id)
    await guard(*rules)
    if not verify_password(body.password, user.password_hash):
        await record_failure(*rules)
        raise AppError("INVALID_CREDENTIALS", "Contraseña incorrecta.", 401)
    await reset(*rules)
    user.totp_enabled = False
    user.totp_secret = None
    await session.commit()
    return {"totp_enabled": False}


@router.post("/logout", status_code=204)
async def logout(request: Request, response: Response) -> None:
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if token:
        await destroy_session(token)
    response.delete_cookie(SESSION_COOKIE_NAME)


@router.get("/me")
async def me(
    user_id: UUID = Depends(get_current_user_id), session: AsyncSession = Depends(get_session)
) -> dict:
    user = await session.get(User, user_id)
    if user is None:
        raise AppError("NOT_AUTHENTICATED", "Se requiere iniciar sesión.", 401)
    granted_consents = list(
        await session.scalars(
            select(Consent.kind).where(Consent.user_id == user_id, Consent.revoked_at.is_(None))
        )
    )
    return {
        "id": str(user.id),
        "email": user.email,
        "display_name": user.display_name,
        "role": user.role,
        "granted_consents": granted_consents,
        # Los obligatorios que faltan (spec 7.1): la web bloquea el uso hasta aceptarlos.
        "pending_consents": [c for c in REQUIRED_CONSENTS if c not in granted_consents],
        "totp_enabled": user.totp_enabled,
    }


class PublicConfigOut(BaseModel):
    """Lo que la pantalla de registro necesita saber ANTES de que nadie inicie sesión."""

    invite_only: bool


@router.get("/config")
async def public_config() -> PublicConfigOut:
    return PublicConfigOut(invite_only=load_app_settings().invite_only)
