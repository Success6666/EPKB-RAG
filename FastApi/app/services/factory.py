from functools import lru_cache

from app.core.config import get_settings
from app.langchain_modules.chains.rag_chain import HybridRetrievalService
from app.langchain_modules.model_io.embeddings import EmbeddingProvider, create_embedding_provider, normalize_embedding_provider
from app.langchain_modules.model_io.generation import OllamaGenerationClient
from app.langchain_modules.retrieval.document_processor import DocumentProcessor
from app.langchain_modules.retrieval.vector_store import VectorStore, create_vector_store
from app.services.ingestion import DocumentIngestionService
from app.services.java_callback import JavaDocumentStatusCallback
from app.services.mysql_repository import MySqlRepository
from app.schemas.documents import DocumentIngestJob
from app.schemas.rag import RetrievalQuery


_dynamic_vector_stores: dict[tuple[str, str, str, str, str], VectorStore] = {}


@lru_cache
def get_embedding_provider() -> EmbeddingProvider:
    return create_embedding_provider(get_settings())


@lru_cache
def get_vector_store() -> VectorStore:
    return create_vector_store(get_settings(), get_embedding_provider())


def resolve_vector_store_for_request(request: RetrievalQuery) -> VectorStore:
    if not request.embedding_provider:
        return get_vector_store()
    return resolve_vector_store_from_embedding_config(
        embedding_provider=request.embedding_provider,
        embedding_model=request.embedding_model,
        embedding_base_url=request.embedding_base_url,
        embedding_api_key=request.embedding_api_key,
        embedding_truncate=request.embedding_truncate,
    )


def resolve_vector_store_for_document_job(job: DocumentIngestJob) -> VectorStore:
    if not job.embedding_provider:
        return get_vector_store()
    return resolve_vector_store_from_embedding_config(
        embedding_provider=job.embedding_provider,
        embedding_model=job.embedding_model,
        embedding_base_url=job.embedding_base_url,
        embedding_api_key=job.embedding_api_key,
        embedding_truncate=job.embedding_truncate,
    )


def resolve_vector_store_from_embedding_config(
    embedding_provider: str,
    embedding_model: str | None,
    embedding_base_url: str | None,
    embedding_api_key: str | None,
    embedding_truncate: str | None,
) -> VectorStore:
    settings = get_settings()
    provider = normalize_embedding_provider(embedding_provider)
    if provider == "sentence_transformers":
        model = embedding_model or settings.sentence_transformer_model
        scoped_settings = settings.model_copy(update={"embedding_provider": provider, "sentence_transformer_model": model})
        key = (provider, model, "", "", "")
    elif provider == "ollama":
        model = embedding_model or settings.ollama_embedding_model
        base_url = embedding_base_url or settings.ollama_base_url
        scoped_settings = settings.model_copy(update={
            "embedding_provider": provider,
            "ollama_embedding_model": model,
            "ollama_base_url": base_url,
        })
        key = (provider, model, base_url, "", "")
    elif provider == "nvidia":
        model = embedding_model or settings.nvidia_embedding_model
        base_url = embedding_base_url or settings.nvidia_base_url
        api_key = embedding_api_key or settings.nvidia_api_key
        truncate = embedding_truncate or settings.nvidia_embedding_truncate
        scoped_settings = settings.model_copy(update={
            "embedding_provider": provider,
            "nvidia_embedding_model": model,
            "nvidia_base_url": base_url,
            "nvidia_api_key": api_key,
            "nvidia_embedding_truncate": truncate,
        })
        key = (provider, model, base_url, truncate, api_key or "")
    else:
        raise ValueError(f"Unsupported embedding provider: {embedding_provider}")
    if key not in _dynamic_vector_stores:
        _dynamic_vector_stores[key] = create_vector_store(scoped_settings, create_embedding_provider(scoped_settings))
    return _dynamic_vector_stores[key]


@lru_cache
def get_document_processor() -> DocumentProcessor:
    return DocumentProcessor(get_settings())


@lru_cache
def get_ollama_client() -> OllamaGenerationClient:
    return OllamaGenerationClient(get_settings())


@lru_cache
def get_mysql_repository() -> MySqlRepository:
    return MySqlRepository(get_settings())


@lru_cache
def get_java_callback() -> JavaDocumentStatusCallback:
    return JavaDocumentStatusCallback(get_settings())


def get_ingestion_service() -> DocumentIngestionService:
    return DocumentIngestionService(
        processor=get_document_processor(),
        vector_store=get_vector_store(),
        mysql_repository=get_mysql_repository(),
        vector_store_resolver=resolve_vector_store_for_document_job,
    )


def get_retrieval_service() -> HybridRetrievalService:
    return HybridRetrievalService(
        settings=get_settings(),
        vector_store=get_vector_store(),
        generator=get_ollama_client(),
        mysql_repository=get_mysql_repository(),
        embedding_store_resolver=resolve_vector_store_for_request,
    )
