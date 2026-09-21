"""Logros ya conseguidos, para poder avisar al usuario una sola vez (Fase 7, R10).

Hasta ahora los logros se calculaban al vuelo en cada `GET /gamification/summary` y no
quedaba constancia de ninguno: sin fila no hay forma de distinguir "lo acaba de conseguir"
de "lo tiene desde hace meses", así que no se podía notificar sin repetirse cada vez.

`notified_at` es lo que impide que el aviso se mande dos veces: el worker solo envía los
logros con `notified_at IS NULL` y lo marca en la misma transacción.

Revision ID: 0018
Revises: 0017
Create Date: 2026-09-21
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0018"
down_revision: str | None = "0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SELF = "current_setting('app.current_user_id', true)::uuid"


def upgrade() -> None:
    op.get_bind().exec_driver_sql(f"""
        CREATE TABLE user_achievements (
          id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          user_id     uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
          key         text NOT NULL,
          earned_on   date NOT NULL,
          notified_at timestamptz,
          created_at  timestamptz NOT NULL DEFAULT now(),
          UNIQUE (user_id, key)
        );
        CREATE INDEX user_achievements_pending_idx
          ON user_achievements (user_id) WHERE notified_at IS NULL;

        ALTER TABLE user_achievements ENABLE ROW LEVEL SECURITY;
        ALTER TABLE user_achievements FORCE ROW LEVEL SECURITY;
        CREATE POLICY user_achievements_isolation ON user_achievements
          USING (user_id = {_SELF});
    """)


def downgrade() -> None:
    op.get_bind().exec_driver_sql("""
        DROP POLICY IF EXISTS user_achievements_isolation ON user_achievements;
        DROP TABLE IF EXISTS user_achievements;
    """)
