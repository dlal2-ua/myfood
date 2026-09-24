"""Importación de recetas desde URL (sección 20). Mismo patrón de dos
mitades (regla 19) que el resto de iafood: `request_recipe_import` corre
en `api` (guardia SSRF, consentimiento/cuota, encola el trabajo) y
`process_recipe_import_job` corre en el `worker` (descarga HTTP +
`recipe_scrapers` + resolución de cada línea de ingrediente mediante el
MISMO resolutor que Smart Log — sección 20: "cada línea de
ingrediente... pasa por el mismo resolutor que Smart Log", en
`ai/flows/food_resolution.py`).

Cada línea de ingrediente se resuelve con su PROPIA llamada al agente (no
una única llamada para toda la receta, como hace Smart Log con una
frase): una receta necesita food_id + gramos editables ligados a CADA
línea concreta, algo que una fusión de menciones perdería.

El resultado es una receta EN BORRADOR (`response_payload`) — el usuario
la revisa (nombre, raciones, cada ingrediente con sus gramos editables,
líneas sin resolver) y la confirma con `POST /recipes`; nada se guarda
solo."""

from __future__ import annotations

import re
import uuid
from urllib.parse import urljoin, urlsplit, urlunsplit
from uuid import UUID

import httpx
from recipe_scrapers import NoSchemaFoundInWildMode, scrape_html
from sqlalchemy.ext.asyncio import AsyncSession

from myfood.ai import client as ai_client
from myfood.ai.agent import AiAgentError
from myfood.ai.flows.food_resolution import (
    build_candidates_payload,
    resolve_food_mentions,
    search_candidates_for_text,
)
from myfood.ai.prompts import (
    RECIPE_IMPORT_PROMPT_VERSION,
    RECIPE_IMPORT_SYSTEM_V1,
    build_recipe_import_line_prompt,
)
from myfood.ai.queue import enqueue_recipe_import_job
from myfood.db.models import AiSession
from myfood.db.session import AdminSessionLocal
from myfood.domain.url_safety import UnsafeUrlError, ensure_public_http_url, resolve_public_ip
from myfood.errors import AppError

_AGENT_TIMEOUT_SECONDS = 20.0
_FETCH_TIMEOUT_SECONDS = 10.0
_MAX_RESPONSE_BYTES = 3 * 1024 * 1024
_MAX_INGREDIENT_LINES = 40


async def request_recipe_import(session: AsyncSession, user_id: UUID, *, url: str) -> AiSession:
    """Corre en el proceso `api`. Determinista y local (guardia SSRF +
    creación de la sesión); la descarga real y la llamada al proveedor
    quedan para el worker (regla 19)."""
    credential_status = await ai_client.get_credential_status(session)
    if not credential_status.configured:
        raise AppError(
            "AI_NOT_CONFIGURED",
            "El administrador todavía no ha configurado la credencial de iafood.",
            status_code=503,
        )

    try:
        ensure_public_http_url(url)
    except UnsafeUrlError as exc:
        raise AppError("UNSAFE_URL", str(exc), status_code=422) from exc

    ai_session = AiSession(
        user_id=user_id,
        kind="recipe_import",
        status="running",
        request_payload={"prompt_version": RECIPE_IMPORT_PROMPT_VERSION, "url": url},
    )
    session.add(ai_session)
    await session.commit()
    await session.refresh(ai_session)

    await enqueue_recipe_import_job(str(ai_session.id))
    return ai_session


_MAX_REDIRECTS = 5


def _pinned_request(url: str) -> tuple[str, dict[str, str], dict[str, str]]:
    """URL con la IP ya validada en lugar del nombre, más la cabecera `Host` y el
    `sni_hostname` originales: se conecta a esa IP (sin resolver otra vez, para que
    un DNS rebinding no sirva) y el certificado HTTPS se sigue verificando contra
    el nombre real."""
    try:
        ip = resolve_public_ip(url)
    except UnsafeUrlError as exc:
        raise AppError("UNSAFE_URL", str(exc), status_code=422) from exc
    parts = urlsplit(url)
    host = parts.hostname or ""
    port = parts.port or (443 if parts.scheme == "https" else 80)
    ip_host = f"[{ip}]" if ":" in ip else ip
    pinned = urlunsplit(parts._replace(netloc=f"{ip_host}:{port}"))
    host_header = host if parts.port is None else f"{host}:{parts.port}"
    return pinned, {"Host": host_header}, {"sni_hostname": host}


