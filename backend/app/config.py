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
        populate_by_name=True,
    )

    # --- LLM providers (Groq / Gemini / OpenRouter) -----------------------
    # auto = try Groq → Gemini → OpenRouter for whichever keys are set.
    llm_provider: str = Field(default="auto", alias="LLM_PROVIDER")

    openrouter_api_key: str = Field(default="", alias="OPENROUTER_API_KEY")
    # nvidia/nemotron-3-super-120b-a12b:free is the most instruction-reliable free
    # route currently on OpenRouter — the previous primary (nex-n2.5-mini) emitted
    # degenerate output (unrelated CJK text, "Part 2" hallucinations) on ~1 turn
    # in 4; nemotron-3.5-lightning always leaks a "thinking process" preamble.
    openrouter_model: str = Field(
        default="nvidia/nemotron-3-super-120b-a12b:free", alias="OPENROUTER_MODEL"
    )
    openrouter_fallback_model: str = Field(
        default="nex-agi/nex-n2.5-mini:free", alias="OPENROUTER_FALLBACK_MODEL"
    )
    openrouter_base_url: str = Field(
        default="https://openrouter.ai/api/v1", alias="OPENROUTER_BASE_URL"
    )
    openrouter_timeout_seconds: float = Field(default=45.0, alias="OPENROUTER_TIMEOUT_SECONDS")
    openrouter_max_output_tokens: int = Field(default=1200, alias="OPENROUTER_MAX_OUTPUT_TOKENS")

    groq_api_key: str = Field(default="", alias="GROQ_API_KEY")
    # Prefer a fast instruction-following free model; 120b often burns the
    # token budget on hidden reasoning and returns an empty visible answer.
    groq_model: str = Field(default="openai/gpt-oss-20b", alias="GROQ_MODEL")
    groq_base_url: str = Field(default="https://api.groq.com/openai/v1", alias="GROQ_BASE_URL")

    gemini_api_key: str = Field(default="", alias="GEMINI_API_KEY")
    # Google retired 2.0/2.5 flash for new keys; 3.6-flash is the current free default.
    gemini_model: str = Field(default="gemini-3.6-flash", alias="GEMINI_MODEL")
    # Google's OpenAI-compatible endpoint (Bearer key, /chat/completions stream).
    gemini_base_url: str = Field(
        default="https://generativelanguage.googleapis.com/v1beta/openai",
        alias="GEMINI_BASE_URL",
    )

    # --- Semantic retrieval (optional hybrid layer) -----------------------
    # Uses Google's embeddings API (same GEMINI_API_KEY). Vectors are stored on
    # each passage in MongoDB; the cosine search runs in-process over the small
    # corpus. If the key is absent or SEMANTIC_RETRIEVAL is false, retrieval is
    # pure lexical (structured filters + text index) exactly as before.
    semantic_retrieval: bool = Field(default=True, alias="SEMANTIC_RETRIEVAL")
    embedding_model: str = Field(default="gemini-embedding-001", alias="EMBEDDING_MODEL")
    embedding_dimensions: int = Field(default=768, alias="EMBEDDING_DIMENSIONS")
    embedding_base_url: str = Field(
        default="https://generativelanguage.googleapis.com/v1beta",
        alias="EMBEDDING_BASE_URL",
    )
    # Blend weight for the semantic score vs the lexical score (0..1).
    embedding_weight: float = Field(default=0.55, alias="EMBEDDING_WEIGHT")

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
    rate_limit_chat_per_minute: int = Field(default=30, alias="RATE_LIMIT_CHAT_PER_MINUTE")
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

    @property
    def llm_configured(self) -> bool:
        return bool(self.groq_api_key or self.gemini_api_key or self.openrouter_api_key)

    @property
    def embeddings_configured(self) -> bool:
        return bool(self.semantic_retrieval and self.gemini_api_key)

    @property
    def active_llm_label(self) -> str:
        pref = (self.llm_provider or "auto").strip().lower()
        if pref == "groq" and self.groq_api_key:
            return f"groq/{self.groq_model}"
        if pref == "gemini" and self.gemini_api_key:
            return f"gemini/{self.gemini_model}"
        if pref == "openrouter" and self.openrouter_api_key:
            return self.openrouter_model
        if self.groq_api_key:
            return f"groq/{self.groq_model}"
        if self.gemini_api_key:
            return f"gemini/{self.gemini_model}"
        if self.openrouter_api_key:
            return self.openrouter_model
        return "unconfigured"


@lru_cache
def get_settings() -> Settings:
    return Settings()
