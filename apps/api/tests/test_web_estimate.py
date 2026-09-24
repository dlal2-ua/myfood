"""Respaldo por búsqueda web (`ai/flows/web_estimate.py`).

Lo que hay que atar aquí no es que encuentre cosas —eso depende de internet— sino las reglas:
que solo se dispare cuando hace falta, que se pueda apagar, que lo que saque no entre nunca en
el catálogo (R9) y que un número imposible no llegue al histórico.
"""

import json
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import select, text

from myfood.ai.agent import AgentResult, AiAgentError
from myfood.ai.flows import web_estimate
from myfood.config import get_settings
from myfood.db.models import AiProposal, AiSession, Food
from myfood.db.session import AdminSessionLocal

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def _limits_tmp_path(tmp_path, monkeypatch):
    monkeypatch.setattr(get_settings(), "iafood_config_path", str(tmp_path / "iafood.json"))


def _set_fallback(enabled: bool) -> None:
    Path(get_settings().iafood_config_path).write_text(
        json.dumps({"web_search_fallback": enabled}), encoding="utf-8"
    )


@pytest_asyncio.fixture
async def running_session(two_users):
    user_id, _ = two_users
    async with AdminSessionLocal() as session:
        ai_session = AiSession(
            user_id=user_id, kind="smart_log", status="running", request_payload={}
        )
        session.add(ai_session)
        await session.commit()
        await session.refresh(ai_session)
        return ai_session


def _agent_returning(items, calls=None):
    async def _fake(**kwargs):
        if calls is not None:
            calls.append(kwargs)
        for tool_obj in kwargs.get("mcp_tools") or []:
            await tool_obj.handler({"items": items})
        return AgentResult(text="", input_tokens=4000, output_tokens=300)

    return _fake


async def _run(session, ai_session, missing, **kwargs):
    return await web_estimate.estimate_missing_foods(
        session,
        token="fake",
        user_id=ai_session.user_id,
        ai_session=ai_session,
        missing=missing,
        log_date=kwargs.pop("log_date", "2026-09-24"),
        meal_type=kwargs.pop("meal_type", "lunch"),
    )


# --- cuándo se dispara ----------------------------------------------------------------------


async def test_sin_nada_que_buscar_no_se_llama_al_modelo(running_session, monkeypatch):
    """Es un segundo turno con búsqueda web: si se disparase siempre, multiplicaría por tres el
    coste de TODAS las peticiones para mejorar la minoría que lo necesita."""
    _set_fallback(True)
    llamado = []
    monkeypatch.setattr(web_estimate, "run_agent", _agent_returning([], llamado))
    async with AdminSessionLocal() as session:
        proposal, result = await _run(session, running_session, [])
    assert proposal is None and result is None and llamado == []


async def test_el_administrador_puede_apagarlo(running_session, monkeypatch):
    _set_fallback(False)
    llamado = []
    monkeypatch.setattr(web_estimate, "run_agent", _agent_returning([], llamado))
    async with AdminSessionLocal() as session:
        proposal, result = await _run(session, running_session, ["fabada asturiana"])
    assert proposal is None and llamado == []


async def test_se_le_da_la_herramienta_de_busqueda_y_ninguna_otra(running_session, monkeypatch):
    """`extra_tools` es la única puerta por la que entra una herramienta nativa del CLI. Nada
    de Bash ni de escribir en disco (R1/R2)."""
    _set_fallback(True)
    llamado = []
    monkeypatch.setattr(web_estimate, "run_agent", _agent_returning([], llamado))
    async with AdminSessionLocal() as session:
        await _run(session, running_session, ["fabada asturiana"])
    assert llamado[0]["extra_tools"] == ["WebSearch"]


# --- qué se hace con lo que devuelve --------------------------------------------------------


async def test_lo_estimado_queda_en_una_propuesta_con_su_fuente(running_session, monkeypatch):
    _set_fallback(True)
    monkeypatch.setattr(
        web_estimate,
        "run_agent",
        _agent_returning(
            [
                {
                    "nombre": "Fabada asturiana",
                    "cantidad_texto": "una",
                    "tipo_cantidad": "porcion",
                    "kcal_100g": 180,
                    "protein_100g": 11,
                    "fat_100g": 12,
                    "carbs_100g": 6,
                    "fuente": "https://www.ejemplo.es/fabada-asturiana",
                }
            ]
        ),
    )
    async with AdminSessionLocal() as session:
        proposal, result = await _run(session, running_session, ["fabada asturiana"])
        assert proposal is not None
        item = proposal["payload"]["items"][0]
        assert item["name"] == "Fabada asturiana"
        assert item["estimated"] is True
        assert item["food_id"] is None
        assert item["source_url"] == "https://www.ejemplo.es/fabada-asturiana"
        # Una porción de un plato de cuchara son 250 g, y los pone `quantity_text` a
        # partir del texto — el modelo no da gramos ni aquí (R1).
        assert item["grams"] == 250.0
        assert item["kcal"] == 450.0  # 180 kcal/100 g × 250 g
        assert result.input_tokens == 4000

        # Queda pendiente de que el usuario la apruebe, como la del chat.
        stored = (
            await session.scalars(
                select(AiProposal).where(AiProposal.ai_session_id == running_session.id)
            )
        ).all()
        assert [p.status for p in stored] == ["pending"]

        # Y NO se ha dado de alta en el catálogo: no viene del ETL (R9).
        catalogo = (
            await session.scalars(select(Food).where(Food.name_es == "Fabada asturiana"))
        ).all()
        assert catalogo == []
    async with AdminSessionLocal() as session:
        await session.execute(text("DELETE FROM ai_proposals"))
        await session.commit()


async def test_un_valor_imposible_no_llega_al_historico(running_session, monkeypatch):
    """El aceite, lo más calórico que se come, ronda las 900 kcal/100 g. Por encima es un error
    de lectura, y es preferible no proponer nada a meterlo en el día del usuario."""
    _set_fallback(True)
    monkeypatch.setattr(
        web_estimate,
        "run_agent",
        _agent_returning(
            [{"nombre": "Algo raro", "cantidad_texto": "una ración", "kcal_100g": 5000}]
        ),
    )
    async with AdminSessionLocal() as session:
        proposal, result = await _run(session, running_session, ["algo raro"])
    assert proposal is None
    assert result is not None  # la llamada sí se hizo: cuenta para los tokens


async def test_si_falla_la_busqueda_el_registro_sigue_adelante(running_session, monkeypatch):
    """El respaldo es un extra: que se caiga no puede tumbar un registro que ya tiene sus otros
    alimentos resueltos contra el catálogo."""
    _set_fallback(True)

    async def _boom(**kwargs):
        raise AiAgentError("se cayó", code="AI_TIMEOUT")

    monkeypatch.setattr(web_estimate, "run_agent", _boom)
    async with AdminSessionLocal() as session:
        proposal, result = await _run(session, running_session, ["fabada asturiana"])
    assert proposal is None and result is None
