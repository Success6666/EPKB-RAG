import hashlib
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from langchain_core.documents import Document

from app.core.config import Settings
from app.langchain_modules.model_io.embeddings import EmbeddingProvider


@dataclass(frozen=True)
class KnowledgeBaseScope:
    tenant_id: str
    kb_id: str


@dataclass
class VectorSearchResult:
    chunk_id: str
    text: str
    metadata: dict[str, Any]
    score: float


class VectorStore(ABC):
    @abstractmethod
    def upsert_chunks(self, scope: KnowledgeBaseScope, chunks: list[dict[str, Any]]) -> None:
        raise NotImplementedError

    @abstractmethod
    def similarity_search(
        self,
        scope: KnowledgeBaseScope,
        query: str,
        top_k: int,
        metadata_filter: dict[str, Any] | None = None,
    ) -> list[VectorSearchResult]:
        raise NotImplementedError

    @abstractmethod
    def list_chunks(
        self,
        scope: KnowledgeBaseScope,
        limit: int,
        metadata_filter: dict[str, Any] | None = None,
    ) -> list[VectorSearchResult]:
        raise NotImplementedError

    @abstractmethod
    def delete_document(self, scope: KnowledgeBaseScope, doc_id: str) -> None:
        raise NotImplementedError


class LangChainChromaVectorStore(VectorStore):
    def __init__(self, persist_dir: str, embeddings: EmbeddingProvider, upsert_batch_size: int) -> None:
        self.persist_dir = persist_dir
        self.embeddings = embeddings
        self.upsert_batch_size = max(int(upsert_batch_size), 1)
        self._stores = {}

    def upsert_chunks(self, scope: KnowledgeBaseScope, chunks: list[dict[str, Any]]) -> None:
        if not chunks:
            return
        store = self._store(scope)
        doc_id = chunk_doc_id(chunks)
        delete_chroma_document(store, scope, doc_id)
        try:
            for batch in batched(chunks, self.upsert_batch_size):
                store.add_documents(
                    documents=[to_document(chunk, scope) for chunk in batch],
                    ids=[chunk["id"] for chunk in batch],
                )
        except Exception:
            delete_chroma_document(store, scope, doc_id)
            raise

    def similarity_search(
        self,
        scope: KnowledgeBaseScope,
        query: str,
        top_k: int,
        metadata_filter: dict[str, Any] | None = None,
    ) -> list[VectorSearchResult]:
        results = self._store(scope).similarity_search_with_score(
            query=query,
            k=top_k,
            filter=chroma_filter(scope, metadata_filter),
        )
        return [from_document(document, 1.0 / (1.0 + float(distance))) for document, distance in results]

    def list_chunks(
        self,
        scope: KnowledgeBaseScope,
        limit: int,
        metadata_filter: dict[str, Any] | None = None,
    ) -> list[VectorSearchResult]:
        raw = self._store(scope).get(
            where=chroma_filter(scope, metadata_filter),
            limit=limit,
            include=["documents", "metadatas"],
        )
        ids = raw.get("ids", [])
        documents = raw.get("documents", [])
        metadatas = raw.get("metadatas", [])
        return [
            VectorSearchResult(
                chunk_id=str(metadata.get("chunk_id") or chunk_id),
                text=document,
                metadata=dict(metadata or {}),
                score=0.0,
            )
            for chunk_id, document, metadata in zip(ids, documents, metadatas)
        ]

    def delete_document(self, scope: KnowledgeBaseScope, doc_id: str) -> None:
        delete_chroma_document_by_name(self.persist_dir, scope, doc_id)

    def _store(self, scope: KnowledgeBaseScope):
        key = collection_name(scope)
        if key not in self._stores:
            from langchain_community.vectorstores import Chroma

            self._stores[key] = Chroma(
                collection_name=key,
                persist_directory=self.persist_dir,
                embedding_function=self.embeddings.embeddings,
            )
        return self._stores[key]


