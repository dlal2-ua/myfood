"""Cliente del Claude Agent SDK (sección 10.1), autenticado con el
`claude setup-token` que el admin pega en el panel (nunca API key: decisión
de arquitectura, ver 🥗 Plan de Actuación). Réplica en Python del adaptador
de openGym (`api/coach/adapters/claude.js` + `oauth.js`): mismo mecanismo
exacto (`CLAUDE_CODE_OAUTH_TOKEN`), mismas restricciones (sin herramientas,
sin sesión persistida, entorno del subproceso construido desde cero).

⚠️ Invariante de seguridad, verificado leyendo el código fuente del SDK
instalado (`claude_agent_sdk/_internal/transport/subprocess_cli.py`): el
diccionario `env` de `ClaudeAgentOptions` se MEZCLA sobre el `os.environ`
completo del proceso llamante, no lo sustituye. Por eso esta función solo
puede invocarse desde el `worker` (sección 19: "no llames a APIs externas
desde el hilo que atiende la petición del usuario"), nunca desde una ruta
de `api/routers/*` que sirve una petición de usuario — el proceso `api`
lleva en su entorno las contraseñas de Postgres, `SECRET_KEY`, etc., y el
del `worker` (que es quien realmente llama a esta función, desde
`ai/flows/diet_plan.py`) es el único que debe mantenerse mínimo.
"""

import asyncio
import os
import tempfile
from dataclasses import dataclass
from typing import Any

from claude_agent_sdk import (
    ClaudeAgentOptions,
    ClaudeSDKError,
    ResultError,
    ResultMessage,
    SdkMcpTool,
    create_sdk_mcp_server,
    query,
)

_ALLOWED_ENV_PASSTHROUGH = ("PATH",)


class AiAgentError(Exception):
    """El Agent SDK terminó sin un resultado utilizable. `code` distingue
    las situaciones de la tabla de errores (sección 10.1) para que el
    llamador pueda reaccionar distinto (p. ej. avisar en el panel de admin
    que la credencial hay que renovarla, no solo "algo falló")."""

    def __init__(self, message: str, *, code: str = "AI_PROVIDER_ERROR"):
        super().__init__(message)
        self.code = code


@dataclass
class AgentResult:
    text: str
    input_tokens: int | None
    output_tokens: int | None


def _build_env(token: str, home_dir: str) -> dict[str, str]:
    """Entorno mínimo para el subproceso del CLI — nunca los secretos propios
    de MyFood. `PATH` se toma del proceso actual porque el binario del CLI
    bundleado por el SDK necesita localizar herramientas básicas del sistema
    (no porque el resto del entorno del proceso llamante deba heredarse)."""
    env = {
        "HOME": home_dir,
        "TMPDIR": home_dir,
        "CLAUDE_CONFIG_DIR": home_dir,
        "CLAUDE_CODE_DISABLE_AUTO_MEMORY": "1",
        "CLAUDE_CODE_OAUTH_TOKEN": token,
        "CLAUDE_AGENT_SDK_CLIENT_APP": "myfood-iafood/0.1.0",
    }
    for key in _ALLOWED_ENV_PASSTHROUGH:
        if key in os.environ:
            env[key] = os.environ[key]
    return env


async def run_agent(
    *,
    token: str,
    prompt: str,
    system_prompt: str,
    model: str | None = None,
    max_turns: int = 1,
    timeout_seconds: float = 30.0,
    mcp_tools: list[SdkMcpTool[Any]] | None = None,
) -> AgentResult:
    """Llamada de un solo turno, sin herramientas nativas del CLI (Bash,
    Read, etc. — R1/R2: la IA nunca ejecuta código ni toca disco/red por su
    cuenta) y sin sesión persistida. `mcp_tools`, si se pasa, son las ÚNICAS
    herramientas que el modelo puede llamar — se registran como un servidor
    MCP en proceso (`create_sdk_mcp_server`) y se auto-aprueban vía
    `allowed_tools` (mismo patrón que el ejemplo del propio SDK), nunca vía
    un callback de permisos. Ninguna herramienta nativa queda disponible
    aunque `mcp_tools` esté vacío.
    """
    with tempfile.TemporaryDirectory(prefix="myfood-iafood-") as home_dir:
        mcp_servers: dict[str, Any] = {}
        allowed_tools: list[str] = []
        if mcp_tools:
            mcp_servers = {"myfood": create_sdk_mcp_server(name="myfood", tools=mcp_tools)}
            allowed_tools = [t.name for t in mcp_tools]

        options = ClaudeAgentOptions(
            tools=[],
            allowed_tools=allowed_tools,
            permission_mode="dontAsk",
            strict_mcp_config=True,
            mcp_servers=mcp_servers,
            cwd=home_dir,
            model=model,
            max_turns=max_turns,
            system_prompt=system_prompt,
            env=_build_env(token, home_dir),
        )

        async def _collect() -> AgentResult:
            result_message: ResultMessage | None = None
            async for message in query(prompt=prompt, options=options):
                if isinstance(message, ResultMessage):
                    result_message = message
            if result_message is None:
                raise AiAgentError("El Agent SDK no devolvió ningún resultado.")
            if result_message.is_error:
                detail = "; ".join(result_message.errors or []) or result_message.subtype
                raise AiAgentError(f"El Agent SDK terminó con error: {detail}")
            usage = result_message.usage or {}
            return AgentResult(
                # `result` puede venir vacío cuando el único "trabajo" del
                # turno fue llamar a una herramienta (mcp_tools) sin texto
                # de cierre — no es un error, el llamador mira el sink de la
                # herramienta, no este texto, para saber si hubo respuesta.
                text=result_message.result or "",
                input_tokens=usage.get("input_tokens"),
                output_tokens=usage.get("output_tokens"),
            )

        try:
            return await asyncio.wait_for(_collect(), timeout=timeout_seconds)
        except TimeoutError as exc:
            raise AiAgentError(
                "Tiempo de espera agotado con el proveedor de IA.", code="AI_TIMEOUT"
            ) from exc
        except ClaudeSDKError as exc:
            # Sin este catch, un fallo real del SDK (token inválido, CLI no
            # encontrado, JSON corrupto...) se propagaba tal cual — nunca
            # como `AiAgentError` — y el `except AiAgentError` de
            # `process_diet_plan_job` no lo atrapaba: la `ai_session` se
            # quedaba en `running` para siempre (encontrado en vivo, con un
            # token de prueba inválido: `ResultError` con "401 Invalid
            # bearer token" no marcado nunca como `failed`).
            detail = str(exc)
            code = "AI_PROVIDER_ERROR"
            if isinstance(exc, ResultError):
                if exc.result:
                    detail = exc.result
                if exc.api_error_status in (401, 403):
                    code = "AI_CREDENTIAL_INVALID"
            raise AiAgentError(f"El Agent SDK falló: {detail}", code=code) from exc
