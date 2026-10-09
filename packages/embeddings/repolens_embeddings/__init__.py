"""Embeddings and vector search for RepoLens."""

from .embedder import (  # noqa: F401
    Embedder,
    HashedEmbedder,
    OpenAIEmbedder,
    cosine_similarity,
    get_embedder,
    pack_vector,
    unpack_vector,
)
from .store import MemoryVectorStore, PgVectorStore, StoredChunk, lexical_score  # noqa: F401

__all__ = [
    "Embedder", "HashedEmbedder", "OpenAIEmbedder", "get_embedder", "cosine_similarity",
    "MemoryVectorStore", "PgVectorStore", "StoredChunk", "lexical_score", "pack_vector", "unpack_vector",
]
