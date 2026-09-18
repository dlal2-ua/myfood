"""Divide el turno de chat en las dos mitades de la regla 19:
`request_chat_message` corre en el proceso `api` (valida, guarda el audio
en Redis sin tocar disco, crea el `ai_session`, encola) y `process_chat_job`
corre en el `worker` (transcribe si hace falta y es la única función de
chat que invoca `ai/agent.run_agent`, vía `chat/agent_loop.py`).

Desviación deliberada del patrón 202+polling del resto de iafood: la
especificación (sección 7.9/24.3) diseña `POST /chat/message` como una
respuesta SÍNCRONA, con su propio timeout de turno (sección 24.5, 20s) — no
tiene sentido pedirle a un chat que haga polling de cada mensaje. El
proceso `api` sigue sin llamar nunca a Whisper ni al Agent SDK: encola
igual que siempre y solo espera el resultado con un `BRPOP` de Redis
(`ai/queue.py::wait_for_chat_result`, operación local, no una llamada a un
proveedor externo) hasta agotar ese timeout.
"""

from __future__ import annotations

import uuid
from datetime import date
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from myfood.ai import client as ai_client
from myfood.ai.agent import AiAgentError
from myfood.ai.queue import enqueue_chat_job, pop_chat_audio, push_chat_result, store_chat_audio
from myfood.ai.validator import validate_day_totals, validate_structure
from myfood.chat.agent_loop import ChatTurnResult, run_chat_turn
from myfood.chat.transcribe import TranscriptionUnavailable, transcribe
from myfood.db.models import (
    AiProposal,
    AiSession,
    BodyMeasurement,
    ChatMessage,
    DietPlan,
    Food,
    Profile,
)
from myfood.db.session import AdminSessionLocal
from myfood.domain import formulas
from myfood.domain.diet_engine import DayTargets, solve_day_with_fixed_items
from myfood.domain.quantity_text import resolve_grams
from myfood.errors import AppError

_MAX_AUDIO_BYTES = 15 * 1024 * 1024


async def request_chat_message(
    session: AsyncSession, user_id: UUID, *, text: str | None, audio_bytes: bytes | None
) -> AiSession:
    """Corre en el proceso `api` (regla 19) — nunca transcribe ni llama al
    proveedor de IA, solo prepara todo lo determinista y encola."""
    credential_status = await ai_client.get_credential_status(session)
    if not credential_status.configured:
        raise AppError(
            "AI_NOT_CONFIGURED",
            "El administrador todavía no ha configurado la credencial de iafood.",
            status_code=503,
        )

    if audio_bytes is not None:
        if len(audio_bytes) > _MAX_AUDIO_BYTES:
            raise AppError(
                "AUDIO_TOO_LARGE", "La nota de voz es demasiado larga.", status_code=422
            )
        source = "voice"
    elif text is not None and text.strip():
        source = "text"
    else:
        raise AppError(
            "EMPTY_MESSAGE", "Escribe un mensaje o adjunta una nota de voz.", status_code=422
        )

    ai_session = AiSession(
        user_id=user_id,
        kind="chat_edit",
        status="running",
        request_payload={"source": source, "text": text if source == "text" else None},
    )
    session.add(ai_session)
    await session.commit()
    await session.refresh(ai_session)

    if audio_bytes is not None:
        # Nunca a disco (R2, sección 24) — Redis con TTL corto, solo hasta
        # que el worker lo transcriba; se borra en cuanto se lee.
        await store_chat_audio(str(ai_session.id), audio_bytes)

    await enqueue_chat_job(str(ai_session.id))
    return ai_session


async def _latest_weight_kg(session: AsyncSession, user_id: UUID) -> float | None:
    stmt = (
        select(BodyMeasurement)
        .where(BodyMeasurement.user_id == user_id, BodyMeasurement.weight_kg.is_not(None))
        .order_by(BodyMeasurement.measured_on.desc())
        .limit(1)
    )
    measurement = await session.scalar(stmt)
    return float(measurement.weight_kg) if measurement else None


def _age_years(birth_date: date) -> float:
    return (date.today() - birth_date).days / 365.25


