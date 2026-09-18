"""2FA por TOTP (Fase 7).

`totp_secret` cifrado en reposo con el mismo mecanismo de aplicación que
`profiles`/`body_measurements` (R4-adjacent: es una credencial, no datos de
salud, pero el mismo criterio de "nunca en claro" aplica). `totp_enabled`
por separado permite generar/regenerar un secreto sin activarlo hasta que
el usuario confirme un código real.

Revision ID: 0008
Revises: 0007
Create Date: 2026-09-18
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("totp_secret", sa.Text(), nullable=True))
    op.add_column(
        "users",
        sa.Column("totp_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("users", "totp_enabled")
    op.drop_column("users", "totp_secret")
