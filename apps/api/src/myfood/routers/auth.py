from uuid import UUID

import pyotp
from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from myfood.db.models import Consent, User
from myfood.db.session import get_session
from myfood.deps import get_current_user_id, get_db
from myfood.errors import AppError
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
    existing = await session.scalar(select(User).where(User.email == body.email))
    if existing is not None:
        raise AppError("EMAIL_ALREADY_REGISTERED", "Ya existe una cuenta con ese email.", 409)

    user = User(
        email=body.email,
        password_hash=hash_password(body.password),
        display_name=body.display_name,
    )
    session.add(user)
    await session.commit()

    token = await create_session(user.id)
    _set_session_cookie(response, token)
    return {"id": str(user.id), "email": user.email, "display_name": user.display_name}


@router.post("/login")
async def login(
    body: LoginRequest, response: Response, session: AsyncSession = Depends(get_session)
) -> dict:
    user = await session.scalar(select(User).where(User.email == body.email))
    if user is None or not verify_password(body.password, user.password_hash):
        raise AppError("INVALID_CREDENTIALS", "Email o contraseña incorrectos.", 401)
    if not user.is_active:
        raise AppError("ACCOUNT_DISABLED", "Esta cuenta está desactivada.", 403)

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
    if not pyotp.TOTP(user.totp_secret).verify(body.code, valid_window=1):
        raise AppError("INVALID_TOTP_CODE", "Código incorrecto.", 401)

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
    if not pyotp.TOTP(user.totp_secret).verify(body.code, valid_window=1):
        raise AppError("INVALID_TOTP_CODE", "Código incorrecto.", 401)
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
    if not verify_password(body.password, user.password_hash):
        raise AppError("INVALID_CREDENTIALS", "Contraseña incorrecta.", 401)
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
    pending_consents = await session.scalars(
        select(Consent.kind).where(Consent.user_id == user_id, Consent.revoked_at.is_(None))
    )
    return {
        "id": str(user.id),
        "email": user.email,
        "display_name": user.display_name,
        "role": user.role,
        "granted_consents": list(pending_consents),
        "totp_enabled": user.totp_enabled,
    }
