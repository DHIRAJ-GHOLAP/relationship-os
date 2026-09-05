"""Centralized, typed application configuration for Relationship OS."""

import os
from typing import List, Optional
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

    # Runtime Environment
    ENVIRONMENT: str = "development"
    DEBUG: bool = False
    APP_NAME: str = "Relationship OS"
    APP_VERSION: str = "1.0.0"
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    ALLOWED_ORIGINS: str = "http://localhost:3000,http://127.0.0.1:3000,http://localhost:8000,http://127.0.0.1:8000"

    # Security & Authentication
    SESSION_SECRET: str = "INSECURE_DEV_SECRET_REPLACE_FOR_PRODUCTION_0123456789"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    ENROLLMENT_TOKEN_EXPIRE_HOURS: int = 24
    COOKIE_SECURE: bool = False
    COOKIE_SAMESITE: str = "lax"

    # Database & Cache
    DATABASE_URL: str = "sqlite+aiosqlite:///./relationship_os.db"
    DATABASE_ECHO: bool = False
    REDIS_URL: Optional[str] = None

    # Integrations: Discord
    DISCORD_ENABLED: bool = False
    DISCORD_BOT_TOKEN: Optional[str] = None
    DISCORD_CHANNEL_ID: Optional[str] = None
    DISCORD_GUILD_ID: Optional[str] = None
    DISCORD_OWNER_USER_ID: Optional[str] = None
    DISCORD_WEBHOOK_URL: Optional[str] = None

    # Integrations: Webhook
    WEBHOOK_ENABLED: bool = False
    WEBHOOK_SIGNING_SECRET: str = "DEV_WEBHOOK_SIGNING_SECRET_REPLACE_ME_1234"
    WEBHOOK_MAX_RETRIES: int = 5
    WEBHOOK_TIMEOUT_SECONDS: int = 10
    WEBHOOK_ALLOW_LOCALHOST: bool = False

    # Integrations: Signal
    SIGNAL_ENABLED: bool = False
    SIGNAL_BRIDGE_URL: Optional[str] = None
    SIGNAL_BRIDGE_TOKEN: Optional[str] = None
    SIGNAL_RECIPIENT_NUMBER: Optional[str] = None

    # Abuse & Rate Limiting
    RATE_LIMIT_LOGIN_PER_MINUTE: int = 5
    RATE_LIMIT_MESSAGES_PER_MINUTE: int = 60
    MAX_MESSAGE_LENGTH: int = 4000
    MAX_ATTACHMENT_SIZE_BYTES: int = 10 * 1024 * 1024  # 10 MB

    # Storage Foundation
    STORAGE_LOCAL_DIR: str = "./storage_uploads"

    # Branding
    ROOM_NAME: str = "Private Room ♥"
    OWNER_DISPLAY_NAME: str = "Owner"
    RECIPIENT_DISPLAY_NAME: str = "Recipient"
    WELCOME_MESSAGE: str = "Welcome to our private room."
    THEME_ACCENT: str = "#e11d48"

    @property
    def cors_origins(self) -> List[str]:
        return [origin.strip() for origin in self.ALLOWED_ORIGINS.split(",") if origin.strip()]

    @field_validator("SESSION_SECRET")
    @classmethod
    def validate_session_secret(cls, v: str) -> str:
        env = os.getenv("ENVIRONMENT", "development")
        if env == "production":
            if len(v) < 32 or "INSECURE" in v or "CHANGE_ME" in v:
                raise ValueError("SESSION_SECRET must be at least 32 high-entropy characters in production.")
        return v


settings = Settings()