async def _build_day_change_proposal(
    session: AsyncSession, user_id: UUID, ai_session: AiSession, turn: ChatTurnResult
) -> tuple[dict | None, str | None]:
    """Mapea alias→food_id, resuelve gramos con el optimizador (R1) y valida
    (R1/R6) exactamente igual que el resto de iafood (`ai/flows/diet_plan.py`)
    — reutilizando las mismas `validate_structure`/`validate_day_totals` en
    vez de duplicar la lógica de validación. Nunca aplica nada: si todo
    cuadra, deja una `ai_proposal` pendiente (scope='day') para que el
    usuario la apruebe en el propio hilo (sección 24.3)."""
    args = turn.day_change_args
    assert args is not None
    try:
        target_date = date.fromisoformat(args["date"])
    except (KeyError, ValueError):
        return None, "No entendí para qué fecha querías ese cambio."

    plan = await session.scalar(
        select(DietPlan).where(DietPlan.user_id == user_id, DietPlan.status == "active")
    )
    if plan is None:
        return None, (
            "No tienes ningún plan activo ahora mismo, así que no puedo proponer ese cambio."
        )
    day_index = (target_date - plan.start_date).days
    if day_index < 0 or (plan.end_date is not None and target_date > plan.end_date):
        return None, "Esa fecha no está dentro de tu plan activo."

    meal_types = [meal.get("meal_type") for meal in args.get("meals", [])]
    alias_to_food_id = {alias: candidate.id for alias, candidate in turn.alias_to_candidate.items()}
    plan_args = {"days": [{"day_index": day_index, "meals": args["meals"]}]}
    struct_errors, resolved_by_day = await validate_structure(
        session,
        plan_args,
        alias_to_food_id=alias_to_food_id,
        user_id=user_id,
        expected_num_days=1,
        expected_meal_types=meal_types,
    )
    if struct_errors:
        return None, "No puedo proponer ese cambio: " + "; ".join(e.message for e in struct_errors)

    candidate_by_food_id = {c.id: c for c in turn.alias_to_candidate.values()}
    items_by_meal = {
        meal_type: [candidate_by_food_id[food_id] for food_id in food_ids]
        for meal_type, food_ids in resolved_by_day[day_index].items()
        if food_ids
    }
    targets = DayTargets(
        kcal=float(plan.target_kcal),
        protein_g=float(plan.target_protein_g),
        fat_g=float(plan.target_fat_g),
        carbs_g=float(plan.target_carbs_g),
    )
    day_plan = solve_day_with_fixed_items(items_by_meal, targets)
    if not day_plan.feasible:
        return None, "No consigo cuadrar ese cambio numéricamente con lo que tienes disponible."

    profile = await session.get(Profile, user_id)
    weight_kg = await _latest_weight_kg(session, user_id)
    if (
        profile is None
        or profile.sex is None
        or profile.birth_date is None
        or profile.height_cm is None
        or weight_kg is None
    ):
        return None, "Completa tu perfil y registra tu peso antes de pedirme cambios en el plan."

    safety_floor_kcal = max(
        formulas.bmr_mifflin(
            profile.sex, weight_kg, float(profile.height_cm), _age_years(profile.birth_date)
        ),
        1200 if profile.sex == "female" else 1500,
    )
    min_fat_g = weight_kg * 0.5
    day_errors = validate_day_totals(
        day_plan.totals, targets, safety_floor_kcal=safety_floor_kcal, min_fat_g=min_fat_g
    )
    if day_errors:
        if any(e.code == "BELOW_SAFETY_FLOOR" for e in day_errors):
            return None, (
                "No puedo proponer ese cambio: te dejaría por debajo de tu suelo de "
                "seguridad calórico, aunque me lo pidas explícitamente."
            )
        return None, "No puedo proponer ese cambio: " + "; ".join(e.message for e in day_errors)

    payload = {
        "diet_plan_id": str(plan.id),
        "day_index": day_index,
        "meals": [
            {
                "meal_type": meal.meal_type,
                "items": [{"food_id": item.food_id, "grams": item.grams} for item in meal.items],
            }
            for meal in day_plan.meals
        ],
    }
    proposal = AiProposal(
        ai_session_id=ai_session.id,
        user_id=user_id,
        scope="day",
        payload=payload,
        rationale=None,
        status="pending",
    )
    session.add(proposal)
    await session.flush()
    return {"scope": "day", "ai_proposal_id": str(proposal.id), "payload": payload}, None


