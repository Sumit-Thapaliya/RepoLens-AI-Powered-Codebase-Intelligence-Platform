"""Embedding providers.

Two providers ship with RepoLens:

``openai``
    Real neural embeddings via any OpenAI-compatible endpoint
    (``OPENAI_API_KEY`` + optional ``OPENAI_BASE_URL``).

``hashed``
    A deterministic, offline, dependency-free embedding over code-aware tokens
    (identifiers, sub-tokens, character trigrams). It gives genuine lexical
    retrieval - and the UI labels it as such - so semantic search, impact
    analysis and grounded chat work with no API key at all. It is *not* a
    neural semantic model and RepoLens never pretends it is.

Both providers return L2-normalised ``list[float]`` vectors of a fixed width so
the storage layer can be dimension agnostic.
"""

from __future__ import annotations

import hashlib
import logging
import math
import re
from typing import Iterable, Protocol

import httpx

from repolens_shared.errors import EmbeddingError

logger = logging.getLogger(__name__)

CODE_TOKEN_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*|\d+|<<|>>|::|->|=>|[{}()\[\].,;:<>+\-*/%&|=!?]+")
SUBTOKEN_RE = re.compile(r"[A-Z]+(?=[A-Z][a-z])|[A-Z]?[a-z]+|\d+")

#: Words that carry no retrieval signal in code.
STOPWORDS = {
    "the", "a", "an", "and", "or", "of", "to", "in", "is", "it", "for", "on", "with", "as", "that",
    "self", "this", "def", "function", "const", "let", "var", "return", "import", "from", "class",
    "await", "async", "public", "private", "static", "void", "new", "if", "else", "for", "while",
}


class Embedder(Protocol):
    name: str
    model: str
    dim: int

    def embed(self, texts: list[str]) -> list[list[float]]: ...
    def embed_one(self, text: str) -> list[float]: ...
    def describe(self) -> dict: ...


# --------------------------------------------------------------------------- #
# Hashed (offline) embeddings
# --------------------------------------------------------------------------- #

class HashedEmbedder:
    """Deterministic hashed n-gram embedding (no network, no keys)."""

    def __init__(self, dim: int = 1536):
        self.dim = dim
        self.name = "hashed"
        self.model = f"hashed-ngram-v1-{dim}d"

    # -- tokenisation -------------------------------------------------------
    def _features(self, text: str) -> Iterable[tuple[str, float]]:
        lowered = (text or "").lower()
        tokens = [token for token in CODE_TOKEN_RE.findall(lowered) if len(token) > 1]
        for token in tokens:
            if token in STOPWORDS:
                continue
            yield token, 1.0
            for part in SUBTOKEN_RE.findall(token):
                if len(part) > 2 and part not in STOPWORDS:
                    yield f"sub:{part}", 0.8
        # character trigrams for identifier-level fuzziness
        for index in range(0, max(0, len(lowered) - 12), 3):
            window = lowered[index: index + 14].strip()
            if len(window) >= 8:
                yield f"tri:{hashlib.blake2b(window.encode(), digest_size=4).hexdigest()}", 0.25

    def _bucket(self, feature: str) -> tuple[int, float]:
        digest = hashlib.blake2b(feature.encode("utf-8"), digest_size=8).digest()
        value = int.from_bytes(digest, "little")
        index = value % self.dim
        sign = 1.0 if (value >> 63) & 1 else -1.0
        return index, sign

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._embed_one(text) for text in texts]

    def _embed_one(self, text: str) -> list[float]:
        vector = [0.0] * self.dim
        counts: dict[str, int] = {}
        for feature, weight in self._features(text[:20000]):
            counts[feature] = counts.get(feature, 0) + 1
            index, sign = self._bucket(feature)
            vector[index] += sign * weight
        norm = math.sqrt(sum(value * value for value in vector)) or 1.0
        return [value / norm for value in vector]

    def embed_one(self, text: str) -> list[float]:
        return self._embed_one(text)

    def describe(self) -> dict:
        return {
            "provider": self.name,
            "model": self.model,
            "dim": self.dim,
            "type": "lexical-hashed",
            "note": "Offline embedding derived from code tokens and n-grams. Supports real retrieval, "
                    "but is not a neural semantic model.",
        }


