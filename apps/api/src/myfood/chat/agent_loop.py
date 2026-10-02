"""Bucle agente del chat conversacional (sección 24.3). A diferencia del
resto de iafood (una única llamada, una única tool, `max_turns=1` o `2`),
aquí Claude puede encadenar varias llamadas de solo lectura antes de
responder o proponer un cambio — la conversación es abierta y no viene con
candidatos precargados (sección 24.2). Tope de 5 llamadas por turno
(sección 24.5, anti-abuso de coste) y 20s de timeout de turno.

Apuntar comida ya no necesita ninguna de esas lecturas: el modelo estima cada plato entero
con lo que sabe (`ai/prompts.py::MEAL_ESTIMATE_RULES`) y lo manda de una vez, que es además
lo que hace que un mensaje dictado de tres platos quepa de sobra en el turno.

Corre siempre en el `worker` (regla 19) — es la única función de chat que
invoca `ai/agent.run_agent`.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession

from myfood.ai.agent import AgentResult, run_agent
from myfood.ai.prompts import CHAT_SYSTEM_V2, build_chat_user_prompt
from myfood.chat.tools import build_chat_tools
from myfood.config import get_settings
from myfood.domain import estimated_dishes
from myfood.domain.diet_engine import CandidateFood

MAX_TOOL_CALLS_PER_TURN = 5
# La sección 24.5 fija 20s de turno. Medido en producción, ese tope corta turnos que iban
# bien: el subproceso del CLI del Agent SDK tarda unos segundos solo en arrancar, y a eso se
# le suman hasta 5 llamadas a herramientas antes de la respuesta. Con 20s, dos mensajes
# reales seguidos fallaron con AI_TIMEOUT aunque el modelo estaba respondiendo; un turno
# normal (sin herramientas) se resuelve en unos 5s. Se sube a 55s, que sigue por debajo del
# tope de 100s del proxy y deja margen para el turno con más herramientas.
CHAT_TURN_TIMEOUT_SECONDS = 55.0


@dataclass
class ChatTurnResult:
    text: str
    day_change_args: dict | None
    pantry_args: dict | None
    # Lo que el turno quiere escribir en el diario del usuario, pendiente de que lo confirme.
    diary_args: dict | None = None
    edit_args: dict | None = None
    water_args: dict | None = None
    shopping_args: dict | None = None
    alias_to_candidate: dict[str, CandidateFood] = field(default_factory=dict)
    input_tokens: int | None = None
    output_tokens: int | None = None


def merge_diary_calls(calls: list[dict]) -> dict | None:
    """Todas las llamadas a `propose_diary_entries` de un turno, en una sola propuesta.

    Al dictar el día entero («he desayunado… para comer… y de cena…») el modelo tiende a
    hacer una llamada por comida, aunque se le pida una. Quedarse con la última —que es lo que
    se hace con el resto de herramientas— tiraba el desayuno y la comida sin decir nada: se
    encontró con un audio real. Aquí cada plato se queda con la comida de su llamada.

    Dos llamadas para la MISMA comida del mismo día sí son una corrección, y ahí vale la
    última. Una propuesta solo tiene una fecha: manda la de la última llamada y las de otros
    días se devuelven en `skipped_dates` para poder decírselo al usuario."""
    calls = [call for call in calls if isinstance(call, dict)]
    if not calls:
        return None
    by_meal: dict[tuple[object, object], dict] = {}
    for call in calls:
        by_meal[(call.get("date"), call.get("meal_type"))] = call
    last = calls[-1]
    same_day = [call for (day, _), call in by_meal.items() if day == last.get("date")]
    skipped = sorted({str(day) for day, _ in by_meal if day != last.get("date")})
    if len(same_day) == 1 and not skipped:
        return last

    items = [
        {**item, "comida": item.get("comida") or call.get("meal_type")}
        for call in same_day
        for item in call.get("items") or []
        if isinstance(item, dict)
    ]
    requests = [str(call["request"]).strip() for call in same_day if call.get("request")]
    merged = {**last, "items": items, "request": " · ".join(dict.fromkeys(requests)) or None}
    if skipped:
        merged["skipped_dates"] = skipped
    return merged


_WEEKDAYS = ("lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo")


def today_label(now: datetime | None = None) -> str:
    """«viernes 2026-10-02», en la hora de la instancia. Con el día de la semana delante
    porque «el lunes» se resuelve mal si solo se tiene la fecha."""
    now = now or datetime.now(ZoneInfo(get_settings().tz))
    return f"{_WEEKDAYS[now.weekday()]} {now.date().isoformat()}"


async def run_chat_turn(
    session: AsyncSession,
    user_id: UUID,
    token: str,
    user_text: str,
    history: Sequence[tuple[str, str]] = (),
) -> ChatTurnResult:
    alias_map: dict[str, CandidateFood] = {}
    day_change_sink: list[dict] = []
    pantry_sink: list[dict] = []
    diary_sink: list[dict] = []
    edit_sink: list[dict] = []
    water_sink: list[dict] = []
    shopping_sink: list[dict] = []

    tools = build_chat_tools(
        session,
        user_id,
        alias_map=alias_map,
        day_change_sink=day_change_sink,
        pantry_sink=pantry_sink,
        diary_sink=diary_sink,
        edit_sink=edit_sink,
        water_sink=water_sink,
        shopping_sink=shopping_sink,
    )

    # Los platos guardados que aparecen en el mensaje: el modelo los nombra tal cual y los
    # números salen del catálogo (`domain/diary_proposal.py`), no de una estimación nueva.
    saved = await estimated_dishes.load_saved(session)
    known_dishes = [dish.name for dish in estimated_dishes.mentioned(user_text, saved)]

    agent_result: AgentResult = await run_agent(
        token=token,
        prompt=build_chat_user_prompt(
            user_text, history, today=today_label(), known_dishes=known_dishes
        ),
        system_prompt=CHAT_SYSTEM_V2,
        mcp_tools=tools,
        max_turns=MAX_TOOL_CALLS_PER_TURN,
        timeout_seconds=CHAT_TURN_TIMEOUT_SECONDS,
    )

    return ChatTurnResult(
        text=agent_result.text,
        # Si el modelo llama a la misma tool más de una vez en el turno
        # (p. ej. se corrige a media conversación), se queda con la última
        # — mismo criterio que el resto de flujos sink-based (`sink[-1]`).
        day_change_args=day_change_sink[-1] if day_change_sink else None,
        pantry_args=pantry_sink[-1] if pantry_sink else None,
        # Salvo el diario: ahí varias llamadas suelen ser varias comidas, no una corrección.
        diary_args=merge_diary_calls(diary_sink),
        edit_args=edit_sink[-1] if edit_sink else None,
        water_args=water_sink[-1] if water_sink else None,
        shopping_args=shopping_sink[-1] if shopping_sink else None,
        alias_to_candidate=alias_map,
        input_tokens=agent_result.input_tokens,
        output_tokens=agent_result.output_tokens,
    )
