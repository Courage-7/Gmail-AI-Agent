"""Application settings."""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "email-assistant-app"
    environment: str = "local"
    log_level: str = "INFO"
    request_id_header: str = "x-request-id"

    groq_api_key: str | None = None
    groq_model: str = "openai/gpt-oss-120b"
    groq_base_url: str = "https://api.groq.com/openai/v1"

    supabase_url: str | None = None
    supabase_service_role_key: str | None = None
    supabase_anon_key: str | None = None
    default_user_id: str = "local-user"

    email_address: str | None = None
    email_password: str | None = None
    imap_host: str = "imap.gmail.com"
    imap_port: int = Field(default=993, gt=0)
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = Field(default=587, gt=0)
    gmail_mcp_image: str = "yashtekwani/gmail-mcp"
    test_send_to: str | None = None

    @field_validator(
        "groq_api_key",
        "supabase_url",
        "supabase_service_role_key",
        "supabase_anon_key",
        "email_address",
        "email_password",
        "test_send_to",
        mode="before",
    )
    @classmethod
    def blank_string_as_none(cls, value: str | None) -> str | None:
        """Treat blank optional string environment values as unset."""
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @property
    def llm_provider(self) -> str:
        """Return the only supported LLM provider."""
        return "groq"

    @property
    def llm_model(self) -> str:
        """Return the configured model for the active LLM provider."""
        return self.groq_model

    @property
    def llm_configured(self) -> bool:
        """Return whether the active LLM provider has its required credentials."""
        return bool(self.groq_api_key and self.groq_base_url and self.groq_model)


@lru_cache
def get_settings() -> Settings:
    """Return cached settings for dependency injection."""
    return Settings()
