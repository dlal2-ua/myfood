"""Concede BYPASSRLS al rol admin (sección 22).

Bug descubierto en la Fase 3: la migración 0002 documenta que `myfood_admin`
no está sujeto a las políticas RLS ("usado solo en /admin/*"), pero
`FORCE ROW LEVEL SECURITY` (0001/0002) se aplica a TODOS los roles salvo
al dueño de la tabla o a uno con el atributo `BYPASSRLS` — nunca se concedió.
En la práctica, `AdminSessionLocal`/`get_admin_session` no podían leer ni
escribir ninguna fila de las tablas con RLS (todo `WHERE`/`CHECK` evalúa
contra `current_setting('app.current_user_id', true)` sin fijar, que da
`NULL`). Sin rutas `/admin/*` construidas todavía, no se había detectado
hasta que el worker de recordatorios (Fase 3) necesitó leer
`notification_rules`/`push_subscriptions` de todos los usuarios.

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-12
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.get_bind().exec_driver_sql("ALTER ROLE myfood_admin BYPASSRLS;")


def downgrade() -> None:
    op.get_bind().exec_driver_sql("ALTER ROLE myfood_admin NOBYPASSRLS;")
