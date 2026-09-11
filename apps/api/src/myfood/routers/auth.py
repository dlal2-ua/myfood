from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from myfood.db.models import Consent, User
from myfood.db.session import get_session
from myfood.deps import get_current_user_id
from myfood.errors import AppError
from myfood.security import (
    SESSION_COOKIE_NAME,
    create_session,
    destroy_session,
    hash_password,
    verify_password,
)

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

    token = await create_session(user.id)
    _set_session_cookie(response, token)
    return {"id": str(user.id), "email": user.email, "display_name": user.display_name}


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
    }
