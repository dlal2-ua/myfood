"""Cliente HTTP hacia el servicio `whisper` autoalojado (sección 24.1) —
única excepción a "sin IA local" (R2): no razona nada, solo convierte voz en
texto. El audio llega ya en memoria (`bytes`, nunca se escribe a disco) y se
descarta en cuanto se obtiene el texto — quien llama a `transcribe` es
responsable de no conservar `audio_bytes` más de lo necesario.
"""

from __future__ import annotations

import httpx

from myfood.config import get_settings

_TRANSCRIBE_TIMEOUT_SECONDS = 30.0


class TranscriptionUnavailable(Exception):
    """El servicio whisper no respondió (contenedor caído, GPU ocupada...) —
    el llamador debe poder ofrecer escribir en su lugar (503, sección 24.1)."""


async def transcribe(audio_bytes: bytes) -> str:
    settings = get_settings()
    try:
        async with httpx.AsyncClient(
            base_url=settings.whisper_base_url, timeout=_TRANSCRIBE_TIMEOUT_SECONDS
        ) as client:
            files = {"audio_file": ("note.ogg", audio_bytes)}
            resp = await client.post("/asr", files=files, params={"language": "es"})
            resp.raise_for_status()
    except httpx.HTTPError as exc:
        raise TranscriptionUnavailable(
            "El servicio de transcripción no está disponible."
        ) from exc

    # El motor `openai-whisper-asr-webservice` responde `{"text": "..."}` en
    # JSON por defecto; se acepta también texto plano por si la instancia
    # está configurada con `output=text`.
    try:
        data = resp.json()
    except ValueError:
        return resp.text.strip()
    if isinstance(data, dict) and "text" in data:
        return data["text"].strip()
    return resp.text.strip()
