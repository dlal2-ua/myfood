from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool

from alembic import context
from myfood.config import get_settings
from myfood.db.base import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

settings = get_settings()
# Migraciones síncronas (psycopg2): necesita crear roles/extensiones/RLS y
# ejecutar bloques DDL con varias sentencias por llamada, algo que asyncpg
# no permite (ver database_url_superuser_sync). El runtime de la app sigue
# usando asyncpg en myfood.db.session.
config.set_main_option("sqlalchemy.url", settings.database_url_superuser_sync)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()
    connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
