from abc import ABC, abstractmethod
from typing import Any

import httpx
import numpy as np

from app.core.config import Settings


class EmbeddingProvider(ABC):
    @abstractmethod
    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        raise NotImplementedError

    @abstractmethod
    def embed_query(self, text: str) -> list[float]:
        raise NotImplementedError


class SentenceTransformerEmbeddingProvider(EmbeddingProvider):
    def __init__(self, model_name: str) -> None:
        self.model_name = model_name
        self._embeddings = None

    @property
    def embeddings(self):
        if self._embeddings is None:
            from langchain_community.embeddings import HuggingFaceEmbeddings

            self._embeddings = NormalizedLangChainEmbeddings(HuggingFaceEmbeddings(
                model_name=self.model_name,
                encode_kwargs={"normalize_embeddings": True},
            ))
        return self._embeddings

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self.embeddings.embed_documents(texts)

    def embed_query(self, text: str) -> list[float]:
        return self.embeddings.embed_query(text)


class OllamaEmbeddingProvider(EmbeddingProvider):
    def __init__(self, base_url: str, model: str, timeout_seconds: int) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout_seconds
        self._embeddings = None

    @property
    def embeddings(self):
        if self._embeddings is None:
            from langchain_community.embeddings import OllamaEmbeddings

            self._embeddings = NormalizedLangChainEmbeddings(OllamaEmbeddings(
                base_url=self.base_url,
                model=self.model,
            ))
        return self._embeddings

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self.embeddings.embed_documents(texts)

    def embed_query(self, text: str) -> list[float]:
        return self.embeddings.embed_query(text)


class NvidiaEmbeddingProvider(EmbeddingProvider):
    def __init__(
        self,
        base_url: str,
        api_key: str | None,
        model: str,
        truncate: str,
        encoding_format: str,
        timeout_seconds: int,
    ) -> None:
        if not api_key:
            raise ValueError("NVIDIA_API_KEY is required when EMBEDDING_PROVIDER=nvidia")
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.truncate = truncate
        self.encoding_format = encoding_format
        self.timeout = timeout_seconds
        self._embeddings = None

    @property
    def embeddings(self):
        if self._embeddings is None:
            self._embeddings = NvidiaLangChainEmbeddings(self)
        return self._embeddings

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self._embed(texts, "passage")

    def embed_query(self, text: str) -> list[float]:
        return self._embed([text], "query")[0]

    def _embed(self, texts: list[str], input_type: str) -> list[list[float]]:
        if not texts:
            return []
        response = httpx.post(
            f"{self.base_url}/embeddings",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            json={
                "input": texts,
                "model": self.model,
                "input_type": input_type,
                "encoding_format": self.encoding_format,
                "truncate": self.truncate,
            },
            timeout=self.timeout,
        )
        response.raise_for_status()
        payload = response.json()
        data = sorted(payload.get("data", []), key=lambda item: item.get("index", 0))
        return normalize_embedding_matrix([item["embedding"] for item in data], expected_count=len(texts))


class NormalizedLangChainEmbeddings:
    def __init__(self, delegate: Any, model: str | None = None) -> None:
        self.delegate = delegate
        self.model = model or getattr(delegate, "model", None) or getattr(delegate, "model_name", None) or "embedding"

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return normalize_embedding_matrix(self.delegate.embed_documents(texts), expected_count=len(texts))

    def embed_query(self, text: str) -> list[float]:
        return normalize_embedding_matrix([self.delegate.embed_query(text)], expected_count=1)[0]

    async def aembed_documents(self, texts: list[str]) -> list[list[float]]:
        return self.embed_documents(texts)

    async def aembed_query(self, text: str) -> list[float]:
        return self.embed_query(text)

    def __call__(self, input: Any) -> list[float] | list[list[float]]:
        if isinstance(input, str):
            return self.embed_query(input)
        return self.embed_documents(list(input))


class NvidiaLangChainEmbeddings(NormalizedLangChainEmbeddings):
    def __init__(self, provider: NvidiaEmbeddingProvider) -> None:
        super().__init__(provider, provider.model)


def create_embedding_provider(settings: Settings) -> EmbeddingProvider:
    provider = normalize_embedding_provider(settings.embedding_provider)
    if provider == "sentence_transformers":
        return SentenceTransformerEmbeddingProvider(settings.default_embedding_model or settings.sentence_transformer_model)
    if provider == "ollama":
        return OllamaEmbeddingProvider(
            settings.ollama_base_url,
            settings.ollama_embedding_model,
            settings.ollama_timeout_seconds,
        )
    if provider == "nvidia":
        return NvidiaEmbeddingProvider(
            settings.nvidia_base_url,
            settings.nvidia_api_key,
            settings.nvidia_embedding_model,
            settings.nvidia_embedding_truncate,
            settings.nvidia_embedding_encoding_format,
            settings.ollama_timeout_seconds,
        )
    raise ValueError(f"Unsupported embedding provider: {settings.embedding_provider}")


def normalize_embedding_provider(provider: str | None) -> str:
    value = (provider or "sentence_transformers").strip().lower().replace("-", "_")
    if value in {"sentence_transformers", "sentencetransformers", "st"}:
        return "sentence_transformers"
    if value in {"ollama", "local"}:
        return "ollama"
    if value == "nvidia":
        return "nvidia"
    return value


def normalize_embedding_matrix(vectors: list[list[float]], expected_count: int | None = None) -> list[list[float]]:
    if expected_count is not None and len(vectors) != expected_count:
        raise ValueError(f"Embedding count mismatch: expected {expected_count}, got {len(vectors)}")
    if not vectors:
        return []
    array = np.asarray(vectors, dtype=np.float32)
    if array.ndim == 1:
        array = array.reshape(1, -1)
    if array.ndim != 2 or array.shape[1] == 0:
        raise ValueError(f"Invalid embedding shape: {array.shape}")
    if expected_count is not None and array.shape[0] != expected_count:
        raise ValueError(f"Embedding count mismatch: expected {expected_count}, got {array.shape[0]}")
    if not np.isfinite(array).all():
        raise ValueError("Embedding contains NaN or infinite values")
    norms = np.linalg.norm(array, axis=1, keepdims=True)
    if np.any(norms <= 0):
        raise ValueError("Embedding contains zero-length vectors")
    array = array / np.clip(norms, np.finfo(np.float32).eps, None)
    return array.astype(np.float32).tolist()
