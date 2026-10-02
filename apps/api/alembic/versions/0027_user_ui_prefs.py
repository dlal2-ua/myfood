"""Preferencias de interfaz de cada usuario.

De momento solo una: qué avisos tiene plegados. Los avisos fijos de la app (el de «no es
consejo médico», el de «estimación orientativa»…) ocupan media pantalla en un móvil y, una vez
leídos, el usuario quiere poder dejarlos en una línea. Se guarda en su cuenta y no en el
navegador para que el plegado le siga a cualquier dispositivo en el que entre.

Es un JSON y no una columna por preferencia a propósito: son ajustes de pantalla, no datos
sobre los que se vaya a consultar, y así el siguiente no necesita migración.

Revision ID: 0027
Revises: 0026
Create Date: 2026-10-02
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0027"
down_revision: str | None = "0026"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.get_bind().exec_driver_sql(
        "ALTER TABLE users ADD COLUMN ui_prefs JSONB NOT NULL DEFAULT '{}'::jsonb;"
    )


def downgrade() -> None:
    op.get_bind().exec_driver_sql("ALTER TABLE users DROP COLUMN IF EXISTS ui_prefs;")