# --------------------------------------------------------------------------- #
# OpenAI-compatible embeddings
# --------------------------------------------------------------------------- #

class OpenAIEmbedder:
    def __init__(self, api_key: str, model: str = "text-embedding-3-small", base_url: str | None = None,
                 dim: int = 1536, timeout: float = 30.0, batch_size: int = 96):
        if not api_key:
            raise EmbeddingError("OPENAI_API_KEY is not configured.")
        self.api_key = api_key
        self.model = model
        self.base_url = (base_url or "https://api.openai.com/v1").rstrip("/")
        self.dim = dim
        self.name = "openai"
        self.timeout = timeout
        self.batch_size = batch_size
        self._detected_dim: int | None = None

    def _endpoint(self) -> str:
        return f"{self.base_url}/embeddings"

    def embed(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for start in range(0, len(texts), self.batch_size):
            batch = [text[:8000] if text else " " for text in texts[start: start + self.batch_size]]
            try:
                response = httpx.post(
                    self._endpoint(),
                    headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
                    json={"model": self.model, "input": batch},
                    timeout=self.timeout,
                )
            except httpx.HTTPError as exc:
                raise EmbeddingError(f"Embedding request failed: {exc}") from exc
            if response.status_code >= 400:
                detail = response.text[:300]
                raise EmbeddingError(f"Embedding provider returned HTTP {response.status_code}: {detail}")
            payload = response.json()
            data = sorted(payload.get("data", []), key=lambda item: item.get("index", 0))
            for item in data:
                vector = item.get("embedding") or []
                if not vector:
                    raise EmbeddingError("Embedding provider returned an empty vector.")
                self._detected_dim = len(vector)
                vectors.append(_normalize(vector))
        if not vectors:
            return []
        return vectors

    def embed_one(self, text: str) -> list[float]:
        return self.embed([text])[0]

    def describe(self) -> dict:
        return {
            "provider": self.name, "model": self.model, "dim": self._detected_dim or self.dim,
            "type": "neural", "endpoint": self.base_url,
            "note": "Neural embeddings from an OpenAI-compatible endpoint.",
        }


def _normalize(vector: list[float]) -> list[float]:
    norm = math.sqrt(sum(value * value for value in vector)) or 1.0
    return [value / norm for value in vector]


# --------------------------------------------------------------------------- #

def get_embedder(provider: str = "local", *, dim: int = 1536, api_key: str | None = None,
                 model: str | None = None, base_url: str | None = None) -> Embedder:
    """Build an embedder, degrading gracefully to the offline provider."""
    provider = (provider or "local").lower()
    if provider == "openai" and api_key:
        try:
            return OpenAIEmbedder(api_key=api_key, model=model or "text-embedding-3-small", base_url=base_url, dim=dim)
        except EmbeddingError as exc:
            logger.warning("Falling back to offline embeddings: %s", exc)
    return HashedEmbedder(dim=dim)


def cosine_similarity(a: list[float], b: list[float]) -> float:
    if not a or not b:
        return 0.0
    length = min(len(a), len(b))
    dot = sum(a[index] * b[index] for index in range(length))
    norm_a = math.sqrt(sum(value * value for value in a)) or 1.0
    norm_b = math.sqrt(sum(value * value for value in b)) or 1.0
    return dot / (norm_a * norm_b)


def pack_vector(vector: list[float]) -> str:
    """JSON representation used by the SQLite fallback path."""
    import json
    return json.dumps([round(value, 6) for value in vector])


def unpack_vector(payload: str | None) -> list[float]:
    if not payload:
        return []
    import json
    try:
        return json.loads(payload)
    except (ValueError, TypeError):
        return []
