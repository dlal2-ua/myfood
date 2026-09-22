"""Recetario compartido: recetas que no son de nadie y todos pueden ver.

Hasta ahora una receta era siempre de un usuario (`user_id NOT NULL`, aislada por RLS), así que
el recetario solo tenía lo que cada uno escribía a mano. Para traer un catálogo de platos
—ingredientes y pasos— hace falta que una receta pueda no tener dueño.

`user_id IS NULL` significa «del catálogo»: cualquiera la ve, nadie la edita. Las políticas se
separan por operación porque la de lectura pasa a ser más amplia que las de escritura: leer,
las tuyas y las del catálogo; escribir, solo las tuyas.

Revision ID: 0022
Revises: 0021
Create Date: 2026-09-22
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0022"
down_revision: str | None = "0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SELF = "current_setting('app.current_user_id', true)::uuid"


def upgrade() -> None:
    op.get_bind().exec_driver_sql(f"""
        ALTER TABLE recipes ALTER COLUMN user_id DROP NOT NULL;
        ALTER TABLE recipes ADD COLUMN source text NOT NULL DEFAULT 'user';
        ALTER TABLE recipes ADD COLUMN source_id text;
        ALTER TABLE recipes ADD COLUMN image_url text;
        ALTER TABLE recipes ADD COLUMN cuisine text;
        ALTER TABLE recipes ADD COLUMN category text;
        -- Las condiciones de la fuente piden citarla: se guarda con la receta, no en el
        -- código, para que viaje con ella si algún día se exporta.
        ALTER TABLE recipes ADD COLUMN attribution text;

        -- Reimportar no puede duplicar: la clave natural es (fuente, id en la fuente).
        CREATE UNIQUE INDEX recipes_source_key ON recipes (source, source_id)
          WHERE source_id IS NOT NULL;

        -- Una receta es de alguien o del catálogo, nunca a medias.
        ALTER TABLE recipes ADD CONSTRAINT recipes_owned_or_public
          CHECK ((user_id IS NULL) = (source <> 'user'));

        DROP POLICY IF EXISTS recipes_isolation ON recipes;
        CREATE POLICY recipes_select ON recipes FOR SELECT
          USING (user_id = {_SELF} OR user_id IS NULL);
        CREATE POLICY recipes_insert ON recipes FOR INSERT
          WITH CHECK (user_id = {_SELF});
        CREATE POLICY recipes_update ON recipes FOR UPDATE
          USING (user_id = {_SELF}) WITH CHECK (user_id = {_SELF});
        CREATE POLICY recipes_delete ON recipes FOR DELETE
          USING (user_id = {_SELF});
    """)


def downgrade() -> None:
    op.get_bind().exec_driver_sql(f"""
        DROP POLICY IF EXISTS recipes_select ON recipes;
        DROP POLICY IF EXISTS recipes_insert ON recipes;
        DROP POLICY IF EXISTS recipes_update ON recipes;
        DROP POLICY IF EXISTS recipes_delete ON recipes;
        CREATE POLICY recipes_isolation ON recipes USING (user_id = {_SELF});

        ALTER TABLE recipes DROP CONSTRAINT IF EXISTS recipes_owned_or_public;
        DROP INDEX IF EXISTS recipes_source_key;
        DELETE FROM recipes WHERE user_id IS NULL;
        ALTER TABLE recipes DROP COLUMN IF EXISTS attribution;
        ALTER TABLE recipes DROP COLUMN IF EXISTS category;
        ALTER TABLE recipes DROP COLUMN IF EXISTS cuisine;
        ALTER TABLE recipes DROP COLUMN IF EXISTS image_url;
        ALTER TABLE recipes DROP COLUMN IF EXISTS source_id;
        ALTER TABLE recipes DROP COLUMN IF EXISTS source;
        ALTER TABLE recipes ALTER COLUMN user_id SET NOT NULL;
    """)
