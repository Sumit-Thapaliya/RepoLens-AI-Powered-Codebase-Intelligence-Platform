"""Application settings. The default setup uses anonymous GitHub access and in-memory SQLite."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
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
    # Limits for anonymous browser sessions and repository downloads.
    max_files: int = Field(default=4000, alias="MAX_FILES")
    max_file_bytes: int = Field(default=1_048_576, alias="MAX_FILE_BYTES")
    max_repo_bytes: int = Field(default=104_857_600, alias="MAX_REPO_BYTES")
    max_analysis_seconds: int = Field(default=1800, alias="MAX_ANALYSIS_SECONDS")
    analysis_workers: int = Field(default=2, alias="ANALYSIS_WORKERS")
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

    @field_validator(
        "max_files",
        "max_file_bytes",
        "max_analysis_seconds",
        "analysis_workers",
        "max_active_analyses_per_session",
        "max_analyses_per_hour",
        "window_ttl_seconds",
        "session_ttl_seconds",
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
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    def public_config(self) -> dict:
        return {
            "storage": {"mode": "memory", "local_files": False},
            "github": {
                "rate_limit": "60 requests/hour (anonymous)",
            },
            "limits": {
                "max_files": self.max_files,
                "max_file_bytes": self.max_file_bytes,
                "max_repo_bytes": self.max_repo_bytes,
                "max_analysis_seconds": self.max_analysis_seconds,
                "max_active_analyses_per_session": self.max_active_analyses_per_session,
                "max_analyses_per_hour": self.max_analyses_per_hour,
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