class LangChainMilvusVectorStore(VectorStore):
    def __init__(self, settings: Settings, embeddings: EmbeddingProvider) -> None:
        self.settings = settings
        self.embeddings = embeddings
        self._stores = {}

    def upsert_chunks(self, scope: KnowledgeBaseScope, chunks: list[dict[str, Any]]) -> None:
        if not chunks:
            return
        store = self._store(scope)
        doc_id = chunk_doc_id(chunks)
        delete_milvus_document(store, scope, doc_id)
        batch_size = max(int(self.settings.vector_upsert_batch_size), 1)
        try:
            for batch in batched(chunks, batch_size):
                store.add_documents(
                    documents=[to_document(chunk, scope) for chunk in batch],
                    ids=[chunk["id"] for chunk in batch],
                )
        except Exception:
            delete_milvus_document(store, scope, doc_id)
            raise

    def similarity_search(
        self,
        scope: KnowledgeBaseScope,
        query: str,
        top_k: int,
        metadata_filter: dict[str, Any] | None = None,
    ) -> list[VectorSearchResult]:
        store = self._store(scope)
        metric_type = milvus_metric_type(store, self.settings.milvus_metric_type)
        results = store.similarity_search_with_score(
            query=query,
            k=top_k,
            param=milvus_search_params(self.settings, top_k),
            expr=milvus_filter(scope, metadata_filter),
        )
        return [
            from_document(
                document,
                milvus_similarity_score(float(score), metric_type),
                {"milvus_raw_score": float(score), "milvus_metric_type": metric_type},
            )
            for document, score in results
        ]

    def list_chunks(
        self,
        scope: KnowledgeBaseScope,
        limit: int,
        metadata_filter: dict[str, Any] | None = None,
    ) -> list[VectorSearchResult]:
        collection = self._store(scope).col
        if collection is None:
            return []
        rows = collection.query(
            expr=milvus_filter(scope, metadata_filter),
            limit=limit,
            output_fields=["pk", "text", "metadata"],
        )
        return [
            VectorSearchResult(
                chunk_id=str((row.get("metadata") or {}).get("chunk_id") or row.get("pk")),
                text=row.get("text", ""),
                metadata=dict(row.get("metadata") or {}),
                score=0.0,
            )
            for row in rows
        ]

    def delete_document(self, scope: KnowledgeBaseScope, doc_id: str) -> None:
        delete_milvus_document_by_name(self.settings, scope, doc_id)

    def _store(self, scope: KnowledgeBaseScope):
        key = collection_name(scope)
        if key not in self._stores:
            from langchain_community.vectorstores.milvus import Milvus

            self._stores[key] = Milvus(
                embedding_function=self.embeddings.embeddings,
                collection_name=key,
                connection_args={"uri": self.settings.milvus_uri, "token": self.settings.milvus_token},
                index_params=milvus_index_params(self.settings),
                search_params=milvus_search_params(self.settings),
                text_field="text",
                metadata_field="metadata",
                auto_id=False,
                drop_old=False,
            )
        return self._stores[key]


def create_vector_store(settings: Settings, embeddings: EmbeddingProvider) -> VectorStore:
    store = settings.vector_store.lower()
    if store == "chroma":
        return LangChainChromaVectorStore(settings.chroma_persist_dir, embeddings, settings.vector_upsert_batch_size)
    if store in {"milvus", "milvus_with_keyword_fallback"}:
        return LangChainMilvusVectorStore(settings, embeddings)
    raise ValueError(f"Unsupported vector store: {settings.vector_store}")


def to_document(chunk: dict[str, Any], scope: KnowledgeBaseScope) -> Document:
    metadata = sanitize_metadata(
        {
            **chunk.get("metadata", {}),
            "tenant_id": scope.tenant_id,
            "kb_id": scope.kb_id,
            "chunk_id": chunk["id"],
        }
    )
    return Document(page_content=chunk["text"], metadata=metadata)


def batched(items: list[dict[str, Any]], batch_size: int) -> list[list[dict[str, Any]]]:
    size = max(int(batch_size), 1)
    return [items[start:start + size] for start in range(0, len(items), size)]


def from_document(document: Document, score: float, extra_metadata: dict[str, Any] | None = None) -> VectorSearchResult:
    metadata = dict(document.metadata or {})
    if extra_metadata:
        metadata.update(extra_metadata)
    return VectorSearchResult(
        chunk_id=str(metadata.get("chunk_id") or metadata.get("pk") or ""),
        text=document.page_content,
        metadata=metadata,
        score=score,
    )


def chroma_filter(scope: KnowledgeBaseScope, metadata_filter: dict[str, Any] | None) -> dict[str, Any]:
    clauses: list[dict[str, Any]] = [{"tenant_id": scope.tenant_id}, {"kb_id": scope.kb_id}]
    for key, value in (metadata_filter or {}).items():
        if isinstance(value, (str, int, float, bool)):
            clauses.append({key: value})
    if len(clauses) == 1:
        return clauses[0]
    return {"$and": clauses}


def milvus_filter(scope: KnowledgeBaseScope, metadata_filter: dict[str, Any] | None) -> str:
    clauses = [f'metadata["tenant_id"] == "{escape(scope.tenant_id)}"', f'metadata["kb_id"] == "{escape(scope.kb_id)}"']
    for key, value in (metadata_filter or {}).items():
        if isinstance(value, str):
            clauses.append(f'metadata["{escape(key)}"] == "{escape(value)}"')
        elif isinstance(value, bool):
            clauses.append(f'metadata["{escape(key)}"] == {str(value).lower()}')
        elif isinstance(value, (int, float)):
            clauses.append(f'metadata["{escape(key)}"] == {value}')
    return " and ".join(clauses)


