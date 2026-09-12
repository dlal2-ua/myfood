"""Tipos cifrados a nivel de aplicación para columnas de datos de salud (R4).

Se usan en `profiles` (sex, birth_date, height_cm) y en `body_measurements`
(todos los numéricos), según la sección 6.7 de la especificación. El cifrado
es AES-GCM con `ENCRYPTION_KEY`; no se puede filtrar ni ordenar por estas
columnas en SQL — se descifra en memoria tras leer.
"""

import base64
import os
from datetime import date
from decimal import Decimal

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from sqlalchemy import String
from sqlalchemy.types import TypeDecorator

from myfood.config import get_settings


def _key_bytes() -> bytes:
    hex_key = get_settings().encryption_key
    return bytes.fromhex(hex_key)


def _encrypt(plaintext: str) -> str:
    key = _key_bytes()
    aesgcm = AESGCM(key)
    nonce = os.urandom(12)
    ciphertext = aesgcm.encrypt(nonce, plaintext.encode("utf-8"), None)
    return base64.b64encode(nonce + ciphertext).decode("ascii")


def _decrypt(token: str) -> str:
    raw = base64.b64decode(token)
    nonce, ciphertext = raw[:12], raw[12:]
    aesgcm = AESGCM(_key_bytes())
    return aesgcm.decrypt(nonce, ciphertext, None).decode("utf-8")


def encrypt_to_bytes(plaintext: str) -> bytes:
    """Como `_encrypt`, pero para columnas BYTEA (p. ej. `ai_credentials.token_encrypted`,
    sección 6.7) en vez de columnas de texto — sin la capa de base64."""
    key = _key_bytes()
    aesgcm = AESGCM(key)
    nonce = os.urandom(12)
    return nonce + aesgcm.encrypt(nonce, plaintext.encode("utf-8"), None)


def decrypt_from_bytes(blob: bytes) -> str:
    nonce, ciphertext = blob[:12], blob[12:]
    aesgcm = AESGCM(_key_bytes())
    return aesgcm.decrypt(nonce, ciphertext, None).decode("utf-8")


class EncryptedText(TypeDecorator):
    """Texto cifrado en reposo (p. ej. `sex`)."""

    impl = String
    cache_ok = True

    def process_bind_param(self, value: str | None, dialect) -> str | None:
        if value is None:
            return None
        return _encrypt(value)

    def process_result_value(self, value: str | None, dialect) -> str | None:
        if value is None:
            return None
        return _decrypt(value)


class EncryptedDate(TypeDecorator):
    """Fecha cifrada en reposo (p. ej. `birth_date`)."""

    impl = String
    cache_ok = True

    def process_bind_param(self, value: date | None, dialect) -> str | None:
        if value is None:
            return None
        return _encrypt(value.isoformat())

    def process_result_value(self, value: str | None, dialect) -> date | None:
        if value is None:
            return None
        return date.fromisoformat(_decrypt(value))


class EncryptedNumeric(TypeDecorator):
    """Numérico cifrado en reposo (p. ej. `height_cm`, medidas corporales)."""

    impl = String
    cache_ok = True

    def process_bind_param(self, value: Decimal | float | None, dialect) -> str | None:
        if value is None:
            return None
        return _encrypt(str(value))

    def process_result_value(self, value: str | None, dialect) -> Decimal | None:
        if value is None:
            return None
        return Decimal(_decrypt(value))
