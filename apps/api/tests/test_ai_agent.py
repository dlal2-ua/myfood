import pytest
from claude_agent_sdk import ResultError, ResultMessage

from myfood.ai import agent as ai_agent
from myfood.ai.tools import build_propose_meal_plan_tool


class _FakeAsyncIterator:
    def __init__(self, items):
        self._items = items

    def __aiter__(self):
        return self._gen()

    async def _gen(self):
        for item in self._items:
            yield item


async def test_run_agent_returns_text_and_usage_on_success(monkeypatch):
    captured = {}

    def fake_query(*, prompt, options):
        captured["prompt"] = prompt
        captured["options"] = options
        return _FakeAsyncIterator(
            [
                ResultMessage(
                    subtype="success",
                    duration_ms=10,
                    duration_api_ms=10,
                    is_error=False,
                    num_turns=1,
                    session_id="s1",
                    result="hola",
                    usage={"input_tokens": 5, "output_tokens": 3},
                )
            ]
        )

    monkeypatch.setattr(ai_agent, "query", fake_query)

    result = await ai_agent.run_agent(
        token="fake-token", prompt="di hola", system_prompt="eres un test"
    )

    assert result.text == "hola"
    assert result.input_tokens == 5
    assert result.output_tokens == 3
    assert captured["prompt"] == "di hola"


async def test_run_agent_builds_options_without_tools_or_secrets(monkeypatch):
    captured = {}

    def fake_query(*, prompt, options):
        captured["options"] = options
        return _FakeAsyncIterator(
            [
                ResultMessage(
                    subtype="success",
                    duration_ms=1,
                    duration_api_ms=1,
                    is_error=False,
                    num_turns=1,
                    session_id="s1",
                    result="ok",
                )
            ]
        )

    monkeypatch.setattr(ai_agent, "query", fake_query)

    await ai_agent.run_agent(token="fake-token", prompt="p", system_prompt="s")

    options = captured["options"]
    assert options.tools == []
    assert options.permission_mode == "dontAsk"
    assert options.strict_mcp_config is True
    assert options.mcp_servers == {}
    assert options.env["CLAUDE_CODE_OAUTH_TOKEN"] == "fake-token"
    # El entorno del subproceso se construye desde cero (nunca los
    # secretos propios de MyFood, aunque el SDK luego mezcle esto sobre
    # el os.environ del proceso llamante — ver docstring de agent.py).
    for leaked_key in ("POSTGRES_PASSWORD", "SECRET_KEY", "ENCRYPTION_KEY", "MEILI_MASTER_KEY"):
        assert leaked_key not in options.env


async def test_run_agent_succeeds_with_empty_text_when_only_a_tool_was_called(monkeypatch):
    """Un turno donde el modelo solo llama a una herramienta (sin texto de
    cierre) no es un error — el llamador mira el sink de la herramienta,
    no `AgentResult.text`, para saber si hubo respuesta útil."""

    def fake_query(*, prompt, options):
        return _FakeAsyncIterator(
            [
                ResultMessage(
                    subtype="success",
                    duration_ms=1,
                    duration_api_ms=1,
                    is_error=False,
                    num_turns=1,
                    session_id="s1",
                    result=None,
                )
            ]
        )

    monkeypatch.setattr(ai_agent, "query", fake_query)

    result = await ai_agent.run_agent(token="x", prompt="p", system_prompt="s")

    assert result.text == ""


async def test_run_agent_registers_mcp_tools_and_allows_them(monkeypatch):
    captured = {}
    sink: list[dict] = []
    tool_obj = build_propose_meal_plan_tool(sink)

    def fake_query(*, prompt, options):
        captured["options"] = options
        return _FakeAsyncIterator(
            [
                ResultMessage(
                    subtype="success",
                    duration_ms=1,
                    duration_api_ms=1,
                    is_error=False,
                    num_turns=1,
                    session_id="s1",
                    result="",
                )
            ]
        )

    monkeypatch.setattr(ai_agent, "query", fake_query)

    await ai_agent.run_agent(
        token="x", prompt="p", system_prompt="s", mcp_tools=[tool_obj]
    )

    options = captured["options"]
    # Ninguna herramienta nativa del CLI, ni siquiera con mcp_tools presente.
    assert options.tools == []
    # Con el nombre a secas el SDK deniega la herramienta en `dontAsk` (encontrado
    # con un token real: "el permiso para usarla ha sido denegado") — el nombre
    # que cuenta es el que expone el servidor MCP: `mcp__<servidor>__<nombre>`.
    assert options.allowed_tools == ["mcp__myfood__propose_meal_plan"]
    assert "myfood" in options.mcp_servers


