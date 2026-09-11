"""Row-Level Security (R11, sección 22).

Segunda capa de aislamiento multiusuario, independiente del filtrado
`WHERE user_id = ...` en código (R3). El rol de aplicación myfood_app queda
sujeto a estas políticas; myfood_admin (usado solo en /admin/*) no.

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-10
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Tablas con columna user_id — sección 22, lista exacta de la especificación.
RLS_TABLES = [
    "profiles", "body_measurements", "user_restrictions", "recipes",
    "pantry_items", "shopping_list_items", "diet_plans", "food_log",
    "water_log", "water_settings", "supplements", "supplement_log",
    "supplement_stock", "fasting_windows", "push_subscriptions",
    "notification_rules", "ai_sessions", "ai_proposals", "tdee_estimates",
    "user_favorite_foods", "chat_messages",
]


def upgrade() -> None:
    for table in RLS_TABLES:
        # supplement_stock no tiene user_id propio: se filtra vía la FK a supplements.
        if table == "supplement_stock":
            op.get_bind().exec_driver_sql(f"""
            ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;
            ALTER TABLE {table} FORCE ROW LEVEL SECURITY;
            CREATE POLICY {table}_isolation ON {table}
              USING (
                supplement_id IN (
                  SELECT id FROM supplements
                  WHERE user_id = current_setting('app.current_user_id', true)::uuid
                )
              );
            """)
        else:
            op.get_bind().exec_driver_sql(f"""
            ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;
            ALTER TABLE {table} FORCE ROW LEVEL SECURITY;
            CREATE POLICY {table}_isolation ON {table}
              USING (user_id = current_setting('app.current_user_id', true)::uuid);
            """)


def downgrade() -> None:
    for table in RLS_TABLES:
        op.get_bind().exec_driver_sql(f"""
        DROP POLICY IF EXISTS {table}_isolation ON {table};
        ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY;
        ALTER TABLE {table} DISABLE ROW LEVEL SECURITY;
        """)
