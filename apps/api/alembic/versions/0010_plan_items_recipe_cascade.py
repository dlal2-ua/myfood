"""ON DELETE CASCADE en plan_items.recipe_id (Fase 7 — batch cooking).

Bug real destapado por el batch cooking (Fase 7, 7/N): `recipe_id` nunca
se poblaba antes de esta fase, así que esta FK sin acción de borrado nunca
había importado en la práctica. En cuanto un `plan_item` puede apuntar a
una receta de verdad, borrar esa receta (`DELETE /recipes/{id}`, o en
cascada al borrar la cuenta del usuario vía `/privacy/delete-account`,
Fase 7 3/N) revienta con una violación de FK. `SET NULL` no vale: el CHECK
`(food_id IS NULL) <> (recipe_id IS NULL)` exige que quede exactamente uno
de los dos — la única opción consistente es que el propio `plan_item`
desaparezca con la receta.

Revision ID: 0010
Revises: 0009
Create Date: 2026-09-18
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.get_bind().exec_driver_sql("""
        ALTER TABLE plan_items DROP CONSTRAINT plan_items_recipe_id_fkey;
        ALTER TABLE plan_items
          ADD CONSTRAINT plan_items_recipe_id_fkey
          FOREIGN KEY (recipe_id) REFERENCES recipes(id) ON DELETE CASCADE;
    """)


def downgrade() -> None:
    op.get_bind().exec_driver_sql("""
        ALTER TABLE plan_items DROP CONSTRAINT plan_items_recipe_id_fkey;
        ALTER TABLE plan_items
          ADD CONSTRAINT plan_items_recipe_id_fkey
          FOREIGN KEY (recipe_id) REFERENCES recipes(id);
    """)