async def test_run_agent_raises_on_error_result(monkeypatch):
    def fake_query(*, prompt, options):
        return _FakeAsyncIterator(
            [
                ResultMessage(
                    subtype="error_during_execution",
                    duration_ms=10,
                    duration_api_ms=10,
                    is_error=True,
                    num_turns=1,
                    session_id="s1",
                    errors=["boom"],
                )
            ]
        )

    monkeypatch.setattr(ai_agent, "query", fake_query)

    with pytest.raises(ai_agent.AiAgentError, match="boom"):
        await ai_agent.run_agent(token="x", prompt="p", system_prompt="s")


async def test_run_agent_raises_when_no_result_message_ever_arrives(monkeypatch):
    def fake_query(*, prompt, options):
        return _FakeAsyncIterator([])

    monkeypatch.setattr(ai_agent, "query", fake_query)

    with pytest.raises(ai_agent.AiAgentError):
        await ai_agent.run_agent(token="x", prompt="p", system_prompt="s")


async def test_run_agent_wraps_sdk_errors_as_ai_agent_error(monkeypatch):
    """Bug real encontrado en vivo: un token inválido hace que el SDK
    lance `ResultError` (subclase de `ClaudeSDKError`), no `TimeoutError` —
    sin capturarlo aquí, se propagaba tal cual y `process_diet_plan_job`
    (que solo atrapa `AiAgentError`) nunca marcaba la sesión como
    `failed`; se quedaba en `running` para siempre."""

    async def fake_query(*, prompt, options):
        raise ResultError(
            "Claude Code returned an error result: Failed to authenticate. "
            "API Error: 401 Invalid bearer token",
            data={"result": "API Error: 401 Invalid bearer token"},
            exit_code=1,
        )
        yield  # pragma: no cover - hace de fake_query un generador asíncrono

    monkeypatch.setattr(ai_agent, "query", fake_query)

    with pytest.raises(ai_agent.AiAgentError, match="401 Invalid bearer token"):
        await ai_agent.run_agent(token="bad-token", prompt="p", system_prompt="s")


async def test_run_agent_wraps_timeout(monkeypatch):
    async def fake_wait_for(coro, timeout):
        coro.close()
        raise TimeoutError

    monkeypatch.setattr(ai_agent.asyncio, "wait_for", fake_wait_for)

    with pytest.raises(ai_agent.AiAgentError, match="Tiempo de espera"):
        await ai_agent.run_agent(
            token="x", prompt="p", system_prompt="s", timeout_seconds=0.01
        )


# --- recuento de tokens ---------------------------------------------------------------------


def test_los_tokens_de_entrada_cuentan_tambien_los_de_cache():
    """`usage["input_tokens"]` del SDK cuenta solo lo que NO venía de caché, y el CLI cachea
    casi todo el prompt: guardando solo ese número, una petición que procesó 13.000 tokens
    quedaba registrada como 4."""
    assert (
        ai_agent._total_input_tokens(
            {
                "input_tokens": 4,
                "cache_read_input_tokens": 12000,
                "cache_creation_input_tokens": 900,
            }
        )
        == 12904
    )


def test_sin_cache_el_recuento_no_cambia():
    assert ai_agent._total_input_tokens({"input_tokens": 2800}) == 2800


def test_sin_ningun_dato_de_uso_no_se_inventa_un_cero():
    """`None` y `0` no son lo mismo: uno dice «no se sabe» y el otro «no consumió nada»."""
    assert ai_agent._total_input_tokens({}) is None
