"""Añade 'smart_log' a los `kind` posibles de `ai_sessions`.

La migración 0001 fijó el CHECK de `ai_sessions.kind` a los cuatro tipos
conocidos entonces ('diet_plan', 'plan_review', 'supplement_suggestion',
'chat_edit') — el registro por lenguaje natural ("Smart Log", sección 10.8)
es un quinto tipo de sesión de iafood que no encajaba en ninguno.

Revision ID: 0006
Revises: 0005
Create Date: 2026-09-12
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OLD_KINDS = ("diet_plan", "plan_review", "supplement_suggestion", "chat_edit")
_NEW_KINDS = (*_OLD_KINDS, "smart_log")


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
