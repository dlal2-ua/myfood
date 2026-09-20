"""Divide el turno de chat en las dos mitades de la regla 19:
`request_chat_message` corre en el proceso `api` (valida, transcribe la nota
de voz si la hay, crea el `ai_session`, encola) y `process_chat_job` corre en
el `worker` (es la única función de chat que invoca `ai/agent.run_agent`, vía
`chat/agent_loop.py`).

El audio se transcribe EN MEMORIA dentro del proceso `api` (sección 24.1: se
pasa a Whisper sin tocar disco) y al worker solo le llega el texto. Antes
viajaba por Redis hasta el worker, pero ese Redis vuelca snapshots a disco
(`--save 60 1`), así que durante unos segundos los bytes del audio podían
acabar en `dump.rdb` — incumpliendo "el audio nunca se persiste". Whisper es
un contenedor local (no un proveedor externo), así que llamarlo desde el
proceso `api` no rompe la regla 19.

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
from datetime import UTC, date, datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy import text as sql_text
from sqlalchemy.ext.asyncio import AsyncSession

from myfood.ai import client as ai_client
from myfood.ai.agent import AiAgentError
from myfood.ai.queue import enqueue_chat_job, push_chat_result
from myfood.ai.validator import validate_day_totals, validate_structure
from myfood.chat.agent_loop import ChatTurnResult, run_chat_turn
from myfood.chat.transcribe import TranscriptionUnavailable, transcribe
from myfood.db.models import (
    AiProposal,
    AiSession,
    ChatMessage,
    DietPlan,
    Food,
)
from myfood.db.session import AdminSessionLocal
from myfood.domain.diet_engine import DayTargets, solve_day_with_fixed_items
from myfood.domain.quantity_text import resolve_grams
from myfood.domain.targets import resolve_targets
from myfood.errors import AppError

_MAX_AUDIO_BYTES = 15 * 1024 * 1024
# Contexto de conversación que se le da al modelo: sin él cada mensaje es una
# conversación nueva (no recuerda sus propias preguntas aclaratorias).
_HISTORY_MAX_MESSAGES = 10
_HISTORY_MAX_AGE = timedelta(hours=6)


async def request_chat_message(
    session: AsyncSession, user_id: UUID, *, text: str | None, audio_bytes: bytes | None
) -> AiSession:
    """Corre en el proceso `api` (regla 19) — nunca llama al proveedor de IA
    (Claude); solo transcribe la nota de voz con el Whisper local, prepara todo
    lo determinista y encola."""
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
        try:
            text = await transcribe(audio_bytes)
        except TranscriptionUnavailable as exc:
            raise AppError(
                "TRANSCRIPTION_UNAVAILABLE",
                "No se pudo transcribir la nota de voz. Puedes escribir tu mensaje en su lugar.",
                status_code=503,
            ) from exc
        finally:
            # El audio no debe sobrevivir a la transcripción, pase lo que pase.
            del audio_bytes
        if not text.strip():
            raise AppError(
                "EMPTY_TRANSCRIPTION",
                "No se ha entendido nada en la nota de voz. Vuelve a grabarla o escribe "
                "tu mensaje.",
                status_code=422,
            )
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
        request_payload={"source": source, "text": text},
    )
    session.add(ai_session)
    await session.commit()
    await session.refresh(ai_session)

    await enqueue_chat_job(str(ai_session.id))
    return ai_session


async def _recent_history(session: AsyncSession, user_id: UUID) -> list[tuple[str, str]]:
    rows = (
        await session.scalars(
            select(ChatMessage)
            .where(
                ChatMessage.user_id == user_id,
                ChatMessage.created_at >= datetime.now(UTC) - _HISTORY_MAX_AGE,
            )
            .order_by(ChatMessage.created_at.desc())
            .limit(_HISTORY_MAX_MESSAGES)
        )
    ).all()
    return [(m.role, m.content) for m in reversed(rows)]


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

    has_recipe_item = await session.scalar(
        sql_text("""
            SELECT 1 FROM plan_items pi
            JOIN plan_meals pm ON pm.id = pi.plan_meal_id
            JOIN plan_days pd ON pd.id = pm.plan_day_id
            WHERE pd.plan_id = :plan_id AND pd.day_index = :day_index
              AND pi.recipe_id IS NOT NULL
            LIMIT 1
        """),
        {"plan_id": str(plan.id), "day_index": day_index},
    )
    if has_recipe_item:
        # Aprobar un cambio de día sustituye todas sus comidas: una receta de
        # batch cooking no es un alimento que el modelo pueda referenciar, así
        # que se perdería sin avisar.
        return None, (
            "Ese día incluye una receta de batch cooking y no puedo cambiarlo desde el chat "
            "sin perderla. Puedes modificarlo desde la pantalla del plan."
        )

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

    try:
        resolved = await resolve_targets(session, user_id, action="pedirme cambios en el plan")
    except AppError:
        return None, "Completa tu perfil y registra tu peso antes de pedirme cambios en el plan."
    safety_floor_kcal = resolved.safety_floor_kcal
    min_fat_g = resolved.min_fat_g
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
        grams = resolve_grams(
            entry.get("approx_quantity_text", ""),
            serving_size_g,
            food_name=candidate.name_es,
            category=food.category if food else None,
        )
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
        message_text = ai_session.request_payload["text"]

        # Antes de guardar el mensaje actual, para que no aparezca dos veces.
        history = await _recent_history(session, user_id)
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
            turn = await run_chat_turn(session, user_id, token, message_text, history)
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
