from functools import lru_cache
from typing import List
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # Project metadata
    PROJECT_NAME: str = "SlotAlert"
    API_V1_STR: str = "/api/v1"
    APP_ENV: str = "development"
    SECRET_KEY: str = "change-me"

    # Database & Cache URLs
    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/slotalert"
    REDIS_URL: str = "redis://localhost:6337/0"

    # CORS
    ALLOWED_ORIGINS: List[str] = ["*"]

    # Meta WhatsApp Cloud API
    WHATSAPP_API_TOKEN: str | None = None
    WHATSAPP_PHONE_NUMBER_ID: str | None = None
    WHATSAPP_VERIFY_TOKEN: str = "slotalert-webhook-verify-token"
    WHATSAPP_APP_SECRET: str | None = None
    WHATSAPP_API_VERSION: str = "v20.0"
    BASE_WEB_URL: str = "http://localhost:8000"

    # Business Auth & Security
    JWT_SECRET: str = "slotalert-jwt-secret-key-change-in-production"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_DAYS: int = 30
    MASTER_ADMIN_KEY: str = "master-secret-key"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )


@lru_cache()
def get_settings() -> Settings:
    """Return cached instance of Settings."""
    return Settings()