def sanitize_metadata(metadata: dict[str, Any]) -> dict[str, str | int | float | bool]:
    sanitized: dict[str, str | int | float | bool] = {}
    for key, value in metadata.items():
        if value is None:
            continue
        if isinstance(value, (str, int, float, bool)):
            sanitized[key] = value
        else:
            sanitized[key] = str(value)
    return sanitized


def collection_name(scope: KnowledgeBaseScope) -> str:
    digest = hashlib.sha1(f"{scope.tenant_id}:{scope.kb_id}".encode("utf-8")).hexdigest()[:24]
    return f"kb_{digest}"


def milvus_index_params(settings: Settings) -> dict[str, Any]:
    metric_type = normalize_milvus_metric_type(settings.milvus_metric_type)
    index_type = (settings.milvus_index_type or "HNSW").strip().upper()
    if index_type == "HNSW":
        return {
            "metric_type": metric_type,
            "index_type": "HNSW",
            "params": {
                "M": max(int(settings.milvus_hnsw_m), 4),
                "efConstruction": max(int(settings.milvus_hnsw_ef_construction), 16),
            },
        }
    return {"metric_type": metric_type, "index_type": index_type, "params": {}}


def milvus_search_params(settings: Settings, top_k: int | None = None) -> dict[str, Any]:
    metric_type = normalize_milvus_metric_type(settings.milvus_metric_type)
    index_type = (settings.milvus_index_type or "HNSW").strip().upper()
    if index_type == "HNSW":
        ef = max(int(settings.milvus_search_ef), 16)
        if top_k is not None:
            ef = max(ef, int(top_k) + 16)
        return {"metric_type": metric_type, "params": {"ef": ef}}
    return {"metric_type": metric_type, "params": {}}


def milvus_metric_type(store: Any, default_metric: str) -> str:
    collection = getattr(store, "col", None)
    if collection is not None:
        for index in getattr(collection, "indexes", []) or []:
            params = getattr(index, "params", None)
            if isinstance(params, dict):
                metric = params.get("metric_type")
                if metric:
                    return normalize_milvus_metric_type(str(metric))
    return normalize_milvus_metric_type(default_metric)


def normalize_milvus_metric_type(metric_type: str | None) -> str:
    value = (metric_type or "L2").strip().upper()
    if value in {"COSINE", "IP", "L2"}:
        return value
    return "L2"


def milvus_similarity_score(raw_score: float, metric_type: str) -> float:
    metric = normalize_milvus_metric_type(metric_type)
    if metric == "L2":
        return clamp01(1.0 / (1.0 + max(raw_score, 0.0)))
    if metric == "IP":
        return clamp01((raw_score + 1.0) / 2.0)
    if metric == "COSINE":
        return clamp01((raw_score + 1.0) / 2.0)
    return clamp01(raw_score)


def clamp01(value: float) -> float:
    return max(0.0, min(float(value), 1.0))


def chunk_doc_id(chunks: list[dict[str, Any]]) -> str | None:
    for chunk in chunks:
        metadata = chunk.get("metadata") or {}
        doc_id = metadata.get("doc_id")
        if doc_id is not None:
            return str(doc_id)
    return None


def delete_chroma_document(store: Any, scope: KnowledgeBaseScope, doc_id: str | None) -> None:
    if not doc_id:
        return
    raw = store.get(where=chroma_filter(scope, {"doc_id": doc_id}), include=["metadatas"])
    ids = raw.get("ids", [])
    if ids:
        store.delete(ids=ids)


def delete_chroma_document_by_name(persist_dir: str, scope: KnowledgeBaseScope, doc_id: str | None) -> None:
    if not doc_id:
        return
    import chromadb
    from chromadb.errors import InvalidCollectionException

    client = chromadb.PersistentClient(path=persist_dir)
    try:
        collection = client.get_collection(collection_name(scope))
    except (ValueError, InvalidCollectionException):
        return
    raw = collection.get(where=chroma_filter(scope, {"doc_id": doc_id}), include=["metadatas"])
    ids = raw.get("ids", [])
    if ids:
        collection.delete(ids=ids)


def delete_milvus_document(store: Any, scope: KnowledgeBaseScope, doc_id: str | None) -> None:
    if not doc_id or store.col is None:
        return
    store.col.delete(expr=milvus_filter(scope, {"doc_id": doc_id}))


def delete_milvus_document_by_name(settings: Settings, scope: KnowledgeBaseScope, doc_id: str | None) -> None:
    if not doc_id:
        return
    from pymilvus import Collection, connections, utility

    name = collection_name(scope)
    alias = f"delete_{name}"
    connect_kwargs = {"alias": alias, "uri": settings.milvus_uri}
    if settings.milvus_token:
        connect_kwargs["token"] = settings.milvus_token
    connections.connect(**connect_kwargs)
    if not utility.has_collection(name, using=alias):
        return
    collection = Collection(name, using=alias)
    collection.delete(expr=milvus_filter(scope, {"doc_id": doc_id}))


def escape(value: str) -> str:
    return re.sub(r'(["\\\\])', r"\\\1", value)
