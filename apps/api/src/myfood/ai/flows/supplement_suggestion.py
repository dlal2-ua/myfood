"""Sugerencia de suplementos con iafood (sección 10.7) — flujo aparte, con reglas más estrictas por
ser terreno de salud:

- Solo bajo petición explícita del usuario, nunca automáticamente.
- No se ejecuta si el perfil declara embarazo/lactancia o patología/medicación, ni si es menor de
  18 años (`403 SUPPLEMENT_ADVICE_BLOCKED`), ni si no hay datos suficientes para valorar nada.
- El LLM solo elige CLAVES de la lista blanca (`domain/supplements_whitelist.py`): la dosis la
  rellena el backend con su dosis habitual, sin pasar del máximo ni del UL. Los números que ve
  el usuario (ingesta, % de la referencia) los calcula el backend, no el modelo (R1).
- Cada sugerencia queda como propuesta `pending` con su aviso: solo entra en el catálogo si el
  usuario la aprueba.

Mismo patrón de dos mitades que el resto de iafood (regla 19): `request_*` corre en el proceso
`api` y `process_*_job` en el `worker`.
"""

from __future__ import annotations

import re
import uuid
from collections import defaultdict
from datetime import date, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from myfood.ai import client as ai_client
from myfood.ai import tools
from myfood.ai.agent import AiAgentError, run_agent
from myfood.ai.anonymize import age_band, build_supplement_payload
from myfood.ai.prompts import (
    SUPPLEMENT_SUGGESTION_PROMPT_VERSION,
    SUPPLEMENT_SUGGESTION_SYSTEM_V1,
    build_supplement_suggestion_user_prompt,
)
from myfood.ai.queue import enqueue_supplement_suggestion_job
from myfood.db.models import (
    HEALTH_FLAG_CONDITION,
    HEALTH_FLAG_PREGNANT,
    AiProposal,
    AiSession,
    FoodLog,
    Profile,
    Supplement,
)
from myfood.db.session import AdminSessionLocal
from myfood.domain import micronutrients, supplements_whitelist
from myfood.domain.supplements_whitelist import BY_KEY, DISCLAIMER, MICRO_SUGGEST_BELOW_PCT
from myfood.domain.targets import age_years, resolve_targets
from myfood.errors import AppError

PERIOD_DAYS = 30
MIN_LOGGING_DAYS = 7
# Los micronutrientes solo vienen en algunos alimentos (los de marca casi nunca): con pocos datos,
# una «carencia» sería un artefacto. Por debajo de esta cobertura no se valora nada (R9).
MIN_MICRO_COVERAGE = 0.6
# Un alimento cuenta como «con datos» si trae al menos esta cantidad de los micronutrientes que se
# valoran: con uno o dos sueltos (un alimento que solo declara el hierro) no se puede saber cuánto
# aporta del resto.
MIN_MICROS_PER_FOOD = 4
_RELEVANT_MICROS = frozenset(
    e.micro_key for e in supplements_whitelist.WHITELIST if e.micro_key is not None
)
PROTEIN_SUGGEST_BELOW_PCT = 90.0
_AGENT_TIMEOUT_SECONDS = 45.0
_MAX_REASON_CHARS = 240
_HAS_DIGIT = re.compile(r"\d")


def _blocked() -> AppError:
    return AppError(
        "SUPPLEMENT_ADVICE_BLOCKED",
        "Con lo que has indicado en tu perfil, MyFood no sugiere suplementos: consulta a un "
        "médico o un dietista-nutricionista.",
        status_code=403,
    )


