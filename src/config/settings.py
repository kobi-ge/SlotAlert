from functools import lru_cache
from typing import List, Literal, Optional
from pydantic import SecretStr, model_validator
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

    # Meta WhatsApp Cloud API Provider Configuration
    WHATSAPP_PROVIDER: Literal["mock", "meta"] = "mock"

    # Meta Cloud API Credentials
    WHATSAPP_ACCESS_TOKEN: Optional[SecretStr] = None
    WHATSAPP_API_TOKEN: Optional[str] = None  # Legacy fallback alias
    WHATSAPP_PHONE_NUMBER_ID: Optional[str] = None
    WHATSAPP_BUSINESS_ACCOUNT_ID: Optional[str] = None
    WHATSAPP_VERIFY_TOKEN: str = "slotalert-webhook-verify-token"
    WHATSAPP_APP_SECRET: Optional[SecretStr] = None
    WHATSAPP_API_VERSION: str = "v20.0"

    # Template Defaults & Network Resilience
    WHATSAPP_SLOT_TEMPLATE_NAME: str = "slot_cancellation_alert_v1"
    WHATSAPP_SLOT_TEMPLATE_LANG: str = "he"
    WHATSAPP_MAX_RETRIES: int = 3
    WHATSAPP_RETRY_BACKOFF_FACTOR: float = 0.5

    BASE_WEB_URL: str = "http://localhost:8000"

    # Business Auth & Security
    JWT_SECRET: str = "slotalert-jwt-secret-key-change-in-production"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_DAYS: int = 30
    MASTER_ADMIN_KEY: str = "master-secret-key"

    @property
    def whatsapp_access_token_value(self) -> Optional[str]:
        """Return raw string value of WhatsApp access token, checking secret and legacy token."""
        if self.WHATSAPP_ACCESS_TOKEN:
            return self.WHATSAPP_ACCESS_TOKEN.get_secret_value()
        return self.WHATSAPP_API_TOKEN

    @property
    def whatsapp_app_secret_value(self) -> Optional[str]:
        """Return raw string value of WhatsApp app secret."""
        if self.WHATSAPP_APP_SECRET:
            return self.WHATSAPP_APP_SECRET.get_secret_value()
        return None

    @model_validator(mode="after")
    def validate_meta_provider_settings(self) -> "Settings":
        """Ensure required credentials exist when WHATSAPP_PROVIDER is 'meta'."""
        if self.WHATSAPP_PROVIDER == "meta":
            token = self.WHATSAPP_ACCESS_TOKEN or self.WHATSAPP_API_TOKEN
            if not token:
                raise ValueError("WHATSAPP_ACCESS_TOKEN (or WHATSAPP_API_TOKEN) is required when WHATSAPP_PROVIDER='meta'")
            if not self.WHATSAPP_PHONE_NUMBER_ID:
                raise ValueError("WHATSAPP_PHONE_NUMBER_ID is required when WHATSAPP_PROVIDER='meta'")
            if not self.WHATSAPP_APP_SECRET:
                raise ValueError("WHATSAPP_APP_SECRET is required when WHATSAPP_PROVIDER='meta'")
        return self

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