async def _build_pantry_proposal(
    session: AsyncSession, user_id: UUID, ai_session: AiSession, turn: ChatTurnResult
) -> dict | None:
    """Igual que `ai/flows/receipt_scan.py`: los gramos de partida vienen de
    `domain/quantity_text.resolve_grams`, nunca calculados por la IA (R1)."""
    args = turn.pantry_args
    assert args is not None
    items_out = []
    for entry in args.get("items", []):
        candidate = turn.alias_to_candidate.get(entry.get("alias"))
        if candidate is None:
            continue
        food = await session.get(Food, uuid.UUID(candidate.id))
        serving_size_g = float(food.serving_size_g) if food and food.serving_size_g else None
        grams = resolve_grams(entry.get("approx_quantity_text", ""), serving_size_g)
        items_out.append(
            {"food_id": candidate.id, "food_name": candidate.name_es, "quantity_g": grams}
        )

    if not items_out:
        return None

    payload = {"items": items_out}
    proposal = AiProposal(
        ai_session_id=ai_session.id,
        user_id=user_id,
        scope="pantry",
        payload=payload,
        rationale=None,
        status="pending",
    )
    session.add(proposal)
    await session.flush()
    return {"scope": "pantry", "ai_proposal_id": str(proposal.id), "payload": payload}


async def process_chat_job(ai_session_id: str) -> None:
    """Corre en el `worker` (regla 19)."""
    async with AdminSessionLocal() as session:
        ai_session = await session.get(AiSession, uuid.UUID(ai_session_id))
        if ai_session is None or ai_session.status != "running":
            return

        user_id = ai_session.user_id
        source = ai_session.request_payload["source"]

        if source == "voice":
            audio_bytes = await pop_chat_audio(ai_session_id)
            if audio_bytes is None:
                ai_session.status = "failed"
                ai_session.validation_errors = [
                    {"code": "AUDIO_EXPIRED", "message": "La nota de voz ya no está disponible."}
                ]
                await session.commit()
                await push_chat_result(ai_session_id, {"error": "AUDIO_EXPIRED"})
                return
            try:
                message_text = await transcribe(audio_bytes)
            except TranscriptionUnavailable:
                ai_session.status = "failed"
                ai_session.validation_errors = [
                    {
                        "code": "TRANSCRIPTION_UNAVAILABLE",
                        "message": "El servicio de transcripción no está disponible.",
                    }
                ]
                await session.commit()
                await push_chat_result(ai_session_id, {"error": "TRANSCRIPTION_UNAVAILABLE"})
                return
            del audio_bytes
        else:
            message_text = ai_session.request_payload["text"]

        session.add(
            ChatMessage(
                user_id=user_id,
                role="user",
                content=message_text,
                source=source,
                ai_session_id=ai_session.id,
            )
        )
        await session.flush()

        token = await ai_client.get_decrypted_token(session)
        if token is None:
            ai_session.status = "failed"
            ai_session.validation_errors = [
                {"code": "AI_NOT_CONFIGURED", "message": "La credencial se retiró tras encolar."}
            ]
            await session.commit()
            await push_chat_result(ai_session_id, {"error": "AI_NOT_CONFIGURED"})
            return

        try:
            turn = await run_chat_turn(session, user_id, token, message_text)
        except AiAgentError as exc:
            ai_session.status = "failed"
            ai_session.validation_errors = [{"code": exc.code, "message": str(exc)}]
            await session.commit()
            await push_chat_result(ai_session_id, {"error": exc.code})
            return

        proposal_out: dict | None = None
        assistant_text = turn.text or "Vale."

        if turn.day_change_args is not None:
            proposal_out, day_error = await _build_day_change_proposal(
                session, user_id, ai_session, turn
            )
            if day_error:
                # Mensaje honesto de por qué no puede, en vez de aplicar nada
                # (sección 24.3: "si falla validación... responde con un
                # mensaje honesto de por qué no puede").
                assistant_text = day_error

        if turn.pantry_args is not None and proposal_out is None:
            pantry_out = await _build_pantry_proposal(session, user_id, ai_session, turn)
            if pantry_out is not None:
                proposal_out = pantry_out

        session.add(
            ChatMessage(
                user_id=user_id,
                role="assistant",
                content=assistant_text,
                source="text",
                ai_session_id=ai_session.id,
            )
        )
        ai_session.status = "succeeded"
        ai_session.response_payload = {"message": assistant_text}
        ai_session.input_tokens = turn.input_tokens
        ai_session.output_tokens = turn.output_tokens
        await session.commit()

        await push_chat_result(
            ai_session_id, {"message": assistant_text, "proposal": proposal_out}
        )