async def _intake_summary(session: AsyncSession, user_id: UUID, profile: Profile) -> dict:
    """Ingesta media de los últimos 30 días (solo los días con registro) frente a la referencia."""
    since = date.today() - timedelta(days=PERIOD_DAYS - 1)
    rows = (
        await session.execute(
            select(FoodLog.log_date, FoodLog.protein_g, FoodLog.micros).where(
                FoodLog.user_id == user_id, FoodLog.log_date >= since
            )
        )
    ).all()
    micros_by_day: dict[date, dict[str, float]] = defaultdict(dict)
    protein_by_day: dict[date, float] = defaultdict(float)
    with_micros = 0
    for log_date, protein_g, micros in rows:
        protein_by_day[log_date] += float(protein_g)
        if len(_RELEVANT_MICROS & micros.keys()) >= MIN_MICROS_PER_FOOD:
            with_micros += 1
        for key, value in micros.items():
            day = micros_by_day[log_date]
            day[key] = day.get(key, 0.0) + float(value)
    days = len(protein_by_day)
    reference = micronutrients.reference_for_sex(profile.sex)

    nutrients = []
    for entry in supplements_whitelist.WHITELIST:
        if entry.micro_key is None:
            continue
        average = sum(d.get(entry.micro_key, 0.0) for d in micros_by_day.values()) / max(days, 1)
        ref = reference[entry.micro_key]
        nutrients.append(
            {
                "key": entry.key,
                "label": micronutrients.NUTRIENT_LABELS[entry.micro_key],
                "avg_per_day": round(average, 2),
                "reference": ref,
                "pct_of_reference": round(100 * average / ref, 1),
            }
        )
    protein = None
    try:
        target = (await resolve_targets(session, user_id)).protein_g
        average = sum(protein_by_day.values()) / max(days, 1)
        protein = {
            "key": "protein",
            "avg_per_day_g": round(average, 1),
            "target_g": round(target, 1),
            "pct_of_target": round(100 * average / target, 1) if target else None,
        }
    except AppError:
        protein = None
    return {
        "days": days,
        "micro_coverage": (with_micros / len(rows)) if rows else 0.0,
        "nutrients": nutrients,
        "protein": protein,
    }


async def request_supplement_suggestion(session: AsyncSession, user_id: UUID) -> AiSession:
    """Corre en el proceso `api`. Aplica los bloqueos, resume la ingesta y encola el trabajo."""
    credential_status = await ai_client.get_credential_status(session)
    if not credential_status.configured:
        raise AppError(
            "AI_NOT_CONFIGURED",
            "El administrador todavía no ha configurado la credencial de iafood.",
            status_code=503,
        )
    profile = await session.get(Profile, user_id)
    if profile is not None and (
        profile.has_health_flag(HEALTH_FLAG_PREGNANT)
        or profile.has_health_flag(HEALTH_FLAG_CONDITION)
    ):
        raise _blocked()
    if profile is None or profile.birth_date is None:
        raise AppError(
            "PROFILE_INCOMPLETE",
            "Indica tu fecha de nacimiento en el perfil: no se sugieren suplementos sin conocer "
            "tu edad.",
            status_code=422,
        )
    if age_years(profile.birth_date) < 18 or age_band(profile.birth_date) == "<18":
        raise _blocked()

    summary = await _intake_summary(session, user_id, profile)
    if summary["days"] < MIN_LOGGING_DAYS:
        raise AppError(
            "NOT_ENOUGH_DATA",
            f"Registra tus comidas al menos {MIN_LOGGING_DAYS} días de los últimos {PERIOD_DAYS} "
            "para poder valorar tu ingesta.",
            status_code=422,
        )
    if summary["micro_coverage"] < MIN_MICRO_COVERAGE:
        raise AppError(
            "INSUFFICIENT_MICRONUTRIENT_DATA",
            "Los alimentos que has registrado traen pocos datos de vitaminas y minerales, así que "
            "no se puede valorar tu ingesta con fiabilidad.",
            status_code=422,
        )

    taking = list(
        await session.execute(
            select(Supplement.name, Supplement.type).where(
                Supplement.user_id == user_id, Supplement.is_active.is_(True)
            )
        )
    )
    already = [
        e.key
        for e in supplements_whitelist.WHITELIST
        if supplements_whitelist.already_taking(e, taking)
    ]
    anonymized = build_supplement_payload(
        nutrients=summary["nutrients"],
        logging_days=summary["days"],
        protein=summary["protein"],
        already_taking=already,
        whitelist=[{"key": e.key, "name": e.name_es} for e in supplements_whitelist.WHITELIST],
    )
    ai_session = AiSession(
        user_id=user_id,
        kind="supplement_suggestion",
        status="running",
        request_payload={
            "prompt_version": SUPPLEMENT_SUGGESTION_PROMPT_VERSION,
            "anonymized": anonymized,
        },
    )
    session.add(ai_session)
    await session.commit()
    await session.refresh(ai_session)
    await enqueue_supplement_suggestion_job(str(ai_session.id))
    return ai_session


def _evidence(key: str, payload: dict) -> str | None:
    """Frase con los números reales de la ingesta, compuesta por el backend."""
    if key == "protein" and payload.get("protein"):
        p = payload["protein"]
        if p.get("pct_of_target") is None:
            return None
        return (
            f"Tu ingesta media de proteína es de {p['avg_per_day_g']:g} g al día, el "
            f"{p['pct_of_target']:g} % de tu objetivo."
        )
    for nutrient in payload.get("nutrients", []):
        if nutrient["key"] == key:
            return (
                f"Tu ingesta media de {nutrient['label'][0].lower()}{nutrient['label'][1:]} es el "
                f"{nutrient['pct_of_reference']:g} % de la referencia."
            )
    return None


