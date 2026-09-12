import pytest
from claude_agent_sdk import ResultMessage

from myfood.ai import agent as ai_agent


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


async def test_run_agent_wraps_timeout(monkeypatch):
    async def fake_wait_for(coro, timeout):
        coro.close()
        raise TimeoutError

    monkeypatch.setattr(ai_agent.asyncio, "wait_for", fake_wait_for)

    with pytest.raises(ai_agent.AiAgentError, match="Tiempo de espera"):
        await ai_agent.run_agent(
            token="x", prompt="p", system_prompt="s", timeout_seconds=0.01
        )
