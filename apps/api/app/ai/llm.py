"""LLM provider clients (OpenAI-compatible and Anthropic).

Every client is optional: when no provider is configured RepoLens runs in
retrieval-only mode and the chat service answers extractively from real
repository evidence instead of failing.
"""

from __future__ import annotations

import logging

import httpx

from repolens_shared.errors import LLMError

from ..core.config import Settings

logger = logging.getLogger(__name__)


class LLMClient:
    provider = "none"
    model = "none"
    available = False

    def complete(self, *, system: str, user: str, max_tokens: int | None = None,
                 temperature: float | None = None) -> str | None:
        raise NotImplementedError

    def describe(self) -> dict:
        return {"provider": self.provider, "model": self.model, "available": self.available}


class NoLLM(LLMClient):
    def __init__(self) -> None:
        self.provider = "none"
        self.model = "none"
        self.available = False

    def complete(self, **_kwargs) -> str | None:
        return None


class OpenAICompatibleLLM(LLMClient):
    def __init__(self, api_key: str, model: str, base_url: str | None = None, max_tokens: int = 2048,
                 temperature: float = 0.1, timeout: float = 90.0):
        self.api_key = api_key
        self.model = model
        self.base_url = (base_url or "https://api.openai.com/v1").rstrip("/")
        self.provider = "openai"
        self.available = True
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.timeout = timeout

    def complete(self, *, system: str, user: str, max_tokens: int | None = None,
                 temperature: float | None = None) -> str | None:
        payload = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "max_tokens": max_tokens or self.max_tokens,
            "temperature": self.temperature if temperature is None else temperature,
        }
        try:
            response = httpx.post(
                f"{self.base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
                json=payload, timeout=self.timeout,
            )
        except httpx.HTTPError as exc:
            raise LLMError(f"LLM request failed: {exc}") from exc
        if response.status_code >= 400:
            raise LLMError(f"LLM provider returned HTTP {response.status_code}: {response.text[:300]}")
        data = response.json()
        choices = data.get("choices") or []
        if not choices:
            return None
        return (choices[0].get("message") or {}).get("content")


class AnthropicLLM(LLMClient):
    def __init__(self, api_key: str, model: str = "claude-3-5-sonnet-latest", max_tokens: int = 2048,
                 temperature: float = 0.1, timeout: float = 90.0):
        self.api_key = api_key
        self.model = model
        self.provider = "anthropic"
        self.available = True
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.timeout = timeout

    def complete(self, *, system: str, user: str, max_tokens: int | None = None,
                 temperature: float | None = None) -> str | None:
        payload = {
            "model": self.model, "system": system, "max_tokens": max_tokens or self.max_tokens,
            "temperature": self.temperature if temperature is None else temperature,
            "messages": [{"role": "user", "content": user}],
        }
        try:
            response = httpx.post(
                "https://api.anthropic.com/v1/messages",
                headers={"x-api-key": self.api_key, "anthropic-version": "2023-06-01",
                         "Content-Type": "application/json"},
                json=payload, timeout=self.timeout,
            )
        except httpx.HTTPError as exc:
            raise LLMError(f"LLM request failed: {exc}") from exc
        if response.status_code >= 400:
            raise LLMError(f"LLM provider returned HTTP {response.status_code}: {response.text[:300]}")
        blocks = (response.json() or {}).get("content") or []
        text = "".join(block.get("text", "") for block in blocks if block.get("type") == "text")
        return text or None


def get_llm(settings: Settings) -> LLMClient:
    provider = (settings.llm_provider or "none").lower()
    if provider in {"none", ""}:
        return NoLLM()
    key = settings.active_llm_key()
    if not key:
        logger.warning("LLM_PROVIDER=%s but no API key is configured - running retrieval-only", provider)
        return NoLLM()
    try:
        if provider in {"openai", "azure-openai", "openai-compatible"}:
            return OpenAICompatibleLLM(
                api_key=key,
                model=settings.llm_model or "gpt-4o-mini",
                base_url=settings.openai_base_url,
                max_tokens=settings.llm_max_tokens,
                temperature=settings.llm_temperature,
            )
        if provider == "anthropic":
            return AnthropicLLM(
                api_key=key,
                model=settings.llm_model or "claude-3-5-sonnet-latest",
                max_tokens=settings.llm_max_tokens,
                temperature=settings.llm_temperature,
            )
    except Exception as exc:  # pragma: no cover
        logger.warning("Could not initialise LLM provider %s: %s", provider, exc)
    return NoLLM()
