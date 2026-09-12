"""Endpoints de iafood (sección 7.7). El trabajo real (la llamada al Claude
Agent SDK) corre en el `worker` (regla 19) — este router solo comprueba
consentimiento/cuotas, prepara y encola la petición, y expone el estado de
la sesión y las propuestas resultantes para aprobar/rechazar una a una
(R1: nada se aplica solo)."""

from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from myfood.ai.consent import require_ai_processing_consent
from myfood.ai.flows.diet_plan import request_diet_plan
from myfood.ai.quota import QuotaExceeded, check_and_consume_quota, reset_at_iso
from myfood.ai.schemas import AiSessionOut, ai_session_to_out
from myfood.db.models import AiProposal, AiSession, DietPlan, PlanDay, PlanItem, PlanMeal
from myfood.deps import get_current_user_id, get_db
from myfood.domain.food_candidates import compute_alternatives_for_item
from myfood.errors import AppError

router = APIRouter(prefix="/ai", tags=["ai"])


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


async def _materialize_proposal(session: AsyncSession, user_id: UUID, proposal: AiProposal) -> None:
    """Vuelca la propuesta de un día (`scope='meal'`) en `plan_days`/
    `plan_meals`/`plan_items` reales del `DietPlan` que ya creó el worker —
    las mismas tablas que usa el motor determinista, con las mismas
    alternativas precalculadas (sección "Plan de Actuación": cualquier
    dieta que salga de MyFood cuadra igual, venga de la IA o no)."""
    payload = proposal.payload
    plan = await session.get(DietPlan, UUID(payload["diet_plan_id"]))
    if plan is None or plan.user_id != user_id:
        raise AppError("PLAN_NOT_FOUND", "El plan asociado ya no existe.", status_code=404)

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
