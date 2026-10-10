"""Typed application settings. All secrets come from the environment."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

API_DIR = Path(__file__).resolve().parents[2]
REPO_ROOT = API_DIR.parents[1]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=(REPO_ROOT / ".env", API_DIR / ".env"), extra="ignore",
                                      case_sensitive=False)

    app_name: str = "RepoLens API"
    app_env: str = Field(default="development", alias="APP_ENV")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    cors_origins: str = Field(default="http://localhost:3000,http://127.0.0.1:3000", alias="CORS_ORIGINS")

    # Storage: empty = in-memory only (nothing written to disk). A postgresql:// URL (e.g. Neon) = stored there.
    database_url: str = Field(default="", alias="DATABASE_URL")

    # GitHub
    github_token: str | None = Field(default=None, alias="GITHUB_TOKEN")
    github_api_base: str = Field(default="https://api.github.com", alias="GITHUB_API_BASE")

    # Limits. The time limit is the real guard; size and count caps are optional (0 = none).
    max_files: int = Field(default=4000, alias="MAX_FILES")
    max_file_bytes: int = Field(default=1_048_576, alias="MAX_FILE_BYTES")
    max_repo_bytes: int = Field(default=0, alias="MAX_REPO_BYTES")
    max_analysis_seconds: int = Field(default=1800, alias="MAX_ANALYSIS_SECONDS")
    analysis_workers: int = Field(default=2, alias="ANALYSIS_WORKERS")

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
    def storage_mode(self) -> str:
        return "postgres" if self.is_postgres else "memory"

    def public_config(self) -> dict:
        return {
            "storage": {"mode": self.storage_mode, "local_files": False},
            "github": {"authenticated": bool(self.github_token), "api_base": self.github_api_base,
                       "rate_limit": "5000 requests/hour (token)" if self.github_token
                       else "60 requests/hour (anonymous)"},
            "limits": {
                "max_files": self.max_files,
                "max_file_bytes": self.max_file_bytes,
                "max_repo_bytes": self.max_repo_bytes,
                "max_analysis_seconds": self.max_analysis_seconds,
                "analysis_workers": self.analysis_workers,
            },
        }


@lru_cache
def get_settings() -> Settings:
    return Settings()
