"""Un usuario solo puede tener una ventana de ayuno abierta (Fase 7: ayuno intermitente).

`fasting_windows` existe desde el esquema inicial pero nada la usaba. Con el temporizador hace falta
garantizar en la propia base de datos que no se abren dos ayunos a la vez (dos pestañas, un doble
toque): índice único parcial sobre las ventanas sin `ended_at`.

Revision ID: 0014
Revises: 0013
Create Date: 2026-09-20
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.get_bind().exec_driver_sql("""
        CREATE UNIQUE INDEX fasting_windows_one_open_per_user
          ON fasting_windows (user_id) WHERE ended_at IS NULL;
    """)


def downgrade() -> None:
    op.get_bind().exec_driver_sql("DROP INDEX fasting_windows_one_open_per_user;")
