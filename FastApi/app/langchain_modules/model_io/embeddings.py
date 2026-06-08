from abc import ABC, abstractmethod
from concurrent.futures import ThreadPoolExecutor
import logging
import time
from typing import Any

import httpx
import numpy as np

from app.core.config import Settings

logger = logging.getLogger(__name__)


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
        batch_size: int,
        max_concurrency: int,
        max_retries: int,
        retry_backoff_seconds: float,
        retry_max_backoff_seconds: float,
    ) -> None:
        if not api_key:
            raise ValueError("NVIDIA_API_KEY is required when EMBEDDING_PROVIDER=nvidia")
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.truncate = truncate
        self.encoding_format = encoding_format
        self.timeout = timeout_seconds
        self.batch_size = max(int(batch_size), 1)
        self.max_concurrency = max(int(max_concurrency), 1)
        self.max_retries = max(int(max_retries), 1)
        self.retry_backoff_seconds = max(float(retry_backoff_seconds), 0.0)
        self.retry_max_backoff_seconds = max(float(retry_max_backoff_seconds), self.retry_backoff_seconds)
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
        batches = [texts[start:start + self.batch_size] for start in range(0, len(texts), self.batch_size)]
        if self.max_concurrency <= 1 or len(batches) <= 1:
            vectors = [vector for batch in batches for vector in self._embed_batch(batch, input_type)]
            return normalize_embedding_matrix(vectors, expected_count=len(texts))

        workers = min(self.max_concurrency, len(batches))
        with ThreadPoolExecutor(max_workers=workers) as executor:
            batch_vectors = list(executor.map(lambda batch: self._embed_batch(batch, input_type), batches))
        vectors = [vector for batch in batch_vectors for vector in batch]
        return normalize_embedding_matrix(vectors, expected_count=len(texts))

    def _embed_batch(self, texts: list[str], input_type: str) -> list[list[float]]:
        last_error: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            try:
                response = self._post_embeddings(texts, input_type)
                response.raise_for_status()
                payload = response.json()
                data = sorted(payload.get("data", []), key=lambda item: item.get("index", 0))
                return [item["embedding"] for item in data]
            except httpx.HTTPStatusError as exc:
                if not retryable_http_status(exc.response.status_code):
                    raise
                last_error = exc
                self._log_retry(attempt, len(texts), exc)
            except httpx.TransportError as exc:
                last_error = exc
                self._log_retry(attempt, len(texts), exc)
            if attempt < self.max_retries:
                time.sleep(self._retry_delay(attempt))
        if last_error is not None:
            raise last_error
        raise RuntimeError("NVIDIA embedding request failed without an exception.")

    def _post_embeddings(self, texts: list[str], input_type: str) -> httpx.Response:
        return httpx.post(
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

    def _retry_delay(self, attempt: int) -> float:
        return min(
            self.retry_backoff_seconds * (2 ** max(attempt - 1, 0)),
            self.retry_max_backoff_seconds,
        )

    def _log_retry(self, attempt: int, batch_size: int, exc: Exception) -> None:
        if attempt >= self.max_retries:
            return
        logger.warning(
            "NVIDIA embedding request failed, retrying attempt=%s/%s batch_size=%s error=%s",
            attempt,
            self.max_retries,
            batch_size,
            exc,
        )


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
            settings.nvidia_embedding_batch_size,
            settings.nvidia_embedding_max_concurrency,
            settings.nvidia_embedding_max_retries,
            settings.nvidia_embedding_retry_backoff_seconds,
            settings.nvidia_embedding_retry_max_backoff_seconds,
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


def retryable_http_status(status_code: int) -> bool:
    return status_code == 429 or status_code >= 500


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
