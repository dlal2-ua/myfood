"""El administrador que puso la credencial de iafood puede borrar su cuenta.

`ai_credentials.updated_by` referenciaba a `users(id)` sin `ON DELETE`: el usuario que había guardado
la credencial no podía eliminar su cuenta (`POST /privacy/delete-account` devolvía un error de
integridad). Ahora la referencia pasa a NULL y la credencial se conserva.

Revision ID: 0015
Revises: 0014
Create Date: 2026-09-20
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.get_bind().exec_driver_sql("""
        ALTER TABLE ai_credentials DROP CONSTRAINT ai_credentials_updated_by_fkey;
        ALTER TABLE ai_credentials
          ADD CONSTRAINT ai_credentials_updated_by_fkey
          FOREIGN KEY (updated_by) REFERENCES users(id) ON DELETE SET NULL;
    """)


def downgrade() -> None:
    op.get_bind().exec_driver_sql("""
        ALTER TABLE ai_credentials DROP CONSTRAINT ai_credentials_updated_by_fkey;
        ALTER TABLE ai_credentials
          ADD CONSTRAINT ai_credentials_updated_by_fkey FOREIGN KEY (updated_by) REFERENCES users(id);
    """)
