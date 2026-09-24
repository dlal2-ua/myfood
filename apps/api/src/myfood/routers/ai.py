"""Endpoints de iafood (sección 7.7). El trabajo real (la llamada al Claude
Agent SDK) corre en el `worker` (regla 19) — este router solo comprueba
consentimiento/cuotas, prepara y encola la petición, y expone el estado de
la sesión y las propuestas resultantes para aprobar/rechazar una a una
(R1: nada se aplica solo)."""

from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from myfood.ai.consent import require_ai_processing_consent
from myfood.ai.flows.diet_plan import request_diet_plan
from myfood.ai.flows.supplement_suggestion import request_supplement_suggestion
from myfood.ai.limits import load_limits
from myfood.ai.quota import QuotaExceeded, check_and_consume_quota, quota_status, reset_at_iso
from myfood.ai.schemas import AiSessionOut, ai_session_to_out
from myfood.db.models import (
    AiProposal,
    AiSession,
    DietPlan,
    PantryItem,
    PlanDay,
    PlanItem,
    PlanMeal,
    Supplement,
)
from myfood.deps import get_current_user_id, get_db
from myfood.domain import diary_proposal
from myfood.domain.food_candidates import compute_alternatives_for_item
from myfood.errors import AppError

router = APIRouter(prefix="/ai", tags=["ai"])


class QuotaOut(BaseModel):
    scope: str
    used: int
    limit: int
    remaining: int
    reset_at: str
    # Tope compartido por toda la instancia; `None` en los ámbitos que no lo aplican.
    instance_limit: int | None = None
    instance_remaining: int | None = None


@router.get("/quota")
async def get_quota(
    scope: Literal[
        "smart_log", "chat", "diet_plan", "supplement_suggestion", "plate_photo"
    ] = "smart_log",
    user_id: UUID = Depends(get_current_user_id),
) -> QuotaOut:
    """Cuánta cuota de iafood le queda hoy al usuario en ese ámbito, sin gastarla.

    La pantalla lo enseña ANTES de pulsar: la cuota se descuenta al encolar la petición,
    así que insistir con el mismo texto la agota sin traer ninguna respuesta nueva."""
    limits = load_limits()
    if scope == "chat":
        status = await quota_status(
            user_id,
            scope="chat",
            per_profile_limit=limits.chat_messages_per_profile_daily,
            enforce_instance=False,
        )
    elif scope == "plate_photo":
        status = await quota_status(
            user_id, scope="plate_photo", per_profile_limit=limits.plate_photo_per_profile_daily
        )
    else:
        status = await quota_status(user_id, scope=scope)
    return QuotaOut(**status)


class RequestDietPlanIn(BaseModel):
    num_days: int = Field(default=7, ge=1, le=7)


@router.post("/diet-plan", status_code=202)
async def create_diet_plan_request(
    body: RequestDietPlanIn,
    user_id: UUID = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_db),
) -> AiSessionOut:
    await require_ai_processing_consent(session, user_id)
    try:
        await check_and_consume_quota(user_id)
    except QuotaExceeded as exc:
        raise AppError(
            exc.code, exc.message, status_code=429, details={"reset_at": reset_at_iso()}
        ) from exc

    ai_session = await request_diet_plan(session, user_id, num_days=body.num_days)
    return ai_session_to_out(ai_session)


@router.post("/supplement-suggestions", status_code=202)
async def create_supplement_suggestion_request(
    user_id: UUID = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_db),
) -> AiSessionOut:
    """Sugerencia de suplementos (sección 10.7): solo bajo petición explícita, con la lista blanca
    y los bloqueos por embarazo, patología o edad (`403 SUPPLEMENT_ADVICE_BLOCKED`)."""
    await require_ai_processing_consent(session, user_id)
    try:
        await check_and_consume_quota(user_id, scope="supplement_suggestion")
    except QuotaExceeded as exc:
        raise AppError(
            exc.code, exc.message, status_code=429, details={"reset_at": reset_at_iso()}
        ) from exc
    ai_session = await request_supplement_suggestion(session, user_id)
    return ai_session_to_out(ai_session)


async def _get_owned_session(session: AsyncSession, user_id: UUID, session_id: UUID) -> AiSession:
    ai_session = await session.get(AiSession, session_id)
    if ai_session is None or ai_session.user_id != user_id:
        raise AppError("AI_SESSION_NOT_FOUND", "No existe esa sesión.", status_code=404)
    return ai_session


@router.get("/sessions/{session_id}")
async def get_session_status(
    session_id: UUID,
    user_id: UUID = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_db),
) -> AiSessionOut:
    ai_session = await _get_owned_session(session, user_id, session_id)
    return ai_session_to_out(ai_session)


class AiProposalOut(BaseModel):
    id: UUID
    ai_session_id: UUID
    scope: str
    payload: dict
    rationale: str | None
    status: str


def _proposal_to_out(proposal: AiProposal) -> AiProposalOut:
    return AiProposalOut(
        id=proposal.id,
        ai_session_id=proposal.ai_session_id,
        scope=proposal.scope,
        payload=proposal.payload,
        rationale=proposal.rationale,
        status=proposal.status,
    )


@router.get("/proposals")
async def list_proposals(
    status: str | None = None,
    user_id: UUID = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_db),
) -> list[AiProposalOut]:
    stmt = select(AiProposal).where(AiProposal.user_id == user_id)
    if status is not None:
        stmt = stmt.where(AiProposal.status == status)
    rows = await session.scalars(stmt)
    return [_proposal_to_out(p) for p in rows]