def validate_suggestions(raw: list[dict], payload: dict) -> list[dict]:
    """Deja solo las sugerencias válidas: clave de la lista blanca, sin repetir, que no tome ya el
    usuario y que los datos apoyen (ingesta por debajo de la referencia)."""
    already = set(payload.get("already_taking", []))
    by_nutrient = {n["key"]: n for n in payload.get("nutrients", [])}
    protein = payload.get("protein") or {}
    accepted: list[dict] = []
    seen: set[str] = set()
    for item in raw[:10]:
        key = item.get("key")
        entry = BY_KEY.get(key) if isinstance(key, str) else None
        if entry is None or key in seen or key in already:
            continue
        if entry.micro_key is not None:
            nutrient = by_nutrient.get(key)
            if nutrient is None or nutrient["pct_of_reference"] >= MICRO_SUGGEST_BELOW_PCT:
                continue
        elif key == "protein":
            pct = protein.get("pct_of_target")
            if pct is None or pct >= PROTEIN_SUGGEST_BELOW_PCT:
                continue
        else:
            # Creatina, omega-3 y multivitamínico no se pueden valorar con datos de ingesta: sin
            # un dato que lo apoye, no se sugieren (R9).
            continue
        seen.add(key)
        accepted.append({**item, "key": key})
        if len(accepted) == 3:
            break
    return accepted


def _reason(item: dict, payload: dict) -> str:
    """Los números los pone el backend; el texto del modelo solo se usa si no lleva ninguno."""
    evidence = _evidence(item["key"], payload)
    text = str(item.get("reason", "")).strip()[:_MAX_REASON_CHARS]
    if text and not _HAS_DIGIT.search(text):
        return f"{evidence} {text}" if evidence else text
    return evidence or "Los datos de tu ingesta lo apoyan."


async def process_supplement_suggestion_job(ai_session_id: str) -> None:
    """Corre en el `worker` (regla 19)."""
    async with AdminSessionLocal() as session:
        ai_session = await session.get(AiSession, uuid.UUID(ai_session_id))
        if ai_session is None or ai_session.status != "running":
            return
        payload: dict = ai_session.request_payload["anonymized"]

        token = await ai_client.get_decrypted_token(session)
        if token is None:
            ai_session.status = "failed"
            ai_session.validation_errors = [
                {"code": "AI_NOT_CONFIGURED", "message": "La credencial se retiró tras encolar."}
            ]
            await session.commit()
            return

        sink: list[dict] = []
        try:
            agent_result = await run_agent(
                token=token,
                prompt=build_supplement_suggestion_user_prompt(payload),
                system_prompt=SUPPLEMENT_SUGGESTION_SYSTEM_V1,
                mcp_tools=[tools.build_suggest_supplements_tool(sink, supplements_whitelist.KEYS)],
                max_turns=2,
                timeout_seconds=_AGENT_TIMEOUT_SECONDS,
            )
        except AiAgentError as exc:
            ai_session.status = "failed"
            ai_session.validation_errors = [{"code": exc.code, "message": str(exc)}]
            await session.commit()
            return

        raw = sink[-1].get("suggestions", []) if sink else []
        accepted = validate_suggestions(raw, payload)

        suggestions = []
        for item in accepted:
            entry = BY_KEY[item["key"]]
            reason = _reason(item, payload)
            proposal = AiProposal(
                ai_session_id=ai_session.id,
                user_id=ai_session.user_id,
                scope="supplement",
                payload={
                    "key": entry.key,
                    "name_es": entry.name_es,
                    "type": entry.type,
                    "dose_amount": supplements_whitelist.suggested_dose(entry),
                    "dose_unit": entry.dose_unit,
                    "upper_limit": entry.upper_limit,
                    "disclaimer": DISCLAIMER,
                },
                rationale=reason,
                status="pending",
            )
            session.add(proposal)
            await session.flush()
            suggestions.append(
                {
                    "proposal_id": str(proposal.id),
                    "key": entry.key,
                    "name_es": entry.name_es,
                    "dose_amount": proposal.payload["dose_amount"],
                    "dose_unit": entry.dose_unit,
                    "reason": reason,
                }
            )

        ai_session.status = "succeeded"
        ai_session.response_payload = {
            "suggestions": suggestions,
            "disclaimer": DISCLAIMER,
            "warning": None if suggestions else "NO_SUPPORTED_SUGGESTION",
        }
        ai_session.input_tokens = agent_result.input_tokens
        ai_session.output_tokens = agent_result.output_tokens
        await session.commit()
