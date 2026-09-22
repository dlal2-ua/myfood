"""Invitaciones y control de acceso a la IA.

La app es accesible desde internet, así que registrarse deja de ser libre: hace falta un
código que genera el administrador, de un solo uso, igual que en openGym. Las cuentas que ya
existían no se tocan (decisión del usuario: respetar las que hay y exigir código a las nuevas).

`users.ai_enabled` separa «tener cuenta» de «poder gastar la cuota de Claude»: el
administrador decide a quién deja usar la IA, que es lo que cuesta dinero.

Revision ID: 0019
Revises: 0018
Create Date: 2026-09-22
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0019"
down_revision: str | None = "0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.get_bind().exec_driver_sql("""
        CREATE TABLE invites (
          code        text PRIMARY KEY,
          note        text,
          created_by  uuid REFERENCES users(id) ON DELETE SET NULL,
          created_at  timestamptz NOT NULL DEFAULT now(),
          -- Un solo uso: al registrarse queda marcado y ya no vale para nadie más.
          used_by     uuid REFERENCES users(id) ON DELETE SET NULL,
          used_at     timestamptz,
          revoked_at  timestamptz
        );
        CREATE INDEX invites_usable_idx ON invites (code)
          WHERE used_by IS NULL AND revoked_at IS NULL;

        -- Sin RLS: `invites` no es de nadie, solo la tocan las rutas /admin/* (rol
        -- myfood_admin) y el registro, que corre sin sesión de usuario.

        ALTER TABLE users ADD COLUMN ai_enabled boolean NOT NULL DEFAULT true;
        ALTER TABLE users ADD COLUMN invited_with text REFERENCES invites(code) ON DELETE SET NULL;
        ALTER TABLE users ADD COLUMN last_seen_at timestamptz;
    """)


def downgrade() -> None:
    op.get_bind().exec_driver_sql("""
        ALTER TABLE users DROP COLUMN IF EXISTS last_seen_at;
        ALTER TABLE users DROP COLUMN IF EXISTS invited_with;
        ALTER TABLE users DROP COLUMN IF EXISTS ai_enabled;
        DROP TABLE IF EXISTS invites;
    """)
