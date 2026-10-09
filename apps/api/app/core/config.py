"""Typed application settings. All secrets come from the environment."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

API_DIR = Path(__file__).resolve().parents[2]
REPO_ROOT = API_DIR.parents[1]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=(REPO_ROOT / ".env", API_DIR / ".env"), extra="ignore", case_sensitive=False)

    app_name: str = "RepoLens API"
    app_env: str = Field(default="development", alias="APP_ENV")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    cors_origins: str = Field(default="http://localhost:3000,http://127.0.0.1:3000", alias="CORS_ORIGINS")

    # database
    database_url: str = Field(default="sqlite:///./data/repolens.db", alias="DATABASE_URL")
    enable_pgvector: bool = Field(default=True, alias="ENABLE_PGVECTOR")
    embedding_dim: int = Field(default=1536, alias="EMBEDDING_DIM")

    # github
    github_token: str | None = Field(default=None, alias="GITHUB_TOKEN")
    github_api_base: str = Field(default="https://api.github.com", alias="GITHUB_API_BASE")

    # llm
    llm_provider: str = Field(default="none", alias="LLM_PROVIDER")
    llm_model: str | None = Field(default=None, alias="LLM_MODEL")
    llm_max_tokens: int = Field(default=2048, alias="LLM_MAX_TOKENS")
    llm_temperature: float = Field(default=0.1, alias="LLM_TEMPERATURE")
    openai_api_key: str | None = Field(default=None, alias="OPENAI_API_KEY")
    openai_base_url: str | None = Field(default=None, alias="OPENAI_BASE_URL")
    anthropic_api_key: str | None = Field(default=None, alias="ANTHROPIC_API_KEY")

    # embeddings
    embeddings_provider: str = Field(default="local", alias="EMBEDDINGS_PROVIDER")
    embeddings_model: str | None = Field(default=None, alias="EMBEDDINGS_MODEL")

    # limits
    max_files: int = Field(default=4000, alias="MAX_FILES")
    max_file_bytes: int = Field(default=1_048_576, alias="MAX_FILE_BYTES")
    max_repo_bytes: int = Field(default=268_435_456, alias="MAX_REPO_BYTES")
    max_analysis_seconds: int = Field(default=1800, alias="MAX_ANALYSIS_SECONDS")
    analysis_workers: int = Field(default=2, alias="ANALYSIS_WORKERS")

    # workspace
    data_dir: Path = Field(default=REPO_ROOT / "data", alias="REPOLENS_DATA_DIR")
    repo_cache_dir: Path | None = Field(default=None, alias="REPOLENS_REPO_CACHE")

    @field_validator("log_level")
    @classmethod
    def _upper(cls, value: str) -> str:
        return (value or "INFO").upper()

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def is_postgres(self) -> bool:
        return self.database_url.startswith(("postgresql", "postgres"))

    @property
    def pgvector_enabled(self) -> bool:
        return bool(self.enable_pgvector and self.is_postgres)

    @property
    def cache_dir(self) -> Path:
        return self.repo_cache_dir or (self.data_dir / "repos")

    @property
    def sqlite_path(self) -> Path | None:
        if self.is_postgres:
            return None
        prefix = "sqlite:///"
        if self.database_url.startswith(prefix):
            return Path(self.database_url[len(prefix):]).expanduser()
        return None

    def resolved_database_url(self) -> str:
        """Make relative SQLite paths absolute so the API works from any cwd."""
        path = self.sqlite_path
        if path is not None and not path.is_absolute():
            absolute = (REPO_ROOT / path).resolve()
            return f"sqlite:///{absolute}"
        return self.database_url

    def public_config(self) -> dict:
        return {
            "database": {
                "dialect": "postgresql" if self.is_postgres else "sqlite",
                "pgvector": self.pgvector_enabled,
                "location": _redact(self.database_url),
            },
            "github": {"authenticated": bool(self.github_token), "api_base": self.github_api_base,
                       "rate_limit": "5000 requests/hour (token)" if self.github_token else "60 requests/hour (anonymous)"},
            "llm": {
                "provider": self.llm_provider,
                "model": self.llm_model,
                "configured": self.llm_provider not in {"none", "", None} and bool(self.active_llm_key()),
            },
            "embeddings": {
                "provider": self.embeddings_provider,
                "model": self.embeddings_model,
                "dim": self.embedding_dim,
                "neural": self.embeddings_provider == "openai" and bool(self.openai_api_key),
            },
            "limits": {
                "max_files": self.max_files,
                "max_file_bytes": self.max_file_bytes,
                "max_repo_bytes": self.max_repo_bytes,
                "max_analysis_seconds": self.max_analysis_seconds,
                "analysis_workers": self.analysis_workers,
            },
        }

    def active_llm_key(self) -> str | None:
        provider = (self.llm_provider or "none").lower()
        if provider in {"openai", "azure-openai", "openai-compatible"}:
            return self.openai_api_key
        if provider == "anthropic":
            return self.anthropic_api_key
        return None


def _redact(url: str) -> str:
    if "://" not in url:
        return url
    scheme, rest = url.split("://", 1)
    if "@" in rest:
        credentials, host = rest.rsplit("@", 1)
        user = credentials.split(":", 1)[0]
        return f"{scheme}://{user}:***@{host}"
    return url


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    os.environ.setdefault("REPOLENS_DATA_DIR", str(settings.data_dir))
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    settings.cache_dir.mkdir(parents=True, exist_ok=True)
    return settings
