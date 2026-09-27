"""Application settings, loaded from the environment."""

from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration. Missing required values raise at startup."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    telegram_bot_token: str = Field(min_length=1)
    groq_api_key: str = Field(min_length=1)
    groq_model: str = Field(default="llama-3.3-70b-versatile", min_length=1)
    database_url: str = Field(min_length=1)
    # Signs the dashboard magic links, so a guessable value is a real hole.
    app_secret: str = Field(min_length=32)
    public_base_url: str = Field(default="http://localhost:8000")
    log_level: str = Field(default="INFO")

    @field_validator("public_base_url")
    @classmethod
    def _strip_trailing_slash(cls, v: str) -> str:
        return v.rstrip("/")

    @field_validator("log_level")
    @classmethod
    def _upper(cls, v: str) -> str:
        return v.upper()

    @field_validator("database_url")
    @classmethod
    def _require_async_driver(cls, v: str) -> str:
        # Railway hands out `postgresql://` URLs; asyncpg needs the explicit driver.
        if v.startswith("postgresql://"):
            return v.replace("postgresql://", "postgresql+asyncpg://", 1)
        if v.startswith("postgres://"):
            return v.replace("postgres://", "postgresql+asyncpg://", 1)
        return v


@lru_cache
def get_settings() -> Settings:
    return Settings()
