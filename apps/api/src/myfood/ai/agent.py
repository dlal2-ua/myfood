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
del `worker` es el único que debe mantenerse mínimo antes de que este
módulo se use de verdad en un flujo (Fase 5, próxima entrega).
"""

import asyncio
import os
import tempfile
from dataclasses import dataclass

from claude_agent_sdk import ClaudeAgentOptions, ResultMessage, query

_ALLOWED_ENV_PASSTHROUGH = ("PATH",)


class AiAgentError(Exception):
    """El Agent SDK terminó sin un resultado utilizable (timeout, error del
    proveedor, token inválido...). El llamador decide el código HTTP/estado
    de `ai_sessions` según el contexto (tabla de errores, sección 10.1)."""


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
) -> AgentResult:
    """Llamada de un solo turno, sin herramientas propias del CLI (R1/R2: la
    IA nunca ejecuta código ni toca disco/red por su cuenta) y sin sesión
    persistida. Las herramientas de function calling de cada flujo concreto
    (`propose_meal_plan`, etc.) se añaden como MCP server dedicado cuando
    ese flujo se construya — no existen todavía en esta infraestructura base.
    """
    with tempfile.TemporaryDirectory(prefix="myfood-iafood-") as home_dir:
        options = ClaudeAgentOptions(
            tools=[],
            permission_mode="dontAsk",
            strict_mcp_config=True,
            mcp_servers={},
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
            if result_message.is_error or result_message.result is None:
                detail = "; ".join(result_message.errors or []) or result_message.subtype
                raise AiAgentError(f"El Agent SDK terminó con error: {detail}")
            usage = result_message.usage or {}
            return AgentResult(
                text=result_message.result,
                input_tokens=usage.get("input_tokens"),
                output_tokens=usage.get("output_tokens"),
            )

        try:
            return await asyncio.wait_for(_collect(), timeout=timeout_seconds)
        except TimeoutError as exc:
            raise AiAgentError("Tiempo de espera agotado con el proveedor de IA.") from exc
