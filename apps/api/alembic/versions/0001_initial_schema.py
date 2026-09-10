"""Esquema inicial completo (sección 6 de la especificación).

Crea las extensiones necesarias, los roles de conexión (myfood_app sujeto a
RLS, myfood_admin sin RLS) y todas las tablas de las secciones 6.1-6.10.
Las políticas RLS en sí se activan en la migración 0002 (sección 22).

Revision ID: 0001
Revises:
Create Date: 2026-09-10
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op
from myfood.config import get_settings

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.get_bind().exec_driver_sql("""
    CREATE EXTENSION IF NOT EXISTS pg_trgm;
    CREATE EXTENSION IF NOT EXISTS citext;
    CREATE EXTENSION IF NOT EXISTS vector;
    """)

    # --- Roles de conexión (sección 22) ---------------------------------
    op.get_bind().exec_driver_sql("""
    DO $$
    BEGIN
      IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'myfood_app') THEN
        CREATE ROLE myfood_app LOGIN;
      END IF;
      IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'myfood_admin') THEN
        CREATE ROLE myfood_admin LOGIN;
      END IF;
    END $$;
    """)
    # Contraseñas desde .env — con parámetros bind, nunca interpoladas en el SQL.
    settings = get_settings()
    bind = op.get_bind()
    bind.execute(
        sa.text("ALTER ROLE myfood_app WITH PASSWORD :pwd"),
        {"pwd": settings.postgres_app_password},
    )
    bind.execute(
        sa.text("ALTER ROLE myfood_admin WITH PASSWORD :pwd"),
        {"pwd": settings.postgres_admin_password},
    )

    # --- 6.1 Usuarios y perfil ------------------------------------------
    op.get_bind().exec_driver_sql("""
    CREATE TABLE users (
      id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      email           CITEXT UNIQUE NOT NULL,
      password_hash   TEXT NOT NULL,
      display_name    TEXT NOT NULL,
      role            TEXT NOT NULL DEFAULT 'user' CHECK (role IN ('user','admin')),
      locale          TEXT NOT NULL DEFAULT 'es',
      timezone        TEXT NOT NULL DEFAULT 'Europe/Madrid',
      is_active       BOOLEAN NOT NULL DEFAULT TRUE,
      created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
    );

    CREATE TABLE consents (
      id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      user_id     UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
      kind        TEXT NOT NULL,
      version     TEXT NOT NULL,
      granted_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
      revoked_at  TIMESTAMPTZ
    );
    CREATE INDEX ON consents (user_id, kind);

    CREATE TABLE profiles (
      user_id           UUID PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
      sex               TEXT,
      birth_date        TEXT,
      height_cm         TEXT,
      activity_level    TEXT NOT NULL DEFAULT 'moderate'
                        CHECK (activity_level IN ('sedentary','light','moderate','active','very_active')),
      goal              TEXT NOT NULL DEFAULT 'maintain'
                        CHECK (goal IN ('lose','maintain','gain')),
      goal_rate_kg_week NUMERIC(3,2) DEFAULT 0.50,
      bmr_formula       TEXT NOT NULL DEFAULT 'mifflin'
                        CHECK (bmr_formula IN ('mifflin','katch','cunningham','harris')),
      meals_per_day     SMALLINT NOT NULL DEFAULT 4,
      budget_eur_week   NUMERIC(10,2),
      max_cook_minutes  SMALLINT,
      diet_style        TEXT,
      updated_at        TIMESTAMPTZ NOT NULL DEFAULT now()
    );

    CREATE TABLE allergens (
      code  TEXT PRIMARY KEY,
      name_es TEXT NOT NULL
    );

    CREATE TABLE user_restrictions (
      id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      user_id    UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
      kind       TEXT NOT NULL CHECK (kind IN ('allergen','intolerance','disliked_food','banned_food')),
      allergen_code TEXT REFERENCES allergens(code),
      food_id    UUID,
      note       TEXT
    );
    CREATE INDEX ON user_restrictions (user_id);
    """)

    # --- 6.2 Medidas corporales ------------------------------------------
    # Nota: columnas numéricas cifradas a nivel de aplicación (sección 6.7) se
    # almacenan como TEXT (payload base64 de AES-GCM), no como NUMERIC nativo.
    op.get_bind().exec_driver_sql("""
    CREATE TABLE body_measurements (
      id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      user_id        UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
      measured_on    DATE NOT NULL,
      weight_kg      TEXT,
      body_fat_pct   TEXT,
      bf_method      TEXT CHECK (bf_method IN ('navy','jackson3','jackson7','durnin','bia','manual')),
      neck_cm        TEXT,
      waist_cm       TEXT,
      hip_cm         TEXT,
      chest_cm       TEXT,
      arm_cm         TEXT,
      thigh_cm       TEXT,
      source         TEXT NOT NULL DEFAULT 'manual'
                     CHECK (source IN ('manual','health_connect','scale')),
      created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
      UNIQUE (user_id, measured_on)
    );
    CREATE INDEX ON body_measurements (user_id, measured_on DESC);
    """)

    # --- 6.3 Alimentos, nutrientes e imágenes -----------------------------
    op.get_bind().exec_driver_sql("""
    CREATE TABLE foods (
      id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      kind             TEXT NOT NULL CHECK (kind IN ('generic','branded','recipe','user')),
      source           TEXT NOT NULL,
      source_id        TEXT,
      license          TEXT NOT NULL,
      attribution      TEXT,
      barcode_ean      TEXT,
      name_es          TEXT NOT NULL,
      name_en          TEXT,
      brand            TEXT,
      category         TEXT,
      serving_size_g   NUMERIC(8,2),
      serving_label    TEXT,
      quality_rank     SMALLINT NOT NULL,
      is_verified      BOOLEAN NOT NULL DEFAULT FALSE,
      nutriscore_grade  CHAR(1) CHECK (nutriscore_grade IN ('a','b','c','d','e')),
      nova_group        SMALLINT CHECK (nova_group BETWEEN 1 AND 4),
      ecoscore_grade    CHAR(1) CHECK (ecoscore_grade IN ('a','b','c','d','e')),
      cooking_yield_factor NUMERIC(4,2),
      created_by       UUID REFERENCES users(id) ON DELETE SET NULL,
      created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
    );
    CREATE UNIQUE INDEX ON foods (barcode_ean) WHERE barcode_ean IS NOT NULL AND kind = 'branded';
    CREATE INDEX ON foods USING gin (name_es gin_trgm_ops);
    CREATE INDEX ON foods (kind, quality_rank);

    CREATE TABLE food_nutrients (
      food_id        UUID PRIMARY KEY REFERENCES foods(id) ON DELETE CASCADE,
      kcal_100g      NUMERIC(10,3) NOT NULL,
      protein_100g   NUMERIC(10,3) NOT NULL DEFAULT 0,
      fat_100g       NUMERIC(10,3) NOT NULL DEFAULT 0,
      saturated_100g NUMERIC(10,3),
      carbs_100g     NUMERIC(10,3) NOT NULL DEFAULT 0,
      sugars_100g    NUMERIC(10,3),
      fiber_100g     NUMERIC(10,3),
      salt_100g      NUMERIC(10,3),
      micros         JSONB NOT NULL DEFAULT '{}'::jsonb
    );

    CREATE TABLE food_vectors (
      food_id   UUID PRIMARY KEY REFERENCES foods(id) ON DELETE CASCADE,
      vec       vector(6) NOT NULL
    );
    CREATE INDEX ON food_vectors USING hnsw (vec vector_l2_ops);

    CREATE TABLE food_images (
      id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      food_id       UUID NOT NULL REFERENCES foods(id) ON DELETE CASCADE,
      type          TEXT NOT NULL CHECK (type IN ('front','ingredients','nutrition','packaging')),
      remote_url    TEXT,
      local_path    TEXT,
      width         INT,
      height        INT,
      source        TEXT NOT NULL,
      license       TEXT,
      attribution   TEXT,
      last_access_at TIMESTAMPTZ,
      bytes         BIGINT,
      created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
      UNIQUE (food_id, type)
    );
    CREATE INDEX ON food_images (last_access_at);

    CREATE TABLE food_allergens (
      food_id       UUID NOT NULL REFERENCES foods(id) ON DELETE CASCADE,
      allergen_code TEXT NOT NULL REFERENCES allergens(code),
      PRIMARY KEY (food_id, allergen_code)
    );
    """)

    # --- 6.4 Recetas, despensa y compra ------------------------------------
    op.get_bind().exec_driver_sql("""
    CREATE TABLE recipes (
      id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      user_id       UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
      name          TEXT NOT NULL,
      servings      SMALLINT NOT NULL DEFAULT 1,
      prep_minutes  SMALLINT,
      instructions  TEXT,
      food_id       UUID REFERENCES foods(id) ON DELETE SET NULL,
      internal_ean  TEXT UNIQUE,
      created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
    );
    CREATE INDEX ON recipes (user_id);

    CREATE TABLE recipe_ingredients (
      id        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      recipe_id UUID NOT NULL REFERENCES recipes(id) ON DELETE CASCADE,
      food_id   UUID NOT NULL REFERENCES foods(id),
      grams     NUMERIC(8,2) NOT NULL
    );

    CREATE TABLE pantry_items (
      id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      user_id    UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
      food_id    UUID NOT NULL REFERENCES foods(id),
      quantity_g NUMERIC(10,2) NOT NULL,
      expires_on DATE,
      updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
    );
    CREATE INDEX ON pantry_items (user_id);

    CREATE TABLE shopping_list_items (
      id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      user_id    UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
      food_id    UUID REFERENCES foods(id),
      free_text  TEXT,
      quantity_g NUMERIC(10,2),
      category   TEXT,
      is_checked BOOLEAN NOT NULL DEFAULT FALSE,
      plan_id    UUID,
      created_at TIMESTAMPTZ NOT NULL DEFAULT now()
    );
    CREATE INDEX ON shopping_list_items (user_id, is_checked);
    """)

    # --- 6.5 Planes de dieta y registro diario -----------------------------
    op.get_bind().exec_driver_sql("""
    CREATE TABLE diet_plans (
      id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      user_id         UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
      name            TEXT NOT NULL,
      start_date      DATE NOT NULL,
      end_date        DATE,
      status          TEXT NOT NULL DEFAULT 'draft'
                      CHECK (status IN ('draft','active','archived')),
      target_kcal     NUMERIC(7,1) NOT NULL,
      target_protein_g NUMERIC(7,1) NOT NULL,
      target_fat_g    NUMERIC(7,1) NOT NULL,
      target_carbs_g  NUMERIC(7,1) NOT NULL,
      generated_by    TEXT NOT NULL DEFAULT 'manual'
                      CHECK (generated_by IN ('manual','engine','iafood')),
      created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
    );
    CREATE INDEX ON diet_plans (user_id, status);

    CREATE TABLE plan_days (
      id        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      plan_id   UUID NOT NULL REFERENCES diet_plans(id) ON DELETE CASCADE,
      day_index SMALLINT NOT NULL,
      UNIQUE (plan_id, day_index)
    );

    CREATE TABLE plan_meals (
      id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      plan_day_id UUID NOT NULL REFERENCES plan_days(id) ON DELETE CASCADE,
      meal_type   TEXT NOT NULL CHECK (meal_type IN
                  ('breakfast','morning_snack','lunch','afternoon_snack','dinner','supper')),
      sort_order  SMALLINT NOT NULL DEFAULT 0
    );

    CREATE TABLE plan_items (
      id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      plan_meal_id UUID NOT NULL REFERENCES plan_meals(id) ON DELETE CASCADE,
      food_id      UUID REFERENCES foods(id),
      recipe_id    UUID REFERENCES recipes(id),
      grams        NUMERIC(8,2) NOT NULL,
      is_substitutable BOOLEAN NOT NULL DEFAULT TRUE,
      CHECK ((food_id IS NULL) <> (recipe_id IS NULL))
    );

    CREATE TABLE plan_item_alternatives (
      id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      plan_item_id UUID NOT NULL REFERENCES plan_items(id) ON DELETE CASCADE,
      food_id      UUID NOT NULL REFERENCES foods(id),
      grams        NUMERIC(8,2) NOT NULL,
      rank         SMALLINT NOT NULL,
      distance     NUMERIC(8,4) NOT NULL
    );

    CREATE TABLE food_log (
      id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      user_id    UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
      logged_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
      log_date   DATE NOT NULL,
      meal_type  TEXT NOT NULL,
      food_id    UUID REFERENCES foods(id),
      recipe_id  UUID REFERENCES recipes(id),
      grams      NUMERIC(8,2) NOT NULL,
      entry_source TEXT NOT NULL DEFAULT 'manual'
                   CHECK (entry_source IN ('manual','scan','plan','recipe')),
      kcal       NUMERIC(9,2) NOT NULL,
      protein_g  NUMERIC(9,2) NOT NULL,
      fat_g      NUMERIC(9,2) NOT NULL,
      carbs_g    NUMERIC(9,2) NOT NULL,
      micros     JSONB NOT NULL DEFAULT '{}'::jsonb,
      CHECK ((food_id IS NULL) <> (recipe_id IS NULL))
    );
    CREATE INDEX ON food_log (user_id, log_date);
    """)

    # --- 6.6 Agua, suplementos, ayuno y notificaciones ---------------------
    op.get_bind().exec_driver_sql("""
    CREATE TABLE water_settings (
      user_id          UUID PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
      mode             TEXT NOT NULL DEFAULT 'auto' CHECK (mode IN ('auto','manual')),
      daily_target_ml  INT NOT NULL DEFAULT 2500,
      containers       JSONB NOT NULL DEFAULT '[{"label": "Vaso", "ml": 200}, {"label": "Botella", "ml": 500}]'::jsonb
    );

    CREATE TABLE water_log (
      id        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      user_id   UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
      logged_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      log_date  DATE NOT NULL,
      ml        INT NOT NULL CHECK (ml > 0)
    );
    CREATE INDEX ON water_log (user_id, log_date);

    CREATE TABLE supplements (
      id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      user_id             UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
      name                TEXT NOT NULL,
      type                TEXT NOT NULL,
      dose_amount         NUMERIC(8,2) NOT NULL,
      dose_unit           TEXT NOT NULL,
      doses_per_container INT,
      price_per_container NUMERIC(10,2),
      image_path          TEXT,
      notes               TEXT,
      is_active           BOOLEAN NOT NULL DEFAULT TRUE,
      food_id             UUID REFERENCES foods(id),
      created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
    );
    CREATE INDEX ON supplements (user_id, is_active);

    CREATE TABLE supplement_schedules (
      id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      supplement_id UUID NOT NULL REFERENCES supplements(id) ON DELETE CASCADE,
      time_of_day   TIME NOT NULL,
      days_of_week  SMALLINT[] NOT NULL DEFAULT '{1,2,3,4,5,6,7}',
      with_food     BOOLEAN NOT NULL DEFAULT FALSE
    );

    CREATE TABLE supplement_log (
      id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      user_id       UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
      supplement_id UUID NOT NULL REFERENCES supplements(id) ON DELETE CASCADE,
      taken_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
      log_date      DATE NOT NULL,
      skipped       BOOLEAN NOT NULL DEFAULT FALSE
    );
    CREATE INDEX ON supplement_log (user_id, log_date);

    CREATE TABLE supplement_stock (
      supplement_id    UUID PRIMARY KEY REFERENCES supplements(id) ON DELETE CASCADE,
      doses_remaining  NUMERIC(8,2) NOT NULL DEFAULT 0,
      last_restock_at  TIMESTAMPTZ
    );

    CREATE TABLE fasting_windows (
      id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      user_id      UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
      started_at   TIMESTAMPTZ NOT NULL,
      ended_at     TIMESTAMPTZ,
      target_hours NUMERIC(4,1) NOT NULL DEFAULT 16
    );
    CREATE INDEX ON fasting_windows (user_id, started_at DESC);

    CREATE TABLE push_subscriptions (
      id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      user_id    UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
      endpoint   TEXT NOT NULL UNIQUE,
      p256dh     TEXT NOT NULL,
      auth       TEXT NOT NULL,
      device     TEXT,
      created_at TIMESTAMPTZ NOT NULL DEFAULT now()
    );

    CREATE TABLE notification_rules (
      id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      user_id       UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
      kind          TEXT NOT NULL CHECK (kind IN ('water','supplement','meal','weigh_in')),
      is_enabled    BOOLEAN NOT NULL DEFAULT TRUE,
      schedule      JSONB NOT NULL,
      quiet_from    TIME NOT NULL DEFAULT '23:00',
      quiet_to      TIME NOT NULL DEFAULT '08:00'
    );
    CREATE INDEX ON notification_rules (user_id, kind);
    """)

    # --- 6.7 iafood, TDEE adaptativo y auditoría ---------------------------
    op.get_bind().exec_driver_sql("""
    CREATE TABLE ai_credentials (
      id             SMALLINT PRIMARY KEY DEFAULT 1 CHECK (id = 1),
      provider       TEXT NOT NULL DEFAULT 'anthropic',
      token_encrypted BYTEA NOT NULL,
      updated_by     UUID REFERENCES users(id),
      updated_at     TIMESTAMPTZ NOT NULL DEFAULT now()
    );

    CREATE TABLE ai_sessions (
      id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      user_id      UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
      kind         TEXT NOT NULL CHECK (kind IN ('diet_plan','plan_review','supplement_suggestion','chat_edit')),
      status       TEXT NOT NULL CHECK (status IN ('running','succeeded','failed','rejected_validation')),
      request_payload  JSONB NOT NULL,
      response_payload JSONB,
      validation_errors JSONB,
      attempts     SMALLINT NOT NULL DEFAULT 1,
      input_tokens INT,
      output_tokens INT,
      created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
    );
    CREATE INDEX ON ai_sessions (user_id, created_at DESC);

    CREATE TABLE ai_proposals (
      id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      ai_session_id UUID NOT NULL REFERENCES ai_sessions(id) ON DELETE CASCADE,
      user_id       UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
      scope         TEXT NOT NULL,
      payload       JSONB NOT NULL,
      rationale     TEXT,
      status        TEXT NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending','approved','rejected','expired')),
      decided_at    TIMESTAMPTZ
    );
    CREATE INDEX ON ai_proposals (user_id, status);

    CREATE TABLE tdee_estimates (
      id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      user_id           UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
      week_start        DATE NOT NULL,
      weight_trend_kg   NUMERIC(6,3) NOT NULL,
      weight_change_kg  NUMERIC(6,3) NOT NULL,
      avg_intake_kcal   NUMERIC(8,2) NOT NULL,
      estimated_tdee    NUMERIC(8,2) NOT NULL,
      logging_days      SMALLINT NOT NULL,
      is_reliable       BOOLEAN NOT NULL,
      UNIQUE (user_id, week_start)
    );

    CREATE TABLE audit_log (
      id         BIGSERIAL PRIMARY KEY,
      user_id    UUID REFERENCES users(id) ON DELETE SET NULL,
      action     TEXT NOT NULL,
      entity     TEXT,
      entity_id  UUID,
      metadata   JSONB,
      created_at TIMESTAMPTZ NOT NULL DEFAULT now()
    );
    """)

    # --- 6.8 Favoritos y quick-add ------------------------------------------
    op.get_bind().exec_driver_sql("""
    CREATE TABLE user_favorite_foods (
      id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      user_id    UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
      food_id    UUID REFERENCES foods(id) ON DELETE CASCADE,
      recipe_id  UUID REFERENCES recipes(id) ON DELETE CASCADE,
      use_count    INT NOT NULL DEFAULT 0,
      last_used_at TIMESTAMPTZ,
      created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
      CHECK ((food_id IS NULL) <> (recipe_id IS NULL)),
      UNIQUE (user_id, food_id, recipe_id)
    );
    CREATE INDEX ON user_favorite_foods (user_id, use_count DESC);
    """)

    # --- 6.10 Chat conversacional --------------------------------------------
    op.get_bind().exec_driver_sql("""
    CREATE TABLE chat_messages (
      id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      user_id       UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
      role          TEXT NOT NULL CHECK (role IN ('user','assistant')),
      content       TEXT NOT NULL,
      source        TEXT NOT NULL DEFAULT 'text' CHECK (source IN ('text','voice')),
      ai_session_id UUID REFERENCES ai_sessions(id) ON DELETE SET NULL,
      created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
    );
    CREATE INDEX ON chat_messages (user_id, created_at);
    """)

    # --- Permisos de los roles de conexión ----------------------------------
    op.get_bind().exec_driver_sql("""
    GRANT USAGE ON SCHEMA public TO myfood_app, myfood_admin;
    GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO myfood_app, myfood_admin;
    GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO myfood_app, myfood_admin;
    ALTER DEFAULT PRIVILEGES IN SCHEMA public
      GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO myfood_app, myfood_admin;
    ALTER DEFAULT PRIVILEGES IN SCHEMA public
      GRANT USAGE, SELECT ON SEQUENCES TO myfood_app, myfood_admin;
    """)


def downgrade() -> None:
    op.get_bind().exec_driver_sql("""
    DROP TABLE IF EXISTS
      chat_messages, user_favorite_foods, audit_log, tdee_estimates, ai_proposals,
      ai_sessions, ai_credentials, notification_rules, push_subscriptions,
      fasting_windows, supplement_stock, supplement_log, supplement_schedules,
      supplements, water_log, water_settings, food_log, plan_item_alternatives,
      plan_items, plan_meals, plan_days, diet_plans, shopping_list_items,
      pantry_items, recipe_ingredients, recipes, food_allergens, food_images,
      food_vectors, food_nutrients, foods, body_measurements, user_restrictions,
      allergens, profiles, consents, users
    CASCADE;
    """)
    op.get_bind().exec_driver_sql("""
    DO $$
    BEGIN
      IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'myfood_app') THEN
        DROP OWNED BY myfood_app;
        DROP ROLE myfood_app;
      END IF;
      IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'myfood_admin') THEN
        DROP OWNED BY myfood_admin;
        DROP ROLE myfood_admin;
      END IF;
    END $$;
    """)
