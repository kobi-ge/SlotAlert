from functools import lru_cache
from typing import Any, List, Literal, Optional
from pydantic import AliasChoices, Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # Project metadata
    PROJECT_NAME: str = "SlotAlert"
    API_V1_STR: str = "/api/v1"
    APP_ENV: str = Field(default="development", validation_alias=AliasChoices("APP_ENV", "ENVIRONMENT"))
    SECRET_KEY: str = "change-me"

    # Database & Cache URLs
    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/slotalert"
    REDIS_URL: str = "redis://localhost:6337/0"

    # CORS
    ALLOWED_ORIGINS: List[str] = ["*"]

    # Meta WhatsApp Cloud API Provider Configuration ('mock', 'meta', or None for auto)
    WHATSAPP_PROVIDER: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("WHATSAPP_PROVIDER", "MESSAGING_PROVIDER"),
    )

    # Meta Cloud API Credentials
    WHATSAPP_ACCESS_TOKEN: Optional[SecretStr] = None
    WHATSAPP_API_TOKEN: Optional[str] = None  # Legacy fallback alias
    WHATSAPP_PHONE_NUMBER_ID: Optional[str] = None
    WHATSAPP_BUSINESS_ACCOUNT_ID: Optional[str] = None
    WHATSAPP_VERIFY_TOKEN: str = "slotalert-webhook-verify-token"
    WHATSAPP_APP_SECRET: Optional[SecretStr] = None
    WHATSAPP_API_VERSION: str = "v20.0"

    # Template Defaults & Network Resilience
    WHATSAPP_SLOT_TEMPLATE_NAME: str = "slot_cancellation_alert_v2"
    WHATSAPP_SLOT_TEMPLATE_LANG: str = "he"
    WHATSAPP_MAX_RETRIES: int = 3
    WHATSAPP_RETRY_BACKOFF_FACTOR: float = 0.5

    BASE_WEB_URL: str = Field(
        default="http://localhost:8000",
        validation_alias=AliasChoices("BASE_WEB_URL", "BASE_URL", "PUBLIC_URL", "APP_URL"),
    )

    # Business Auth & Security
    JWT_SECRET: str = "slotalert-jwt-secret-key-change-in-production"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_DAYS: int = 30
    MASTER_ADMIN_KEY: str = "master-secret-key"

    @property
    def is_production(self) -> bool:
        """Check if running in production mode."""
        return self.APP_ENV.lower() in ("production", "prod")

    @property
    def effective_whatsapp_provider(self) -> str:
        """
        Resolve the active messaging provider ('mock' or 'meta').
        1. If WHATSAPP_PROVIDER is explicitly set to 'meta' or 'mock', honor it.
        2. If WHATSAPP_PROVIDER is not set:
           - In production with Meta credentials present -> automatically resolves to 'meta'.
           - If Meta credentials are provided -> automatically resolves to 'meta'.
           - Otherwise -> safely defaults to 'mock' for local development & CI tests.
        """
        if self.WHATSAPP_PROVIDER:
            prov = self.WHATSAPP_PROVIDER.strip().lower()
            if prov in ("meta", "mock"):
                return prov

        # Auto-detection: use 'meta' if credentials exist
        if self.whatsapp_access_token_value and self.whatsapp_phone_number_id_value:
            return "meta"
        return "mock"

    @property
    def whatsapp_access_token_value(self) -> Optional[str]:
        """Return raw string value of WhatsApp access token, stripped of whitespace and quotes."""
        val = None
        if self.WHATSAPP_ACCESS_TOKEN:
            val = self.WHATSAPP_ACCESS_TOKEN.get_secret_value()
        elif self.WHATSAPP_API_TOKEN:
            val = self.WHATSAPP_API_TOKEN

        if val:
            clean = val.strip().strip('"').strip("'")
            return clean or None
        return None

    @property
    def whatsapp_phone_number_id_value(self) -> Optional[str]:
        """Return stripped string value of WhatsApp phone number ID."""
        if self.WHATSAPP_PHONE_NUMBER_ID:
            clean = str(self.WHATSAPP_PHONE_NUMBER_ID).strip().strip('"').strip("'")
            return clean or None
        return None

    @property
    def whatsapp_app_secret_value(self) -> Optional[str]:
        """Return raw string value of WhatsApp app secret, stripped of whitespace and quotes."""
        if self.WHATSAPP_APP_SECRET:
            clean = self.WHATSAPP_APP_SECRET.get_secret_value().strip().strip('"').strip("'")
            return clean or None
        return None

    @field_validator("DATABASE_URL", mode="before")
    @classmethod
    def normalize_database_url(cls, v: Any) -> Any:
        """Ensure DATABASE_URL uses asyncpg scheme even if standard postgresql:// is passed."""
        if isinstance(v, str):
            v = v.strip().strip('"').strip("'")
            if v.startswith("postgres://"):
                return v.replace("postgres://", "postgresql+asyncpg://", 1)
            elif v.startswith("postgresql://") and not v.startswith("postgresql+"):
                return v.replace("postgresql://", "postgresql+asyncpg://", 1)
        return v

    @model_validator(mode="after")
    def validate_meta_provider_settings(self) -> "Settings":
        """Ensure required credentials exist when effective provider is 'meta'."""
        if self.effective_whatsapp_provider == "meta":
            if not self.whatsapp_access_token_value:
                raise ValueError("WHATSAPP_ACCESS_TOKEN (or WHATSAPP_API_TOKEN) is required when using Meta WhatsApp provider")
            if not self.whatsapp_phone_number_id_value:
                raise ValueError("WHATSAPP_PHONE_NUMBER_ID is required when using Meta WhatsApp provider")
            if not self.whatsapp_app_secret_value and self.is_production:
                raise ValueError("WHATSAPP_APP_SECRET is required in production when using Meta WhatsApp provider")
        return self

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )


@lru_cache()
def get_settings() -> Settings:
    """Return cached instance of Settings."""
    return Settings()