async def _fetch_html(url: str) -> str:
    """Descarga la página validando CADA salto: `follow_redirects=True` seguía
    redirecciones sin comprobar el destino, así que una página pública podía
    mandar al servidor a `http://169.254.169.254/...` u otra red interna (SSRF por
    redirección)."""
    current = url
    try:
        async with httpx.AsyncClient(
            follow_redirects=False, timeout=_FETCH_TIMEOUT_SECONDS
        ) as http_client:
            for _hop in range(_MAX_REDIRECTS + 1):
                pinned, headers, extensions = _pinned_request(current)
                async with http_client.stream(
                    "GET", pinned, headers=headers, extensions=extensions
                ) as response:
                    if response.is_redirect and response.headers.get("location"):
                        current = urljoin(current, response.headers["location"])
                        continue
                    response.raise_for_status()
                    chunks: list[bytes] = []
                    total = 0
                    async for chunk in response.aiter_bytes():
                        total += len(chunk)
                        if total > _MAX_RESPONSE_BYTES:
                            raise AppError(
                                "RECIPE_PAGE_TOO_LARGE",
                                "La página supera el tamaño máximo permitido (3 MB).",
                                status_code=422,
                            )
                        chunks.append(chunk)
                    return b"".join(chunks).decode(
                        response.encoding or "utf-8", errors="replace"
                    )
            raise AppError(
                "RECIPE_FETCH_FAILED",
                "La página redirige demasiadas veces.",
                status_code=422,
            )
    except httpx.HTTPError as exc:
        raise AppError(
            "RECIPE_FETCH_FAILED",
            f"No se ha podido descargar la página: {exc}",
            status_code=422,
        ) from exc


def _parse_servings(scraper) -> int:
    try:
        raw = scraper.yields()
    except Exception:
        return 1
    match = re.search(r"\d+", raw or "")
    return int(match.group()) if match else 1


def _safe_total_time(scraper) -> int | None:
    try:
        return scraper.total_time()
    except Exception:
        return None


async def process_recipe_import_job(ai_session_id: str) -> None:
    """Corre en el `worker` (regla 19)."""
    async with AdminSessionLocal() as session:
        ai_session = await session.get(AiSession, uuid.UUID(ai_session_id))
        if ai_session is None or ai_session.status != "running":
            return  # ya procesado, o no existe (defensivo)

        url: str = ai_session.request_payload["url"]

        try:
            # Segunda comprobación SSRF: el DNS puede haber cambiado entre
            # la petición original y que el worker recoja el trabajo
            # (TOCTOU asumido deliberadamente, ver domain/url_safety.py).
            ensure_public_http_url(url)
        except UnsafeUrlError as exc:
            ai_session.status = "failed"
            ai_session.validation_errors = [{"code": "UNSAFE_URL", "message": str(exc)}]
            await session.commit()
            return

        try:
            html = await _fetch_html(url)
        except AppError as exc:
            ai_session.status = "failed"
            ai_session.validation_errors = [{"code": exc.code, "message": exc.message}]
            await session.commit()
            return

        try:
            scraper = scrape_html(html, org_url=url, supported_only=False)
        except NoSchemaFoundInWildMode:
            ai_session.status = "failed"
            ai_session.validation_errors = [
                {
                    "code": "RECIPE_SCHEMA_NOT_FOUND",
                    "message": "No se ha encontrado una receta reconocible en esa página.",
                }
            ]
            await session.commit()
            return

        token = await ai_client.get_decrypted_token(session)
        if token is None:
            ai_session.status = "failed"
            ai_session.validation_errors = [
                {"code": "AI_NOT_CONFIGURED", "message": "La credencial se retiró tras encolar."}
            ]
            await session.commit()
            return

        ingredient_lines = [line.strip() for line in scraper.ingredients() if line.strip()]
        ingredient_lines = ingredient_lines[:_MAX_INGREDIENT_LINES]

        resolved_ingredients: list[dict] = []
        unresolved_lines: list[str] = []
        total_input_tokens = 0
        total_output_tokens = 0

        for line in ingredient_lines:
            hits = await search_candidates_for_text(line)
            if not hits:
                unresolved_lines.append(line)
                continue
            candidates_out, alias_to_food_id = build_candidates_payload(hits)

            try:
                items_out, agent_result, _extras = await resolve_food_mentions(
                    session,
                    token=token,
                    prompt=build_recipe_import_line_prompt(line, candidates_out),
                    system_prompt=RECIPE_IMPORT_SYSTEM_V1,
                    alias_to_food_id=alias_to_food_id,
                    timeout_seconds=_AGENT_TIMEOUT_SECONDS,
                )
            except AiAgentError as exc:
                ai_session.status = "failed"
                ai_session.validation_errors = [{"code": exc.code, "message": str(exc)}]
                await session.commit()
                return

            total_input_tokens += agent_result.input_tokens
            total_output_tokens += agent_result.output_tokens
            if items_out:
                resolved_ingredients.append({**items_out[0], "original_line": line})
            else:
                unresolved_lines.append(line)

        ai_session.status = "succeeded"
        ai_session.response_payload = {
            "name": scraper.title(),
            "servings": _parse_servings(scraper),
            "prep_minutes": _safe_total_time(scraper),
            "instructions": scraper.instructions(),
            "ingredients": resolved_ingredients,
            "unresolved_lines": unresolved_lines,
        }
        ai_session.input_tokens = total_input_tokens
        ai_session.output_tokens = total_output_tokens
        await session.commit()
