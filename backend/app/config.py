from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="VANTIX_", env_file=".env", extra="ignore")

    environment: str = "development"
    database_url: str = "postgresql+psycopg://vantix:vantix@localhost:5435/vantix"
    repository_backend: str = "postgres"
    oidc_issuer: str = ""
    oidc_audience: str = "vantix-api"
    oidc_jwks_url: str = ""
    allow_development_auth: bool = True


@lru_cache
def get_settings() -> Settings:
    return Settings()
