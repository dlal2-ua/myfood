"""Añade 'recipe_import' a los `kind` posibles de `ai_sessions`.

Mismo motivo que la migración 0006 para 'smart_log': la importación de
recetas desde URL (sección 20) es otro tipo de sesión de iafood que no
encajaba en el CHECK original de la migración 0001.

Revision ID: 0007
Revises: 0006
Create Date: 2026-09-12
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OLD_KINDS = ("diet_plan", "plan_review", "supplement_suggestion", "chat_edit", "smart_log")
_NEW_KINDS = (*_OLD_KINDS, "recipe_import")


def upgrade() -> None:
    op.get_bind().exec_driver_sql("""
        ALTER TABLE ai_sessions DROP CONSTRAINT ai_sessions_kind_check;
    """)
    kinds_sql = ", ".join(f"'{k}'" for k in _NEW_KINDS)
    op.get_bind().exec_driver_sql(f"""
        ALTER TABLE ai_sessions
        ADD CONSTRAINT ai_sessions_kind_check CHECK (kind IN ({kinds_sql}));
    """)


def downgrade() -> None:
    op.get_bind().exec_driver_sql("""
        ALTER TABLE ai_sessions DROP CONSTRAINT ai_sessions_kind_check;
    """)
    kinds_sql = ", ".join(f"'{k}'" for k in _OLD_KINDS)
    op.get_bind().exec_driver_sql(f"""
        ALTER TABLE ai_sessions
        ADD CONSTRAINT ai_sessions_kind_check CHECK (kind IN ({kinds_sql}));
    """)
