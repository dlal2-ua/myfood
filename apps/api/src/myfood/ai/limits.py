"""Límites de uso de iafood (sección 10.1/24.5) — fichero mutable en disco,
mismo patrón que `coach.json` en openGym. Deliberadamente NO en Postgres:
la especificación fija este dato como `config/iafood.json`, ajustable desde
`/admin/ai/limits` sin reiniciar el stack.

No confundir con la credencial: el token vive cifrado en `ai_credentials`
(`ai/client.py`), nunca en este fichero.
"""

import json
import os
from pathlib import Path

from pydantic import BaseModel, Field

from myfood.config import get_settings

DEFAULT_PER_PROFILE_DAILY = 10
DEFAULT_INSTANCE_DAILY = 30
DEFAULT_MAX_TOKENS_PER_CALL = 8000
# Cuota propia del chat (sección 24.5) — más generosa que la de generación
# completa de dietas a propósito: es una cuota de conversación (preguntas,
# ida y vuelta), un patrón de uso muy distinto a generar un plan entero.
DEFAULT_CHAT_MESSAGES_PER_PROFILE_DAILY = 50
# Cuota propia de la foto del plato: cada una son dos llamadas al modelo (visión y
# catálogo), así que gasta más que un registro por texto, pero es el registro más rápido
# que hay y se usa comida a comida.
DEFAULT_PLATE_PHOTO_PER_PROFILE_DAILY = 10
# Buscar en internet lo que no está en el catálogo. Cuesta entre dos y tres veces más
# tokens que una petición normal y añade 5-15 s, así que solo compensa como respaldo:
# el interruptor está aquí para poder apagarlo sin tocar código.
DEFAULT_WEB_SEARCH_FALLBACK = True


class IafoodLimits(BaseModel):
    per_profile_daily: int = Field(default=DEFAULT_PER_PROFILE_DAILY, ge=1, le=1000)
    instance_daily: int = Field(default=DEFAULT_INSTANCE_DAILY, ge=1, le=10000)
    max_tokens_per_call: int = Field(default=DEFAULT_MAX_TOKENS_PER_CALL, ge=256, le=200000)
    chat_messages_per_profile_daily: int = Field(
        default=DEFAULT_CHAT_MESSAGES_PER_PROFILE_DAILY, ge=1, le=2000
    )
    plate_photo_per_profile_daily: int = Field(
        default=DEFAULT_PLATE_PHOTO_PER_PROFILE_DAILY, ge=1, le=1000
    )
    web_search_fallback: bool = DEFAULT_WEB_SEARCH_FALLBACK


def _config_path() -> Path:
    return Path(get_settings().iafood_config_path)


def load_limits() -> IafoodLimits:
    path = _config_path()
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return IafoodLimits()
    return IafoodLimits.model_validate(json.loads(raw))


def save_limits(limits: IafoodLimits) -> None:
    path = _config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(limits.model_dump(), indent=2), encoding="utf-8")
    os.chmod(tmp_path, 0o600)
    tmp_path.replace(path)
