"""Añade 'receipt_scan' a los `kind` posibles de `ai_sessions`.

Mismo motivo que las migraciones 0006/0007 para 'smart_log'/'recipe_import':
el escaneo OCR de tickets de compra (Fase 7) es otro tipo de sesión de
iafood que no encajaba en el CHECK original.

Revision ID: 0009
Revises: 0008
Create Date: 2026-09-18
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OLD_KINDS = ("diet_plan", "plan_review", "supplement_suggestion", "chat_edit", "smart_log", "recipe_import")
_NEW_KINDS = (*_OLD_KINDS, "receipt_scan")


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
