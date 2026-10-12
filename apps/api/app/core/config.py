"""Settings for public-only GitHub access and in-memory SQLite storage."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

API_DIR = Path(__file__).resolve().parents[2]
REPO_ROOT = API_DIR.parents[1]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(REPO_ROOT / ".env", API_DIR / ".env"),
        extra="ignore",
        case_sensitive=False,
    )

    app_name: str = "RepoLens API"
    app_env: str = Field(default="development", alias="APP_ENV")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    cors_origins: str = Field(
        default="http://localhost:3000,http://127.0.0.1:3000",
        alias="CORS_ORIGINS",
    )
    # Optional server-side credential for authenticated public GitHub API requests.
    # Private repositories remain unsupported regardless of this setting.
    github_token: SecretStr | None = Field(default=None, alias="GITHUB_TOKEN", repr=False)

    # Optional, server-only RAG provider and Neon pgvector configuration. Both secrets
    # are required before source excerpts are embedded or stored persistently.
    rag_database_url: SecretStr | None = Field(default=None, alias="RAG_DATABASE_URL", repr=False)
    rag_api_key: SecretStr | None = Field(default=None, alias="RAG_API_KEY", repr=False)
    rag_api_base_url: str = Field(default="https://api.openai.com/v1", alias="RAG_API_BASE_URL")
    rag_chat_model: str = Field(default="gpt-4o-mini", alias="RAG_CHAT_MODEL")
    rag_embedding_model: str = Field(default="text-embedding-3-small", alias="RAG_EMBEDDING_MODEL")
    rag_embedding_dimensions: int = Field(default=1536, alias="RAG_EMBEDDING_DIMENSIONS")
    rag_index_max_chunks: int = Field(default=250, alias="RAG_INDEX_MAX_CHUNKS")
    rag_chunk_max_chars: int = Field(default=3500, alias="RAG_CHUNK_MAX_CHARS")
    rag_chunk_ttl_hours: int = Field(default=24, alias="RAG_CHUNK_TTL_HOURS")
    rag_top_k: int = Field(default=6, alias="RAG_TOP_K")
    rag_context_max_chars: int = Field(default=18000, alias="RAG_CONTEXT_MAX_CHARS")
    rag_max_history_messages: int = Field(default=8, alias="RAG_MAX_HISTORY_MESSAGES")
    rag_max_output_tokens: int = Field(default=800, alias="RAG_MAX_OUTPUT_TOKENS")
    rag_api_timeout_seconds: int = Field(default=60, alias="RAG_API_TIMEOUT_SECONDS")
    rag_chat_requests_per_minute: int = Field(default=12, alias="RAG_CHAT_REQUESTS_PER_MINUTE")

    # Limits for anonymous browser sessions and repository downloads.
    max_files: int = Field(default=4000, alias="MAX_FILES")
    max_file_bytes: int = Field(default=1_048_576, alias="MAX_FILE_BYTES")
    max_repo_bytes: int = Field(default=104_857_600, alias="MAX_REPO_BYTES")
    max_analysis_seconds: int = Field(default=1800, alias="MAX_ANALYSIS_SECONDS")
    analysis_workers: int = Field(default=2, alias="ANALYSIS_WORKERS")
    max_pending_analyses: int = Field(default=20, alias="MAX_PENDING_ANALYSES")
    max_active_analyses_per_session: int = Field(default=2, alias="MAX_ACTIVE_ANALYSES_PER_SESSION")
    max_analyses_per_hour: int = Field(default=20, alias="MAX_ANALYSES_PER_HOUR")

    # Results expire when their owning tab reports no recent user activity.
    window_ttl_seconds: int = Field(default=1800, alias="WINDOW_TTL_SECONDS")
    window_sweep_seconds: int = Field(default=30, alias="WINDOW_SWEEP_SECONDS")
    session_ttl_seconds: int = Field(default=2_592_000, alias="SESSION_TTL_SECONDS")
    store_source_snippets: bool = Field(default=False, alias="STORE_SOURCE_SNIPPETS")

    @field_validator("log_level")
    @classmethod
    def _upper(cls, value: str) -> str:
        return (value or "INFO").upper()

    @field_validator("github_token", "rag_database_url", "rag_api_key", mode="before")
    @classmethod
    def _clean_secret_settings(cls, value) -> SecretStr | None:
        if value is None:
            return None
        if isinstance(value, SecretStr):
            value = value.get_secret_value()
        secret = str(value).strip()
        return SecretStr(secret) if secret else None

    @field_validator("rag_api_base_url")
    @classmethod
    def _valid_rag_api_base_url(cls, value: str) -> str:
        from urllib.parse import urlsplit

        cleaned = (value or "").strip().rstrip("/")
        parsed = urlsplit(cleaned)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("RAG_API_BASE_URL must be an absolute HTTP(S) URL")
        return cleaned

    @field_validator("rag_chat_model", "rag_embedding_model")
    @classmethod
    def _nonempty_rag_model(cls, value: str) -> str:
        cleaned = (value or "").strip()
        if not cleaned or len(cleaned) > 160:
            raise ValueError("model names must be between 1 and 160 characters")
        return cleaned

    @field_validator("rag_embedding_dimensions")
    @classmethod
    def _valid_embedding_dimensions(cls, value: int) -> int:
        # Keep embeddings within a conservative size supported by common providers and pgvector indexes.
        if not 8 <= value <= 2000:
            raise ValueError("RAG_EMBEDDING_DIMENSIONS must be between 8 and 2000")
        return value

    @field_validator("rag_index_max_chunks")
    @classmethod
    def _bound_rag_chunk_count(cls, value: int) -> int:
        if value > 2000:
            raise ValueError("RAG_INDEX_MAX_CHUNKS must not exceed 2000")
        return value

    @field_validator("rag_chunk_max_chars")
    @classmethod
    def _bound_rag_chunk_size(cls, value: int) -> int:
        if value > 12_000:
            raise ValueError("RAG_CHUNK_MAX_CHARS must not exceed 12000")
        return value

    @field_validator("rag_chunk_ttl_hours")
    @classmethod
    def _bound_rag_chunk_ttl(cls, value: int) -> int:
        if not 1 <= value <= 8_760:
            raise ValueError("RAG_CHUNK_TTL_HOURS must be between 1 and 8760")
        return value

    @field_validator("rag_top_k")
    @classmethod
    def _bound_rag_top_k(cls, value: int) -> int:
        if value > 20:
            raise ValueError("RAG_TOP_K must not exceed 20")
        return value

    @field_validator("rag_context_max_chars")
    @classmethod
    def _bound_rag_context(cls, value: int) -> int:
        if value > 100_000:
            raise ValueError("RAG_CONTEXT_MAX_CHARS must not exceed 100000")
        return value

    @field_validator("rag_max_history_messages")
    @classmethod
    def _bound_rag_history(cls, value: int) -> int:
        if value > 20:
            raise ValueError("RAG_MAX_HISTORY_MESSAGES must not exceed 20")
        return value

    @field_validator("rag_max_output_tokens")
    @classmethod
    def _bound_rag_output_tokens(cls, value: int) -> int:
        if value > 4_000:
            raise ValueError("RAG_MAX_OUTPUT_TOKENS must not exceed 4000")
        return value

    @field_validator("rag_api_timeout_seconds")
    @classmethod
    def _bound_rag_timeout(cls, value: int) -> int:
        if value > 300:
            raise ValueError("RAG_API_TIMEOUT_SECONDS must not exceed 300")
        return value

    @field_validator("rag_chat_requests_per_minute")
    @classmethod
    def _bound_rag_rate_limit(cls, value: int) -> int:
        if value > 120:
            raise ValueError("RAG_CHAT_REQUESTS_PER_MINUTE must not exceed 120")
        return value

    @field_validator(
        "max_files",
        "max_file_bytes",
        "max_analysis_seconds",
        "analysis_workers",
        "max_pending_analyses",
        "max_active_analyses_per_session",
        "max_analyses_per_hour",
        "window_ttl_seconds",
        "session_ttl_seconds",
        "rag_index_max_chunks",
        "rag_chunk_max_chars",
        "rag_top_k",
        "rag_context_max_chars",
        "rag_max_history_messages",
        "rag_max_output_tokens",
        "rag_api_timeout_seconds",
        "rag_chat_requests_per_minute",
    )
    @classmethod
    def _positive_limits(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("must be greater than zero")
        return value

    @field_validator("window_sweep_seconds")
    @classmethod
    def _minimum_sweep_interval(cls, value: int) -> int:
        if value < 5:
            raise ValueError("must be at least 5 seconds")
        return value

    @field_validator("max_repo_bytes")
    @classmethod
    def _nonnegative_repo_cap(cls, value: int) -> int:
        if value < 0:
            raise ValueError("must be zero (unlimited) or greater")
        return value

    @property
    def rag_enabled(self) -> bool:
        return bool(self.rag_database_url and self.rag_api_key)

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    def public_config(self) -> dict:
        return {
            "storage": {"mode": "memory", "local_files": False},
            "github": {
                "rate_limit": (
                    "up to 5,000 requests/hour (authenticated)"
                    if self.github_token else "60 requests/hour (anonymous)"
                ),
            },
            "limits": {
                "max_files": self.max_files,
                "max_file_bytes": self.max_file_bytes,
                "max_repo_bytes": self.max_repo_bytes,
                "max_analysis_seconds": self.max_analysis_seconds,
                "max_active_analyses_per_session": self.max_active_analyses_per_session,
                "max_analyses_per_hour": self.max_analyses_per_hour,
                "max_pending_analyses": self.max_pending_analyses,
                "analysis_workers": self.analysis_workers,
                "window_ttl_seconds": self.window_ttl_seconds,
                "window_sweep_seconds": self.window_sweep_seconds,
            },
            "source_snippets_stored": self.store_source_snippets,
            "private_repositories_allowed": False,
        }


@lru_cache
def get_settings() -> Settings:
    return Settings()
