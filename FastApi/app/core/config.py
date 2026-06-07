from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "Enterprise Private Knowledge Base RAG"
    app_version: str = "0.1.0"
    api_prefix: str = "/api/v1"
    runtime_gc_enabled: bool = True
    runtime_gc_interval_seconds: int = 300
    runtime_malloc_trim_enabled: bool = True
    runtime_gc_log_enabled: bool = False

    upload_dir: str = "./data/uploads"
    chroma_persist_dir: str = "./data/chroma"
    vector_store: str = Field(default="chroma", description="chroma, milvus, or milvus_with_keyword_fallback")

    milvus_uri: str = "http://localhost:19530"
    milvus_token: str | None = None
    milvus_db_name: str = "default"
    milvus_metric_type: str = "L2"
    milvus_index_type: str = "HNSW"
    milvus_hnsw_m: int = 16
    milvus_hnsw_ef_construction: int = 200
    milvus_search_ef: int = 128

    embedding_provider: str = Field(default="nvidia", description="sentence_transformers, ollama, or nvidia")
    generation_provider: str = Field(default="ollama", description="ollama, deepseek, dashscope, or openai-compatible")
    default_chat_model: str | None = None
    default_embedding_model: str | None = None
    sentence_transformer_model: str = "BAAI/bge-small-zh-v1.5"
    ollama_base_url: str = "http://localhost:11434"
    ollama_embedding_model: str = "nomic-embed-text"
    ollama_generation_model: str = "qwen2.5:7b"
    ollama_timeout_seconds: int = 120
    nvidia_api_key: str | None = None
    nvidia_base_url: str = "https://integrate.api.nvidia.com/v1"
    nvidia_embedding_model: str = "nvidia/nv-embedqa-e5-v5"
    nvidia_embedding_truncate: str = "NONE"
    nvidia_embedding_encoding_format: str = "float"
    openai_api_key: str | None = None
    openai_base_url: str = "https://api.openai.com/v1"
    openai_model: str = "gpt-4o-mini"
    openai_compatible_api_key: str | None = None
    openai_compatible_base_url: str | None = None
    deepseek_api_key: str | None = None
    deepseek_base_url: str = "https://api.deepseek.com"
    dashscope_api_key: str | None = None
    dashscope_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"

    chunk_size: int = 800
    chunk_overlap: int = 120
    parent_chunk_size: int = 2400
    parent_chunk_overlap: int = 240
    child_chunk_size: int = 520
    child_chunk_overlap: int = 80
    child_chunks_per_parent: int = 3
    query_rewrite_enabled: bool = True
    query_rewrite_min_chars: int = 8
    query_rewrite_max_history_messages: int = 6
    llm_context_refinement_enabled: bool = True
    llm_context_refinement_max_hits: int = 8
    ocr_enabled: bool = True
    ocr_min_confidence: float = 0.35
    ocr_max_images_per_document: int = 80
    ocr_pdf_max_pages: int = 80
    ocr_pdf_min_text_chars: int = 30
    ocr_render_dpi: int = 220
    ocr_min_image_side: int = 1200
    ocr_max_image_side: int = 2600
    ocr_metadata_raw_max_chars: int = 12000
    ocr_strategy: str = Field(default="auto", description="auto, ocr_only, vision_first, or hybrid")
    ocr_low_confidence_threshold: float = 0.55
    ocr_complex_layout_min_lines: int = 24
    ocr_vision_model: str | None = None
    ocr_vision_model_keywords: str = "vl,vision,llava,internvl,minicpm-v,qwen-vl,qwen2.5-vl,gpt-4o"
    ocr_vision_timeout_seconds: int = 45
    ocr_vision_max_image_side: int = 1800
    ocr_vision_max_chars: int = 8000
    ocr_llm_refinement_enabled: bool = True
    ocr_llm_refinement_min_chars: int = 40
    ocr_llm_refinement_max_chars: int = 6000
    ocr_llm_refinement_timeout_seconds: int = 20
    hallucination_min_score: float = 0.15
    max_keyword_scan_chunks: int = 1000
    default_top_k: int = 5
    vector_weight: float = 0.7
    keyword_weight: float = 0.3
    retrieval_candidate_multiplier: int = 4
    hybrid_query_expansion_enabled: bool = True
    hybrid_query_expansion_max_queries: int = 3
    metadata_boost_enabled: bool = True
    metadata_boost_weight: float = 0.12
    rerank_enabled: bool = True
    rerank_provider: str = "deepseek"
    rerank_model: str = "deepseek-v4-flash"
    rerank_base_url: str | None = None
    rerank_api_key: str | None = None
    rerank_timeout_seconds: int = 60
    rerank_top_n: int = 40
    rerank_weight: float = 0.55
    rerank_batch_size: int = 16

    mysql_dsn: str = "mysql+aiomysql://rag_user:change_me_mysql@localhost:3306/rag_platform"
    mysql_connect_timeout_seconds: int = 5
    mysql_read_timeout_seconds: int = 30
    mysql_write_timeout_seconds: int = 30
    mysql_keyword_fulltext_enabled: bool = True
    mysql_keyword_like_fallback_enabled: bool = True

    rabbitmq_url: str = "amqp://guest:guest@localhost:5672/%2F"
    rabbitmq_queue: str = "rag.document.ingest"
    rabbitmq_document_exchange: str = "rag.document.exchange"
    rabbitmq_document_routing_key: str = "rag.document.index"
    rabbitmq_document_dlx: str = "rag.document.dlx"
    rabbitmq_document_dlq_routing_key: str = "rag.document.dead"
    rabbitmq_document_dlq: str = "rag.document.ingest.dlq"
    rabbitmq_prefetch_count: int = 3
    rabbitmq_max_retries: int = 3
    rabbitmq_processing_timeout_seconds: int = 1800
    rag_ingest_concurrency: int = 3

    java_callback_base_url: str | None = None
    java_callback_path: str = "/api/documents/internal/status"
    java_callback_url: str | None = None
    java_callback_token: str | None = None
    java_callback_token_header: str = "X-Internal-Token"
    java_callback_timeout_seconds: int = 10
    java_callback_max_attempts: int = 3


@lru_cache
def get_settings() -> Settings:
    return Settings()
