"""Protección de la credencial real de iafood (`conftest.py`): la suite corre
contra el mismo Postgres que producción y vacía/crea la fila única de
`ai_credentials` — al terminar la sesión se restaura la que hubiera antes.
Aquí se comprueba la mecánica de copia/restauración (los casts bytea/
timestamptz/uuid son justo lo que fallaría en silencio), siempre con un
fichero de copia en `tmp_path` para no tocar el de la sesión real."""

import json
import stat
import uuid

import pytest
from sqlalchemy import text

from tests.conftest import _SELECT_CREDENTIAL, _restore_credential, _write_credential_backup

# Bytes arbitrarios (incluidos no-UTF-8): un token cifrado real es binario.
_TOKEN = bytes(range(256))


def _insert_credential(conn, *, updated_by=None) -> None:
    conn.execute(
        text(
            "INSERT INTO ai_credentials (id, provider, token_encrypted, updated_by, updated_at) "
            "VALUES (1, 'anthropic', :t, :u, '2026-01-02 03:04:05.678901+00')"
        ),
        {"t": _TOKEN, "u": str(updated_by) if updated_by else None},
    )


def test_backup_and_restore_round_trip_preserves_every_column(
    protect_real_ai_credential, tmp_path
):
    engine = protect_real_ai_credential
    if engine is None:
        pytest.skip("sin BD alcanzable")

    with engine.begin() as conn:
        _insert_credential(conn)
        original = conn.execute(_SELECT_CREDENTIAL).first()

    backup = tmp_path / "backup.json"
    _write_credential_backup(original, backup)
    assert stat.S_IMODE(backup.stat().st_mode) == 0o600

    with engine.begin() as conn:
        conn.execute(text("DELETE FROM ai_credentials"))
        assert conn.execute(_SELECT_CREDENTIAL).first() is None
        _restore_credential(conn, json.loads(backup.read_text()))
        restored = conn.execute(_SELECT_CREDENTIAL).first()
        conn.execute(text("DELETE FROM ai_credentials"))

    assert bytes(restored.token_encrypted) == _TOKEN
    assert restored.provider == original.provider
    assert restored.updated_by == original.updated_by
    assert restored.updated_at == original.updated_at


def test_restore_keeps_updated_by_when_that_user_still_exists(
    protect_real_ai_credential, two_users, tmp_path
):
    engine = protect_real_ai_credential
    if engine is None:
        pytest.skip("sin BD alcanzable")
    user_id, _ = two_users

    with engine.begin() as conn:
        _insert_credential(conn, updated_by=user_id)
        original = conn.execute(_SELECT_CREDENTIAL).first()
    payload = _write_credential_backup(original, tmp_path / "backup.json")

    with engine.begin() as conn:
        _restore_credential(conn, payload)
        restored = conn.execute(_SELECT_CREDENTIAL).first()
        # Fuera antes de que `two_users` borre a su usuario (FK).
        conn.execute(text("DELETE FROM ai_credentials"))

    assert restored.updated_by == user_id


def test_restore_drops_updated_by_when_that_user_no_longer_exists(
    protect_real_ai_credential, tmp_path
):
    """Perder `updated_by` es aceptable; perder el token por una violación de
    la FK, no."""
    engine = protect_real_ai_credential
    if engine is None:
        pytest.skip("sin BD alcanzable")

    payload = {
        "provider": "anthropic",
        "token_encrypted": "AAEC",
        "updated_by": str(uuid.uuid4()),
        "updated_at": "2026-01-02T03:04:05.678901+00:00",
    }
    with engine.begin() as conn:
        _restore_credential(conn, payload)
        restored = conn.execute(_SELECT_CREDENTIAL).first()
        conn.execute(text("DELETE FROM ai_credentials"))

    assert bytes(restored.token_encrypted) == b"\x00\x01\x02"
    assert restored.updated_by is None


def test_table_starts_empty_for_every_test(protect_real_ai_credential):
    """Ningún test debe depender de si hay o no un token real en la BD."""
    engine = protect_real_ai_credential
    if engine is None:
        pytest.skip("sin BD alcanzable")
    with engine.begin() as conn:
        assert conn.execute(_SELECT_CREDENTIAL).first() is None
