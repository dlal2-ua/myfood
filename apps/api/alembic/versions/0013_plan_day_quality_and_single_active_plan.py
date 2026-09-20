"""Calidad de cada día de un plan y un único plan activo por usuario (Fase 4).

- `plan_days.warning` y `plan_days.is_optimal`: si las kcal del día quedan a más de un 5 % del
  objetivo el motor lo marca `TARGETS_NOT_MET` (sección 9), y si el solver agotó el tiempo y
  devuelve su mejor solución, `is_optimal = false`. Hasta ahora no se guardaba nada de esto.
- Índice único parcial: un usuario solo puede tener un plan `active`. Antes se podían activar
  varios a la vez y no estaba claro cuál era «el plan de hoy». Los duplicados existentes se
  archivan (se conserva el más reciente de cada usuario).

Revision ID: 0013
Revises: 0012
Create Date: 2026-09-20
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.get_bind().exec_driver_sql("""
        ALTER TABLE plan_days
          ADD COLUMN warning TEXT,
          ADD COLUMN is_optimal BOOLEAN NOT NULL DEFAULT TRUE;

        UPDATE diet_plans SET status = 'archived'
         WHERE status = 'active'
           AND id NOT IN (
               SELECT DISTINCT ON (user_id) id FROM diet_plans
                WHERE status = 'active'
                ORDER BY user_id, created_at DESC
           );

        CREATE UNIQUE INDEX diet_plans_one_active_per_user
          ON diet_plans (user_id) WHERE status = 'active';
    """)


def downgrade() -> None:
    op.get_bind().exec_driver_sql("""
        DROP INDEX diet_plans_one_active_per_user;
        ALTER TABLE plan_days DROP COLUMN warning, DROP COLUMN is_optimal;
    """)
