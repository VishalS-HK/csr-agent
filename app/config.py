from functools import lru_cache
from urllib.parse import urlparse

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

TRANSACTION_POOLER_PORT = 6543


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Database
    database_url: SecretStr
    db_pool_min_size: int = Field(default=1, ge=0)
    db_pool_max_size: int = Field(default=10, ge=1)
    db_pool_timeout_seconds: float = Field(default=5.0, gt=0)

    # Supabase Auth
    supabase_url: str  # https://<project-ref>.supabase.co
    # Admin key; only scripts/link_auth_users.py uses it, never the app.
    supabase_service_role_key: SecretStr = SecretStr("")

    # OpenAI (week 2)
    openai_api_key: SecretStr = SecretStr("")
    openai_model: str = "gpt-6-luna"
    openai_embedding_model: str = "text-embedding-3-small"

    @field_validator("database_url")
    @classmethod
    def reject_transaction_pooler(cls, value: SecretStr) -> SecretStr:
        if urlparse(value.get_secret_value()).port == TRANSACTION_POOLER_PORT:
            raise ValueError(
                "DATABASE_URL points at the Supabase transaction pooler (port 6543). "
                "Use a session-mode connection on port 5432 instead."
            )
        return value

    @field_validator("supabase_url")
    @classmethod
    def normalize_supabase_url(cls, value: str) -> str:
        value = value.strip().rstrip("/")
        if not value.startswith("https://"):
            raise ValueError("SUPABASE_URL must be the https://<project-ref>.supabase.co URL")
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
