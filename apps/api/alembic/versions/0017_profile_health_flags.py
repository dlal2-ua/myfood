"""Declaraciones de salud del perfil que bloquean la sugerencia de suplementos (sección 10.7).

Embarazo/lactancia y patología o medicación: si el perfil las declara, iafood NO sugiere
suplementos (`403 SUPPLEMENT_ADVICE_BLOCKED`). Son datos de salud de categoría especial (RGPD art. 9,
R4): un único campo cifrado en reposo con la lista de declaraciones.

Revision ID: 0017
Revises: 0016
Create Date: 2026-09-21
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0017"
down_revision: str | None = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.get_bind().exec_driver_sql("ALTER TABLE profiles ADD COLUMN health_flags TEXT;")


def downgrade() -> None:
    op.get_bind().exec_driver_sql("ALTER TABLE profiles DROP COLUMN health_flags;")
