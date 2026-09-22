"""Ajustes de la instancia que el administrador cambia en caliente.

Mismo patrón que `ai/limits.py`: un fichero pequeño en disco que se lee en cada petición, no
una variable de entorno, para poder cambiarlo desde `/admin` sin reiniciar el stack. Aquí va
solo lo que decide el dueño de la instancia sobre quién entra, no configuración de despliegue.
"""

import json
import os
from pathlib import Path

from pydantic import BaseModel, Field

from myfood.config import get_settings

# Por defecto, cerrado: la app está publicada en internet y abrirla a cualquiera no puede ser
# lo que pase si el fichero de ajustes desaparece.
DEFAULT_INVITE_ONLY = True


class AppSettings(BaseModel):
    """`invite_only`: registrarse exige un código de invitación del administrador.
    `ai_enabled_by_default`: si las cuentas nuevas nacen pudiendo usar la IA."""

    invite_only: bool = Field(default=DEFAULT_INVITE_ONLY)
    ai_enabled_by_default: bool = Field(default=False)


def _path() -> Path:
    return Path(get_settings().iafood_config_path).with_name("app.json")


def load_app_settings() -> AppSettings:
    try:
        raw = _path().read_text(encoding="utf-8")
    except FileNotFoundError:
        return AppSettings()
    try:
        return AppSettings.model_validate(json.loads(raw))
    except ValueError:
        # Un fichero corrupto no puede acabar abriendo el registro a cualquiera.
        return AppSettings()


def save_app_settings(settings: AppSettings) -> None:
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(settings.model_dump(), indent=2), encoding="utf-8")
    os.chmod(tmp_path, 0o600)
    tmp_path.replace(path)
