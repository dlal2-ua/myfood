"""Modo familia (Fase 7, documento 1): un hogar comparte despensa y lista
de la compra (RLS ampliada, migración 0011) — cada miembro sigue siendo
dueño solo de lo que añade él mismo; el resto de datos (perfil, registro,
planes...) no se comparte, sigue estrictamente privado por usuario."""

import secrets
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from myfood.db.models import Household, HouseholdMember, User
from myfood.db.session import AdminSessionLocal
from myfood.deps import get_current_user_id, get_db
from myfood.errors import AppError

router = APIRouter(prefix="/household", tags=["household"])


class HouseholdMemberOut(BaseModel):
    user_id: UUID
    display_name: str
    email: str
    joined_at: str


class HouseholdOut(BaseModel):
    id: UUID
    name: str
    invite_code: str
    members: list[HouseholdMemberOut]


async def _membership(session: AsyncSession, user_id: UUID) -> HouseholdMember | None:
    return await session.get(HouseholdMember, user_id)


async def _to_out(session: AsyncSession, household: Household) -> HouseholdOut:
    rows = (
        await session.execute(
            select(HouseholdMember, User)
            .join(User, User.id == HouseholdMember.user_id)
            .where(HouseholdMember.household_id == household.id)
            .order_by(HouseholdMember.joined_at)
        )
    ).all()
    return HouseholdOut(
        id=household.id,
        name=household.name,
        invite_code=household.invite_code,
        members=[
            HouseholdMemberOut(
                user_id=member.user_id,
                display_name=user.display_name,
                email=user.email,
                joined_at=member.joined_at.isoformat(),
            )
            for member, user in rows
        ],
    )


@router.get("")
async def get_my_household(
    user_id: UUID = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_db),
) -> HouseholdOut | None:
    membership = await _membership(session, user_id)
    if membership is None:
        return None
    household = await session.get(Household, membership.household_id)
    if household is None:
        return None
    return await _to_out(session, household)


class HouseholdIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)


@router.post("", status_code=201)
async def create_household(
    body: HouseholdIn,
    user_id: UUID = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_db),
) -> HouseholdOut:
    if await _membership(session, user_id) is not None:
        raise AppError(
            "ALREADY_IN_HOUSEHOLD", "Ya perteneces a un hogar — sal de él primero.", 422
        )

    household = Household(
        name=body.name, invite_code=secrets.token_hex(4).upper(), created_by=user_id
    )
    session.add(household)
    await session.flush()
    session.add(HouseholdMember(household_id=household.id, user_id=user_id))
    await session.commit()
    await session.refresh(household)
    return await _to_out(session, household)


class JoinHouseholdIn(BaseModel):
    invite_code: str = Field(min_length=1, max_length=20)


@router.post("/join")
async def join_household(
    body: JoinHouseholdIn,
    user_id: UUID = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_db),
) -> HouseholdOut:
    if await _membership(session, user_id) is not None:
        raise AppError(
            "ALREADY_IN_HOUSEHOLD", "Ya perteneces a un hogar — sal de él primero.", 422
        )

    # Sesión admin (sin RLS) solo para esta búsqueda: antes de unirse, el
    # usuario todavía no es miembro de ningún hogar, así que la RLS normal
    # le impide VER la fila del hogar al que quiere entrar — el propio
    # código de invitación (un secreto compartido) es la autorización real
    # aquí, no la pertenencia previa.
    async with AdminSessionLocal() as admin_session:
        household_id = await admin_session.scalar(
            select(Household.id).where(Household.invite_code == body.invite_code.upper())
        )
    if household_id is None:
        raise AppError("INVITE_CODE_NOT_FOUND", "No existe ningún hogar con ese código.", 404)

    session.add(HouseholdMember(household_id=household_id, user_id=user_id))
    await session.commit()

    household = await session.get(Household, household_id)
    return await _to_out(session, household)


@router.post("/leave", status_code=204)
async def leave_household(
    user_id: UUID = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_db),
) -> None:
    membership = await _membership(session, user_id)
    if membership is None:
        raise AppError("NOT_IN_HOUSEHOLD", "No perteneces a ningún hogar.", 422)

    household_id = membership.household_id
    await session.delete(membership)
    await session.commit()

    # Tras salir, la RLS de esta sesión ya no deja ver a los demás
    # miembros de ese hogar (con razón: ya no perteneces a él) — se
    # comprueba con una sesión admin (sin RLS) si el hogar se ha quedado
    # vacío para poder borrarlo, no porque la sesión del usuario no vea
    # nada.
    async with AdminSessionLocal() as admin_session:
        remaining = await admin_session.scalar(
            select(HouseholdMember).where(HouseholdMember.household_id == household_id)
        )
        if remaining is None:
            household = await admin_session.get(Household, household_id)
            if household is not None:
                await admin_session.delete(household)
                await admin_session.commit()
