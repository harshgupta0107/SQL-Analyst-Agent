"""Application configuration loaded from the project .env file."""

from functools import lru_cache
from pathlib import Path
from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parent


class Settings(BaseSettings):
    """Validated settings; credentials are masked by Pydantic."""

    groq_api_key: SecretStr = Field(validation_alias="GROQ_API_KEY")
    groq_model: str = Field(validation_alias="GROQ_MODEL")
    gemini_api_key: SecretStr = Field(validation_alias="GEMINI_API_KEY")
    gemini_model: str = Field(validation_alias="GEMINI_MODEL")
    max_rows_returned: int = Field(
        default=1000, ge=1, le=100000, validation_alias="MAX_ROWS_RETURNED"
    )
    query_timeout_seconds: int = Field(
        default=30, ge=1, le=600, validation_alias="QUERY_TIMEOUT_SECONDS"
    )
    llm_timeout_seconds: int = Field(
        default=30, ge=1, le=600, validation_alias="LLM_TIMEOUT_SECONDS"
    )
    max_upload_mb: int = Field(
        default=200, ge=1, le=5000, validation_alias="MAX_UPLOAD_MB"
    )
    log_level: str = Field(default="INFO", validation_alias="LOG_LEVEL")

    model_config = SettingsConfigDict(
        env_file=ROOT / ".env", env_file_encoding="utf-8", extra="ignore"
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return cached settings or raise a value-free missing-variable error."""
    try:
        return Settings()
    except Exception as exc:
        text = str(exc)
        missing = [
            name
            for name in ("GROQ_API_KEY", "GROQ_MODEL", "GEMINI_API_KEY", "GEMINI_MODEL")
            if name in text
        ]
        if missing:
            raise RuntimeError(
                "Missing required configuration variable(s): "
                + ", ".join(missing)
                + ". Add them to .env."
            ) from None
        raise RuntimeError(
            "Invalid application configuration. Check the setting names and numeric limits in .env."
        ) from None
