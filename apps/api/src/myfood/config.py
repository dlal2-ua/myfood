from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "development"
    app_url: str = "http://localhost:8092"
    tz: str = "Europe/Madrid"

    secret_key: str = "dev-secret-key-change-me"
    encryption_key: str = "0" * 64  # 32 bytes hex — DEBE sobreescribirse en producción
    session_ttl_days: int = 30

    postgres_host: str = "postgres"
    postgres_port: int = 5432
    postgres_db: str = "myfood"
    postgres_user: str = "myfood"
    postgres_password: str = ""
    postgres_app_role: str = "myfood_app"
    postgres_app_password: str = ""
    postgres_admin_role: str = "myfood_admin"
    postgres_admin_password: str = ""

    redis_url: str = "redis://redis:6379/0"

    meili_url: str = "http://meilisearch:7700"
    meili_master_key: str = ""

    usda_api_key: str = ""
    off_user_agent: str = "MyFood/1.0 (dev@example.com)"

    image_storage_path: str = "/data/images"
    image_cache_budget_gb: int = 20

    vapid_public_key: str = ""
    vapid_private_key: str = ""
    vapid_subject: str = "mailto:dev@example.com"

    iafood_enabled: bool = True
    iafood_model: str = "claude-sonnet-4-6"
    # Límites de uso (10.1/24.5) — fichero mutable vía /admin/ai/limits,
    # mismo patrón que `coach.json` en openGym. No es la credencial (esa
    # vive cifrada en `ai_credentials`, nunca en disco).
    iafood_config_path: str = "/data/config/iafood.json"

    whisper_base_url: str = "http://whisper:9000"
    whisper_model: str = "medium"

    @property
    def database_url_superuser(self) -> str:
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def database_url_superuser_sync(self) -> str:
        """Usada solo por Alembic: psycopg2 acepta múltiples sentencias SQL en
        una sola llamada (protocolo simple), a diferencia de asyncpg, que las
        rechaza al usar siempre sentencias preparadas."""
        return (
            f"postgresql+psycopg2://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def database_url(self) -> str:
        """URL de conexión con el rol de aplicación (sujeto a RLS, ver sección 22)."""
        return (
            f"postgresql+asyncpg://{self.postgres_app_role}:{self.postgres_app_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