async def _get_owned_proposal(
    session: AsyncSession, user_id: UUID, proposal_id: UUID
) -> AiProposal:
    proposal = await session.get(AiProposal, proposal_id)
    if proposal is None or proposal.user_id != user_id:
        raise AppError("PROPOSAL_NOT_FOUND", "No existe esa propuesta.", status_code=404)
    return proposal


async def _materialize_pantry_proposal(session: AsyncSession, user_id: UUID, payload: dict) -> None:
    """Propuesta del chat (`scope='pantry'`, sección 24.3: `add_to_pantry`)
    — mismo criterio de "sumar si ya existe" que `routers/pantry.py::add_pantry_item`."""
    for entry in payload["items"]:
        food_id = UUID(entry["food_id"])
        existing = await session.scalar(
            select(PantryItem).where(PantryItem.user_id == user_id, PantryItem.food_id == food_id)
        )
        if existing is not None:
            existing.quantity_g = float(existing.quantity_g) + entry["quantity_g"]
        else:
            session.add(
                PantryItem(user_id=user_id, food_id=food_id, quantity_g=entry["quantity_g"])
            )


async def _materialize_proposal(session: AsyncSession, user_id: UUID, proposal: AiProposal) -> None:
    """Vuelca la propuesta de un día en `plan_days`/`plan_meals`/`plan_items`
    reales del `DietPlan` — las mismas tablas que usa el motor determinista,
    con las mismas alternativas precalculadas (sección "Plan de Actuación":
    cualquier dieta que salga de MyFood cuadra igual, venga de la IA o no).

    `scope='meal'`: día nuevo de un plan recién generado por iafood — crea
    el `PlanDay`. `scope='day'`: cambio del chat sobre un plan YA existente
    (sección 24.3, `propose_day_change`) — el `PlanDay` ya existe, así que
    se sustituyen sus comidas (borra `plan_meals` del día y reinserta,
    mismo criterio que `batch_cook`, `routers/diet_plans.py`, solo que para
    el día completo en vez de una comida suelta). `scope='pantry'`: no toca
    planes, va aparte."""
    if proposal.scope == "diary":
        # Lo que el chat propuso apuntar en el diario: se guardan los números que el usuario
        # acaba de aceptar, tal cual, sin recalcularlos.
        await diary_proposal.materialize(session, user_id, proposal.payload)
        return
    if proposal.scope == "pantry":
        await _materialize_pantry_proposal(session, user_id, proposal.payload)
        return
    if proposal.scope == "supplement":
        payload = proposal.payload
        session.add(
            Supplement(
                user_id=user_id,
                name=payload["name_es"],
                type=payload["type"],
                dose_amount=payload["dose_amount"],
                dose_unit=payload["dose_unit"],
                notes="Sugerido por iafood según tu ingesta (orientativo, no es consejo médico).",
            )
        )
        return

    payload = proposal.payload
    plan = await session.get(DietPlan, UUID(payload["diet_plan_id"]))
    if plan is None or plan.user_id != user_id:
        raise AppError("PLAN_NOT_FOUND", "El plan asociado ya no existe.", status_code=404)

    if proposal.scope == "day":
        plan_day = await session.scalar(
            select(PlanDay).where(
                PlanDay.plan_id == plan.id, PlanDay.day_index == payload["day_index"]
            )
        )
        if plan_day is None:
            raise AppError(
                "PLAN_DAY_NOT_FOUND", "Ese día ya no existe en el plan.", status_code=404
            )
        await session.execute(delete(PlanMeal).where(PlanMeal.plan_day_id == plan_day.id))
        await session.flush()
    else:  # scope == "meal"
        plan_day = PlanDay(plan_id=plan.id, day_index=payload["day_index"])
        session.add(plan_day)
        await session.flush()

    for sort_order, meal in enumerate(payload["meals"]):
        plan_meal = PlanMeal(
            plan_day_id=plan_day.id, meal_type=meal["meal_type"], sort_order=sort_order
        )
        session.add(plan_meal)
        await session.flush()
        for item in meal["items"]:
            food_uuid = UUID(item["food_id"])
            plan_item = PlanItem(plan_meal_id=plan_meal.id, food_id=food_uuid, grams=item["grams"])
            session.add(plan_item)
            await session.flush()
            await compute_alternatives_for_item(
                session, plan_item.id, food_uuid, item["grams"], user_id
            )


@router.post("/proposals/{proposal_id}/approve")
async def approve_proposal(
    proposal_id: UUID,
    user_id: UUID = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_db),
) -> AiProposalOut:
    proposal = await _get_owned_proposal(session, user_id, proposal_id)
    if proposal.status != "pending":
        raise AppError("PROPOSAL_NOT_PENDING", "Esta propuesta ya se decidió.", status_code=422)

    await _materialize_proposal(session, user_id, proposal)

    proposal.status = "approved"
    proposal.decided_at = datetime.now(UTC)
    await session.commit()
    await session.refresh(proposal)
    return _proposal_to_out(proposal)


@router.post("/proposals/{proposal_id}/reject")
async def reject_proposal(
    proposal_id: UUID,
    user_id: UUID = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_db),
) -> AiProposalOut:
    proposal = await _get_owned_proposal(session, user_id, proposal_id)
    if proposal.status != "pending":
        raise AppError("PROPOSAL_NOT_PENDING", "Esta propuesta ya se decidió.", status_code=422)

    proposal.status = "rejected"
    proposal.decided_at = datetime.now(UTC)
    await session.commit()
    await session.refresh(proposal)
    return _proposal_to_out(proposal)
