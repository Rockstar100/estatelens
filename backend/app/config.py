"""Application configuration, loaded once from the environment.

All secrets live only in the environment (local ``.env`` or the host dashboard);
nothing here is baked into a Docker layer or logged.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- OpenRouter -------------------------------------------------------
    openrouter_api_key: str = Field(default="", alias="OPENROUTER_API_KEY")
    openrouter_model: str = Field(
        default="nex-agi/nex-n2.5-mini:free", alias="OPENROUTER_MODEL"
    )
    openrouter_fallback_model: str = Field(
        default="nvidia/nemotron-3-super-120b-a12b:free", alias="OPENROUTER_FALLBACK_MODEL"
    )
    openrouter_base_url: str = Field(
        default="https://openrouter.ai/api/v1", alias="OPENROUTER_BASE_URL"
    )
    openrouter_timeout_seconds: float = Field(default=45.0, alias="OPENROUTER_TIMEOUT_SECONDS")
    openrouter_max_output_tokens: int = Field(default=900, alias="OPENROUTER_MAX_OUTPUT_TOKENS")

    # --- MongoDB -------------------------------------------------------
    mongodb_uri: str = Field(default="mongodb://localhost:27017", alias="MONGODB_URI")
    mongodb_database: str = Field(default="estatelens", alias="MONGODB_DATABASE")
    mongodb_timeout_ms: int = Field(default=8000, alias="MONGODB_TIMEOUT_MS")
    mongodb_max_pool_size: int = Field(default=20, alias="MONGODB_MAX_POOL_SIZE")

    # --- App -------------------------------------------------------
    app_base_url: str = Field(default="http://localhost:8000", alias="APP_BASE_URL")
    port: int = Field(default=8000, alias="PORT")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    # --- Chat / retrieval limits -------------------------------------
    max_message_chars: int = Field(default=4000, alias="MAX_MESSAGE_CHARS")
    max_history_messages: int = Field(default=12, alias="MAX_HISTORY_MESSAGES")
    retrieval_passage_limit: int = Field(default=6, alias="RETRIEVAL_PASSAGE_LIMIT")
    properties_page_size_max: int = Field(default=48, alias="PROPERTIES_PAGE_SIZE_MAX")

    # --- Rate limiting (in-memory, single instance) -----------------
    rate_limit_chat_per_minute: int = Field(default=12, alias="RATE_LIMIT_CHAT_PER_MINUTE")
    rate_limit_api_per_minute: int = Field(default=120, alias="RATE_LIMIT_API_PER_MINUTE")

    # --- Scraper (ingestion CLI only) ------------------------------
    scraper_user_agent: str = Field(
        default="EstateLensBot/0.1 (+https://github.com/your-org/estatelens; research demo)",
        alias="SCRAPER_USER_AGENT",
    )
    scraper_max_concurrency: int = Field(default=2, alias="SCRAPER_MAX_CONCURRENCY")
    scraper_delay_seconds: float = Field(default=2.0, alias="SCRAPER_DELAY_SECONDS")

    @property
    def cors_origins(self) -> list[str]:
        origins = {self.app_base_url, "http://localhost:5173", "http://localhost:8000"}
        return [o for o in origins if o]

    @property
    def openrouter_configured(self) -> bool:
        return bool(self.openrouter_api_key)


@lru_cache
def get_settings() -> Settings:
    return Settings()
